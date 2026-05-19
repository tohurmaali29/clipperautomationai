"""
FastAPI Backend - AI Video Clipper
Main application entry point dengan routes untuk:
- Analyze: Extract transcript dan AI analysis menggunakan Gemini API
- Generate Clip: Create video clip dengan trimming, cropping, dan subtitle hardcoding
- Generate Subtitle: Create subtitle file dalam format .ASS
- Download: Download hasil clip video
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel
from typing import Optional
import copy
import hashlib
import logging
import os
import tempfile
from config import Config
from services.transcript_service import get_transcript_result_async, extract_video_id
from services.gemini_service import analyze_transcript_result_async
from services.video_service import generate_clip_async
from services.subtitle_service import generate_subtitles_async

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and clean up app resources."""
    logger.info("Starting AI Video Clipper Backend...")
    if not Config.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set")

    logger.info("Backend initialization complete")
    yield
    logger.info("Shutting down AI Video Clipper Backend...")

# Create FastAPI app
app = FastAPI(
    title="AI Video Clipper",
    description="Automated YouTube video clipper dengan AI analysis menggunakan Gemini API",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware untuk frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
TRANSCRIPT_CACHE = {}
ANALYSIS_CACHE = {}

# ============ PYDANTIC MODELS ============

class AnalyzeRequest(BaseModel):
    """Request model untuk endpoint /analyze"""
    url: str
    mode: str = "viral"
    duration: int = 30

class ClipSegment(BaseModel):
    """Model untuk clip segment hasil AI analysis"""
    start: float
    end: float
    headline: str
    viral_score: int


class SubtitleSegmentEdit(BaseModel):
    start: float
    end: float
    text: str

class GenerateClipRequest(BaseModel):
    """Request model untuk endpoint /generate-clip"""
    url: str = ""
    clip: ClipSegment
    subtitle_lang: str = "id"
    subtitle_style: Optional[dict] = None  # Customizable: color, font, size, margin
    subtitles_enabled: bool = True
    export_aspect: str = "9:16"
    local_path: Optional[str] = None
    source_type: str = "youtube"
    subtitle_segments_override: Optional[list[SubtitleSegmentEdit]] = None

class SubtitleRequest(BaseModel):
    """Request model untuk endpoint /generate-subtitle"""
    transcript: str
    lang: str = "id"
    style: Optional[dict] = None  # Customization: color, font, size, margin

# ============ HEALTH CHECK ============

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve main dashboard."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "AI Video Clipper Backend",
        "version": "1.0.0"
    }

# ============ MAIN ENDPOINTS ============

