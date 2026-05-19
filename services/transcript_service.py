"""
Transcript Service - transkripsi audio dari YouTube video dan file lokal
Menggunakan Whisper sebagai jalur utama untuk sumber YouTube dan upload lokal.
"""

import asyncio
import logging
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from time import perf_counter
from config import Config

try:
    import yt_dlp
except Exception:  # pragma: no cover - environment dependent
    yt_dlp = None

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - environment dependent
    WhisperModel = None

logger = logging.getLogger(__name__)

FFMPEG_CMD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffmpeg.exe")
if not os.path.exists(FFMPEG_CMD):
    FFMPEG_CMD = "ffmpeg"

FFPROBE_CMD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffprobe.exe")
if not os.path.exists(FFPROBE_CMD):
    FFPROBE_CMD = "ffprobe"

TRANSCRIPT_UNAVAILABLE_REASON = "Transcript could not be generated from the video audio. Please try another video or use Analyze Local."


@contextmanager
def _without_broken_proxy():
    """
    Temporarily remove proxy env vars that point to a dead local proxy.
    """
    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]
    original_values = {key: os.environ.get(key) for key in proxy_keys}

    try:
        for key, value in original_values.items():
            if value and "127.0.0.1:9" in value:
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in original_values.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

async def get_transcript_result_async(url: str) -> dict:
    """
    Async function untuk generate transcript dari audio video YouTube
    
    Args:
        url: YouTube video URL
    
    Returns:
        Transcript text atau mock transcript jika gagal
    
    Raises:
        ValueError: Jika URL invalid
    """
    try:
        logger.info(f"Preparing audio transcription for: {url}")
        
        # Extract video ID dari URL
        video_id = extract_video_id(url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")
        
        logger.info(f"Video ID: {video_id}")
        
        # Run audio transcription pipeline in thread pool
        transcript_result = await asyncio.to_thread(_fetch_transcript_sync, video_id)
        transcript_result["used_fallback"] = transcript_result.get("source") == "mock"

        logger.info("Transcript generated successfully")
        return transcript_result
        
    except Exception as e:
        logger.error(f"Error generating transcript: {str(e)}")
        logger.info("Using mock transcript because the audio transcription pipeline failed")
        return {
            "text": generate_mock_transcript(),
            "source": "mock",
            "used_fallback": True,
            "error_reason": TRANSCRIPT_UNAVAILABLE_REASON,
            "error_code": "transcript_unavailable",
        }


async def get_transcript_async(url: str) -> str:
    """Backward-compatible helper returning transcript text only."""
    result = await get_transcript_result_async(url)
    return result["text"]


def _fetch_transcript_sync(video_id: str) -> dict:
    """
    Synchronous helper function untuk generate transcript
    Dijalankan di thread pool dari async function
    """
    try:
        total_started = perf_counter()

        started = perf_counter()
        whisper_result = _fetch_transcript_with_whisper(video_id)
        logger.info("Transcript stage whisper_youtube completed in %.2fs", perf_counter() - started)
        if whisper_result["text"]:
            logger.info("Transcript extracted via Whisper audio transcription")
            logger.info("Transcript pipeline completed in %.2fs", perf_counter() - total_started)
            return _build_transcript_result(
                whisper_result["text"],
                "whisper_youtube",
                [],
                [],
                source_duration=float(whisper_result.get("source_duration") or 0),
            )

        logger.warning("Audio transcription did not produce transcript text for this video")
        logger.info("Transcript pipeline completed in %.2fs", perf_counter() - total_started)
        return _build_transcript_result(
            generate_mock_transcript(),
            "mock",
            [],
            [],
            source_duration=float(whisper_result.get("source_duration") or 0),
            error_reason=TRANSCRIPT_UNAVAILABLE_REASON,
            error_code="transcript_unavailable",
        )
        
    except Exception as e:
        logger.error(f"Transcript service error: {str(e)}")
        return _build_transcript_result(
            generate_mock_transcript(),
            "mock",
            [],
            [],
            source_duration=0.0,
            error_reason=TRANSCRIPT_UNAVAILABLE_REASON,
            error_code="transcript_unavailable",
        )


def _fetch_transcript_with_whisper(video_id: str) -> dict:
    """Transcribe a YouTube video by downloading its audio and running Whisper locally."""
    if yt_dlp is None:
        logger.info("yt-dlp is unavailable for YouTube audio transcription")
        return {"text": "", "source_duration": 0.0}

    if WhisperModel is None:
        logger.info("faster-whisper is unavailable for audio transcription")
        return {"text": "", "source_duration": 0.0}

    url = f"https://www.youtube.com/watch?v={video_id}"
    temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
    output_template = os.path.join(temp_dir, f"{video_id}.%(ext)s")
    base_ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
    }

    downloaded_path = ""

    try:
        downloaded_path, duration_seconds = _download_audio_for_whisper(url, base_ydl_opts)

        if not downloaded_path or not os.path.exists(downloaded_path):
            logger.warning("Audio download step did not produce a usable audio file")
            return {"text": "", "source_duration": float(duration_seconds or 0)}

        logger.info(
            "Running Whisper transcription with model=%s device=%s compute_type=%s",
            Config.WHISPER_MODEL,
            Config.WHISPER_DEVICE,
            Config.WHISPER_COMPUTE_TYPE,
        )
        model = WhisperModel(
            Config.WHISPER_MODEL,
            device=Config.WHISPER_DEVICE,
            compute_type=Config.WHISPER_COMPUTE_TYPE,
        )

        chunk_paths = _prepare_whisper_chunks(
            downloaded_path,
            duration_seconds,
            temp_dir,
        )
        if not chunk_paths:
            chunk_paths = [downloaded_path]

        transcript_parts = []
        for index, chunk_path in enumerate(chunk_paths, start=1):
            logger.info("Transcribing Whisper chunk %s/%s", index, len(chunk_paths))
            segments, _ = model.transcribe(
                chunk_path,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            chunk_text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
            if chunk_text:
                transcript_parts.append(chunk_text)

        text = " ".join(transcript_parts)
        return {
            "text": text.strip(),
            "source_duration": float(duration_seconds or 0),
        }
    except Exception as exc:
        logger.warning("Whisper transcription failed: %s", exc)
        return {"text": "", "source_duration": 0.0}
    finally:
        _cleanup_temp_dir(temp_dir)


def _download_audio_for_whisper(url: str, base_ydl_opts: dict) -> tuple[str, float]:
    """Download audio for Whisper directly from a public YouTube URL."""
    try:
        with _without_broken_proxy():
            with yt_dlp.YoutubeDL(base_ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info), float(info.get("duration") or 0)
    except Exception as exc:
        logger.warning("Whisper audio download failed: %s", exc)
        raise


def _prepare_whisper_chunks(
    audio_path: str,
    duration_seconds: float,
    temp_dir: str,
) -> list[str]:
    """Split long audio into smaller WAV chunks for lower memory transcription."""
    max_audio_seconds = max(0, Config.WHISPER_MAX_AUDIO_SECONDS)
    chunk_seconds = max(30, Config.WHISPER_CHUNK_SECONDS)

    target_duration = duration_seconds or max_audio_seconds
    if max_audio_seconds > 0 and duration_seconds and duration_seconds > max_audio_seconds:
        logger.info(
            "Limiting Whisper transcription to first %ss out of %.0fs audio",
            max_audio_seconds,
            duration_seconds,
        )
        target_duration = max_audio_seconds

    chunk_paths = []
    start_seconds = 0
    chunk_index = 0

    while start_seconds < target_duration:
        current_duration = min(chunk_seconds, target_duration - start_seconds)
        if current_duration <= 0:
            break

        chunk_path = os.path.join(temp_dir, f"whisper_chunk_{chunk_index:03d}.wav")
        if not _export_audio_chunk(audio_path, chunk_path, start_seconds, current_duration):
            logger.warning("Failed to export audio chunk at %ss", start_seconds)
            return []

        chunk_paths.append(chunk_path)
        start_seconds += current_duration
        chunk_index += 1

    return chunk_paths


def _export_audio_chunk(input_path: str, output_path: str, start_seconds: float, duration_seconds: float) -> bool:
    """Use FFmpeg to normalize and export a chunked WAV file for Whisper."""
    cmd = [
        FFMPEG_CMD,
        "-ss", str(start_seconds),
        "-t", str(duration_seconds),
        "-i", input_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        "-y",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as exc:
        logger.warning("FFmpeg chunk export failed to start: %s", exc)
        return False

    if result.returncode != 0:
        logger.warning("FFmpeg chunk export failed: %s", result.stderr)
        return False

    return os.path.exists(output_path)

def _build_transcript_result(
    text: str,
    source: str,
    segments: list[dict],
    heatmap_candidates: list[dict],
    source_duration: float | None = None,
    error_reason: str | None = None,
    error_code: str | None = None,
) -> dict:
    return {
        "text": text,
        "source": source,
        "segments": segments or [],
        "heatmap_candidates": heatmap_candidates or [],
        "source_duration": float(source_duration or 0),
        "error_reason": error_reason,
        "error_code": error_code,
    }


def _cleanup_temp_dir(path: str) -> None:
    """Best-effort cleanup for temporary transcript assets."""
    if not path or not os.path.exists(path):
        return

    for root, _, files in os.walk(path, topdown=False):
        for filename in files:
            file_path = os.path.join(root, filename)
            try:
                os.remove(file_path)
            except Exception as exc:
                logger.warning("Failed to remove temp file %s: %s", file_path, exc)

    try:
        os.rmdir(path)
    except Exception as exc:
        logger.warning("Failed to remove temp dir %s: %s", path, exc)


def _probe_media_duration_seconds(media_path: str) -> float:
    """Return media duration in seconds via ffprobe when available."""
    if not media_path or not os.path.exists(media_path):
        return 0.0

    cmd = [
        FFPROBE_CMD,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        media_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return 0.0
        return float((result.stdout or "0").strip() or 0)
    except Exception:
        return 0.0

def generate_mock_transcript() -> str:
    """
    Generate mock transcript untuk demo purposes
    Digunakan ketika pipeline audio transcription gagal
    """
    return (
        "Dalam era digital ini, teknologi AI telah mengubah cara kita bekerja dan berkarya. "
        "Video ini membahas tentang bagaimana automasi dapat meningkatkan efisiensi produksi konten. "
        "Terutama untuk platform media sosial seperti TikTok dan Instagram Reels yang membutuhkan konten berkualitas tinggi. "
        "Klip viral biasanya datang dari momen yang paled menarik atau yang paling unexpected dalam sebuah video. "
        "Dengan menggunakan AI untuk analisis, kita bisa mengidentifikasi segment mana yang paling potensial menjadi viral. "
        "Tools seperti ini sangat membantu content creators dalam mengoptimalkan output mereka. "
        "Setiap detik harus bernilai dan menarik perhatian audiens dalam waktu singkat."
    )


def extract_video_id(url: str) -> str:
    """
    Extract video ID dari berbagai format YouTube URL
    
    Supported formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/watch?v=VIDEO_ID&t=start_time
    
    Args:
        url: YouTube URL
    
    Returns:
        Video ID (11 chars) atau None jika invalid
    """
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    logger.warning(f"Could not extract video ID from URL: {url}")
    return None

# Backward compatibility
def get_transcript(url: str) -> str:
    """
    Synchronous wrapper untuk backward compatibility
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(get_transcript_async(url))


async def transcribe_audio_file_async(audio_file_path: str) -> dict:
    """
    Transcribe audio file menggunakan Whisper
    
    Args:
        audio_file_path: Path ke file audio yang akan ditranskrip
        
    Returns:
        Dict dengan text transcript dan metadata
    """
    if WhisperModel is None:
        logger.error("faster-whisper is unavailable for audio transcription")
        return {
            "text": generate_mock_transcript(),
            "source": "mock",
            "used_fallback": True,
        }
    
    try:
        logger.info(f"Transcribing audio file: {audio_file_path}")
        
        # Load Whisper model
        model = WhisperModel(
            Config.WHISPER_MODEL,
            device=Config.WHISPER_DEVICE,
            compute_type=Config.WHISPER_COMPUTE_TYPE,
        )
        
        # Transcribe audio
        segments, info = model.transcribe(
            audio_file_path,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        
        # Combine all segments
        transcript_parts = []
        for segment in segments:
            if segment.text.strip():
                transcript_parts.append(segment.text.strip())
        
        text = " ".join(transcript_parts).strip()
        
        if not text:
            logger.warning("Whisper transcription produced empty text")
            return {
                "text": generate_mock_transcript(),
                "source": "mock",
                "used_fallback": True,
            }
        
        logger.info("Audio transcription completed successfully")
        return {
            "text": text,
            "source": "whisper_upload",
            "used_fallback": False,
            "language": info.language,
            "language_probability": info.language_probability,
            "source_duration": _probe_media_duration_seconds(audio_file_path),
        }
        
    except Exception as e:
        logger.error(f"Error transcribing audio file: {str(e)}")
        return {
            "text": generate_mock_transcript(),
            "source": "mock",
            "used_fallback": True,
        }