@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    """
    Endpoint untuk menganalisis video YouTube:
    1. Fetch transcript dari YouTube
    2. Kirim ke Gemini API
    3. Return JSON dengan array of clips dan transcript
    """
    logger.info(f"Analyzing URL: {request.url}")
    
    try:
        video_id = extract_video_id(request.url)
        transcript_cache_hit = False
        analysis_cache_hit = False

        # Step 1: Get transcript
        logger.info("Fetching transcript...")
        transcript_result = _get_cached_transcript(video_id)
        if transcript_result:
            transcript_cache_hit = True
            logger.info("Using cached transcript for video: %s", video_id)
        else:
            transcript_result = await get_transcript_result_async(request.url)
            _store_transcript_cache(video_id, transcript_result)

        transcript = transcript_result["text"]
        
        if transcript_result["source"] == "mock":
            raise HTTPException(
                status_code=400,
                detail=transcript_result.get("error_reason") or "Transcript tidak tersedia. Video ini tidak memiliki subtitle atau tidak dapat di-fetch dari YouTube."
            )
        if not transcript:
            raise HTTPException(status_code=400, detail="Tidak bisa ambil transcript dari video ini")
        
        # Step 2: AI Analysis dengan Gemini API
        logger.info(f"Running AI analysis dengan mode: {request.mode}")
        analysis_cache_key = _build_analysis_cache_key(video_id, transcript, request.mode, request.duration)
        analysis_result = _get_cached_analysis(analysis_cache_key)
        if analysis_result:
            analysis_cache_hit = True
            logger.info("Using cached analysis for video: %s mode=%s duration=%s", video_id, request.mode, request.duration)
        else:
            analysis_result = await analyze_transcript_result_async(
                transcript=transcript,
                mode=request.mode,
                duration=request.duration,
                transcript_segments=transcript_result.get("segments", []),
                candidate_moments=transcript_result.get("heatmap_candidates", []),
                source_duration=transcript_result.get("source_duration", 0),
            )
            _store_analysis_cache(analysis_cache_key, analysis_result)
        
        # Step 3: Prepare response
        raw_clips = analysis_result.get("clips", [])
        clips = [_format_clip_for_frontend(clip) for clip in raw_clips]

        response_data = {
            "status": "success",
            "transcript": transcript,
            "clips": clips,
            "metadata": {
                "mode": request.mode,
                "duration": request.duration,
                "video_url": request.url,
                "source_duration": transcript_result.get("source_duration", 0),
                "transcript_source": transcript_result["source"],
                "analysis_source": analysis_result["source"],
                "demo_mode": transcript_result["used_fallback"] or analysis_result["used_fallback"],
                "heatmap_candidates_used": len(transcript_result.get("heatmap_candidates", [])),
                "cache": {
                    "transcript": transcript_cache_hit,
                    "analysis": analysis_cache_hit,
                },
            },
            "pipeline": {
                "transcript": {
                    **transcript_result,
                    "cache_hit": transcript_cache_hit,
                },
                "analysis": {
                    "source": analysis_result["source"],
                    "used_fallback": analysis_result["used_fallback"],
                    "cache_hit": analysis_cache_hit,
                },
            },
        }
        
        logger.info(f"Analysis complete, found {len(response_data['clips'])} clips")
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during analysis: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/analyze-upload")
async def analyze_upload(
    file: UploadFile = File(...),
    mode: str = Form("viral"),
    duration: int = Form(30),
):
    """Analyze a locally uploaded video/audio file as fallback when YouTube access fails."""
    logger.info("Analyzing uploaded file: %s", file.filename)

    temp_input_path = None
    try:
        suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
        upload_id = hashlib.sha1(f"{file.filename}-{os.urandom(8).hex()}".encode("utf-8")).hexdigest()[:12]
        stored_filename = f"source_{upload_id}{suffix}"
        temp_input_path = os.path.join(Config.UPLOAD_FOLDER, stored_filename)

        with open(temp_input_path, "wb") as handle:
            handle.write(await file.read())

        from services.transcript_service import transcribe_audio_file_async

        transcript_result = await transcribe_audio_file_async(temp_input_path)
        transcript = transcript_result["text"]

        if transcript_result["source"] == "mock" or not transcript:
            raise HTTPException(
                status_code=400,
                detail=transcript_result.get("error_reason") or "Gagal mentranskripsi file video lokal."
            )

        analysis_result = await analyze_transcript_result_async(
            transcript=transcript,
            mode=mode,
            duration=duration,
            source_duration=transcript_result.get("source_duration", 0),
        )

        clips = [_format_clip_for_frontend(clip) for clip in analysis_result.get("clips", [])]
        return {
            "status": "success",
            "transcript": transcript,
            "clips": clips,
            "metadata": {
                "mode": mode,
                "duration": duration,
                "video_url": "",
                "source_type": "local",
                "local_path": temp_input_path,
                "local_filename": stored_filename,
                "source_duration": transcript_result.get("source_duration", 0),
                "transcript_source": transcript_result["source"],
                "analysis_source": analysis_result["source"],
                "demo_mode": transcript_result["used_fallback"] or analysis_result["used_fallback"],
                "heatmap_candidates_used": 0,
                "cache": {
                    "transcript": False,
                    "analysis": False,
                },
            },
            "pipeline": {
                "transcript": {
                    **transcript_result,
                    "cache_hit": False,
                    "heatmap_candidates": [],
                },
                "analysis": {
                    "source": analysis_result["source"],
                    "used_fallback": analysis_result["used_fallback"],
                    "cache_hit": False,
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error during upload analysis: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/generate-clip")
async def generate_clip_endpoint(request: GenerateClipRequest):
    """
    Endpoint untuk generate video clip:
    1. Download video dari YouTube (temporary)
    2. Trim ke segment yang specified
    3. Crop dari 16:9 → 9:16 (untuk TikTok/Reels)
    4. Generate subtitle dalam format .ASS
    5. Hardcode subtitle ke video dengan FFmpeg
    6. Return path ke clip final
    """
    logger.info(f"Generating clip from {request.url}: {request.clip.start}s - {request.clip.end}s")
    
    try:
        # Generate clip dengan FFmpeg
        clip_result = await generate_clip_async(
            url=request.url,
            clip_data=request.clip.model_dump(),
            subtitle_lang=request.subtitle_lang,
            subtitle_style=request.subtitle_style,
            subtitles_enabled=request.subtitles_enabled,
            export_aspect=request.export_aspect,
            source_path=request.local_path,
            subtitle_segments_override=[
                segment.model_dump() for segment in (request.subtitle_segments_override or [])
            ] or None,
        )

        clip_path = clip_result["clip_path"]
        
        if not os.path.exists(clip_path):
            raise HTTPException(status_code=500, detail="Failed to generate clip")
        
        logger.info(f"Clip generated at: {clip_path}")
        
        return {
            "status": "success",
            "clip_path": clip_path,
            "file_size_mb": os.path.getsize(clip_path) / (1024 * 1024),
            "subtitle_segments": clip_result.get("subtitle_segments", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating clip: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/generate-subtitle")
async def generate_subtitle_endpoint(request: SubtitleRequest):
    """
    Endpoint untuk generate subtitle dalam format .ASS:
    - Support customizable color, font, size, margin
    - Return subtitle content atau file path
    """
    logger.info(f"Generating subtitle in language: {request.lang}")
    
    try:
        subtitle_content = await generate_subtitles_async(
            transcript=request.transcript,
            lang=request.lang,
            style=request.style
        )
        
        logger.info("Subtitle generated successfully")
        
        return {
            "status": "success",
            "subtitle": subtitle_content,
            "format": "ass",
            "language": request.lang
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating subtitle: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """
    Download file dari uploads folder
    """
    logger.info(f"Download requested for: {file_path}")
    
    try:
        # Normalize any incoming path to a safe basename.
        normalized = os.path.basename(str(file_path).replace("\\", "/"))

        # Validate filename (security: prevent path traversal)
        if not normalized or normalized in {".", ".."}:
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        resolved_path = os.path.join(Config.UPLOAD_FOLDER, normalized)
        
        if not os.path.exists(resolved_path):
            logger.warning(f"File not found: {resolved_path}")
            raise HTTPException(status_code=404, detail="File not found")
        
        logger.info(f"Returning file: {resolved_path}")
        return FileResponse(
            path=resolved_path,
            filename=normalized,
            media_type='video/mp4'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Download failed")


def _format_clip_for_frontend(clip: dict) -> dict:
    """Normalize clip response so the frontend can render it directly."""
    start = float(clip["start"])
    end = float(clip["end"])
    headline = clip["headline"]
    clip_id = hashlib.sha1(f"{start:.3f}:{end:.3f}:{headline}".encode("utf-8")).hexdigest()[:12]
    return {
        "clip_id": clip_id,
        "start": start,
        "end": end,
        "headline": headline,
        "viral_score": int(clip["viral_score"]),
        "heatmap_score": float(clip.get("heatmap_score", 0) or 0),
        "title": headline,
        "reason": f"AI viral score {int(clip['viral_score'])}/100",
        "summary": f"Clip ini membahas {headline.lower()}.",
        "score": int(clip["viral_score"]),
        "start_time": _seconds_to_label(start),
        "end_time": _seconds_to_label(end),
    }


def _seconds_to_label(value: float) -> str:
    total_seconds = int(value)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _build_analysis_cache_key(video_id: Optional[str], transcript: str, mode: str, duration: int) -> str:
    transcript_hash = hashlib.sha1(transcript.encode("utf-8")).hexdigest()
    return f"{video_id or 'unknown'}::{mode}::{duration}::{transcript_hash}"


def _get_cached_transcript(video_id: Optional[str]) -> Optional[dict]:
    if not video_id:
        return None
    cached = TRANSCRIPT_CACHE.get(video_id)
    if not cached:
        return None
    return copy.deepcopy(cached)


def _store_transcript_cache(video_id: Optional[str], transcript_result: dict) -> None:
    if not video_id:
        return
    if transcript_result.get("used_fallback"):
        return
    TRANSCRIPT_CACHE[video_id] = copy.deepcopy(transcript_result)


def _get_cached_analysis(cache_key: str) -> Optional[dict]:
    cached = ANALYSIS_CACHE.get(cache_key)
    if not cached:
        return None
    return copy.deepcopy(cached)


def _store_analysis_cache(cache_key: str, analysis_result: dict) -> None:
    if analysis_result.get("used_fallback"):
        return
    ANALYSIS_CACHE[cache_key] = copy.deepcopy(analysis_result)

# ============ ERROR HANDLERS ============

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "detail": "Internal server error"
        }
    )

# ============ RUN ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        log_level="info"
    )
