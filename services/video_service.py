"""
Video Service - Generate video clip dengan FFmpeg
Handle: Trimming, Cropping (16:9 → 9:16), dan Hardcoding Subtitle
"""

import os
import subprocess
import logging
import asyncio
import uuid
import tempfile
import re
from contextlib import contextmanager
from time import perf_counter
from typing import Dict, Optional
from config import Config
from services.subtitle_service import build_ass_from_segments, generate_subtitles_async

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - environment dependent
    WhisperModel = None

logger = logging.getLogger(__name__)

# Path ke ffmpeg executable
# Try local ffmpeg.exe first, then fallback to PATH
FFMPEG_CMD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffmpeg.exe")
if not os.path.exists(FFMPEG_CMD):
    # Fallback to system ffmpeg
    FFMPEG_CMD = "ffmpeg"
    logger.info("Using system FFmpeg from PATH")
else:
    logger.info(f"Using local FFmpeg: {FFMPEG_CMD}")


@contextmanager
def _without_broken_proxy():
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


async def generate_clip_async(
    url: str,
    clip_data: Dict,
    subtitle_lang: str = "id",
    subtitle_style: Optional[Dict] = None,
    subtitles_enabled: bool = True,
    export_aspect: str = "9:16",
    source_path: Optional[str] = None,
    subtitle_segments_override: Optional[list[Dict]] = None,
) -> Dict:
    """
    Async function untuk generate video clip:
    1. Download video dari YouTube (temporary)
    2. Trim ke segment specified
    3. Crop dari 16:9 → 9:16 (untuk vertical video)
    4. Generate subtitle .ASS
    5. Hardcode subtitle ke video
    
    Args:
        url: YouTube video URL
        clip_data: Clip segment {start, end, headline, viral_score}
        subtitle_lang: Language subtitle
        subtitle_style: Custom style
    
    Returns:
        Path ke file video clip final
    """
    
    try:
        logger.info(f"Starting clip generation for {url}")
        logger.info(f"Segment: {clip_data['start']}s - {clip_data['end']}s")
        started = perf_counter()
        
        # Run di thread pool karena FFmpeg process blocking
        clip_result = await asyncio.to_thread(
            _generate_clip_sync,
            url,
            clip_data,
            subtitle_lang,
            subtitle_style,
            subtitles_enabled,
            export_aspect,
            source_path,
            subtitle_segments_override,
        )
        clip_path = clip_result["clip_path"]
        
        if not os.path.exists(clip_path):
            raise Exception("Clip file not created")
        
        file_size_mb = os.path.getsize(clip_path) / (1024 * 1024)
        logger.info("Video pipeline completed in %.2fs", perf_counter() - started)
        logger.info(f"Clip generated successfully: {clip_path} ({file_size_mb:.2f} MB)")
        
        return clip_result
        
    except Exception as e:
        logger.error(f"Error generating clip: {str(e)}")
        raise


def _generate_clip_sync(
    url: str,
    clip_data: Dict,
    subtitle_lang: str,
    subtitle_style: Optional[Dict],
    subtitles_enabled: bool,
    export_aspect: str,
    source_path: Optional[str],
    subtitle_segments_override: Optional[list[Dict]],
) -> Dict:
    """
    Synchronous implementation untuk clip generation
    """
    
    clip_id = str(uuid.uuid4())[:8]
    temp_dir = tempfile.gettempdir()
    stage_timings: Dict[str, float] = {}

    try:
        total_started = perf_counter()
        # Step 1: Prepare source video
        logger.info("Step 1: Preparing source video...")
        started = perf_counter()
        video_file = _prepare_source_video(url, source_path, clip_id, temp_dir)
        stage_timings["source_prepare"] = perf_counter() - started
        logger.info("Video stage source_prepare completed in %.2fs", stage_timings["source_prepare"])
        
        if not os.path.exists(video_file):
            raise Exception(f"Failed to download video: {video_file}")
        
        # Step 2: Trim video ke segment
        logger.info(f"Step 2: Trimming video {clip_data['start']}s - {clip_data['end']}s...")
        started = perf_counter()
        trimmed_file = _trim_video(video_file, clip_data['start'], clip_data['end'], clip_id, temp_dir)
        stage_timings["trim"] = perf_counter() - started
        logger.info("Video stage trim completed in %.2fs", stage_timings["trim"])
        
        # Step 3: Fit video into selected aspect ratio with black padding
        logger.info("Step 3: Formatting video to %s with scale+pad...", export_aspect)
        started = perf_counter()
        cropped_file = _format_video_canvas(trimmed_file, clip_id, temp_dir, export_aspect)
        stage_timings["format_canvas"] = perf_counter() - started
        logger.info("Video stage format_canvas completed in %.2fs", stage_timings["format_canvas"])
        
        final_clip_path = os.path.join(Config.UPLOAD_FOLDER, f"clip_{clip_id}.mp4")
        generated_subtitle_segments: list[Dict] = []
        if subtitles_enabled:
            # Step 4: Generate subtitle .ASS
            logger.info("Step 4: Generating subtitle...")
            effective_subtitle_style = _build_subtitle_style(subtitle_style, export_aspect)
            started = perf_counter()
            subtitle_content, generated_subtitle_segments = _generate_subtitle_ass(
                trimmed_file,
                clip_data,
                subtitle_lang,
                effective_subtitle_style,
                clip_id,
                temp_dir,
                subtitle_segments_override=subtitle_segments_override,
            )
            stage_timings["subtitle_generation"] = perf_counter() - started
            logger.info("Video stage subtitle_generation completed in %.2fs", stage_timings["subtitle_generation"])
            
            # Step 5: Hardcode subtitle ke video
            logger.info("Step 5: Hardcoding subtitle ke video...")
            subtitle_dest = os.path.join(Config.UPLOAD_FOLDER, f"subtitle_{clip_id}.ass")
            import shutil
            shutil.copy2(subtitle_content, subtitle_dest)
            started = perf_counter()
            _hardcode_subtitle(cropped_file, subtitle_dest, final_clip_path, clip_id, temp_dir)
            stage_timings["hardcode_subtitle"] = perf_counter() - started
            logger.info("Video stage hardcode_subtitle completed in %.2fs", stage_timings["hardcode_subtitle"])
        else:
            logger.info("Step 4: Subtitle disabled, skipping subtitle generation and hardcoding")
            import shutil
            started = perf_counter()
            shutil.copy2(cropped_file, final_clip_path)
            stage_timings["copy_final"] = perf_counter() - started
            logger.info("Video stage copy_final completed in %.2fs", stage_timings["copy_final"])

        total_elapsed = perf_counter() - total_started
        logger.info("Video sync pipeline completed in %.2fs", total_elapsed)
        _log_video_timing_summary(clip_id, stage_timings, total_elapsed)
        logger.info(f"Clip generation complete: {final_clip_path}")
        
        # Cleanup temp files
        _cleanup_temp_files([video_file, trimmed_file, cropped_file])
        
        return {
            "clip_path": final_clip_path,
            "subtitle_segments": generated_subtitle_segments,
        }
        
    except Exception as e:
        logger.error(f"Clip generation failed: {str(e)}")
        raise


def _download_video(url: str, clip_id: str, temp_dir: str) -> str:
    """
    Download video dari YouTube menggunakan yt-dlp
    
    Returns:
        Path ke video file yang didownload
    """
    
    try:
        video_file = os.path.join(temp_dir, f"video_{clip_id}.mp4")
        
        # Use yt-dlp Python API instead of subprocess
        import yt_dlp

        ydl_opts = {
            'format': 'best[ext=mp4]',
            'outtmpl': video_file,
            'quiet': True,
        }

        logger.info(f"Downloading video with yt-dlp: {url}")
        try:
            with _without_broken_proxy():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
        except Exception as e:
            logger.error(f"yt-dlp download error: {str(e)}")
            # Fallback: create mock video file jika yt-dlp tidak available
            logger.warning("yt-dlp failed, creating mock video file")
            return _create_mock_video_file(video_file)
        
        if not os.path.exists(video_file):
            raise Exception(f"Video file not created: {video_file}")
        
        logger.info(f"Video downloaded: {video_file}")
        return video_file
        
    except subprocess.TimeoutExpired:
        logger.error("Video download timeout")
        raise
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        raise


def _prepare_source_video(url: str, source_path: Optional[str], clip_id: str, temp_dir: str) -> str:
    """Use local uploaded video when available, otherwise download from YouTube."""
    if source_path:
        if not os.path.exists(source_path):
            raise Exception(f"Local source file not found: {source_path}")
        local_copy_path = os.path.join(temp_dir, f"video_{clip_id}{os.path.splitext(source_path)[1] or '.mp4'}")
        import shutil
        shutil.copy2(source_path, local_copy_path)
        logger.info("Using local uploaded source: %s", source_path)
        return local_copy_path

    if not url:
        raise Exception("No video source provided")

    return _download_video(url, clip_id, temp_dir)


def _trim_video(input_file: str, start: float, end: float, clip_id: str, temp_dir: str) -> str:
    """
    Trim video ke segment tertentu menggunakan FFmpeg
    
    Args:
        input_file: Input video file path
        start: Start time dalam seconds
        end: End time dalam seconds
        
    Returns:
        Path ke trimmed video file
    """
    
    try:
        output_file = os.path.join(temp_dir, f"trimmed_{clip_id}.mp4")
        duration = max(1, int(end - start))
        
        cmd = [
            FFMPEG_CMD,
            "-i", input_file,
            "-ss", str(start),  # Start time
            "-t", str(duration),  # Duration
            "-c:v", "libx264",  # Video codec (fast encoding)
            "-preset", "ultrafast",  # Encoding speed
            "-crf", "28",  # Quality (18-28, higher = lower quality but faster)
            "-g", "24",
            "-keyint_min", "24",
            "-sc_threshold", "0",
            "-c:a", "aac",  # Audio codec
            "-movflags", "+faststart",
            "-y",  # Overwrite output
            output_file
        ]
        
        logger.info(f"Running FFmpeg trim: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg trim error: {result.stderr}")
            raise Exception(f"FFmpeg trim failed: {result.stderr}")
        
        logger.info(f"Video trimmed: {output_file}")
        return output_file
        
    except Exception as e:
        logger.error(f"Trim error: {str(e)}")
        raise


def _format_video_canvas(input_file: str, clip_id: str, temp_dir: str, export_aspect: str) -> str:
    """Fit video into the selected social-media aspect ratio with black bars."""
    
    try:
        output_file = os.path.join(temp_dir, f"cropped_{clip_id}.mp4")
        target_width, target_height = _resolve_export_canvas(export_aspect)
        vf_filter = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black"
        )
        
        cmd = [
            FFMPEG_CMD,
            "-i", input_file,
            "-vf", vf_filter,  # Video filter
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-g", "24",
            "-keyint_min", "24",
            "-sc_threshold", "0",
            "-c:a", "aac",
            "-movflags", "+faststart",
            "-y",
            output_file
        ]
        
        logger.info(f"Running FFmpeg canvas format: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg format error: {result.stderr}")
            logger.warning("Canvas formatting failed, using original video")
            return input_file
        
        logger.info(f"Video formatted to canvas: {output_file}")
        return output_file
        
    except Exception as e:
        logger.error(f"Canvas format error: {str(e)}")
        return input_file  # Fallback


def _resolve_export_canvas(export_aspect: str) -> tuple[int, int]:
    """Resolve aspect-ratio label into a 1080-based canvas size."""
    aspect_map = {
        "9:16": (1080, 1920),
        "4:5": (1080, 1350),
        "1:1": (1080, 1080),
        "3:4": (1080, 1440),
        "16:9": (1920, 1080),
    }
    return aspect_map.get((export_aspect or "").strip(), (1080, 1920))


def _build_subtitle_style(subtitle_style: Optional[Dict], export_aspect: str) -> Dict:
    """Build subtitle-safe style presets per export aspect ratio."""
    base_style = dict(subtitle_style or {})
    canvas_width, canvas_height = _resolve_export_canvas(export_aspect)

    aspect_presets = {
        "9:16": {"small": 30, "medium": 52, "large": 68, "margin_v": 220},
        "4:5": {"small": 28, "medium": 48, "large": 62, "margin_v": 170},
        "1:1": {"small": 24, "medium": 42, "large": 56, "margin_v": 140},
        "3:4": {"small": 28, "medium": 48, "large": 62, "margin_v": 165},
        "16:9": {"small": 22, "medium": 38, "large": 50, "margin_v": 90},
    }
    preset = aspect_presets.get((export_aspect or "").strip(), aspect_presets["9:16"])
    size_preset = str(base_style.get("size_preset", "medium")).strip().lower()
    top_margin_map = {
        "9:16": 220,
        "4:5": 180,
        "1:1": 150,
        "3:4": 185,
        "16:9": 120,
    }
    alignment_map = {
        "top": ("8", top_margin_map.get((export_aspect or "").strip(), 220)),
        "middle": ("5", int(max(40, canvas_height * 0.08))),
        "bottom": ("2", preset["margin_v"]),
    }
    requested_position = str(base_style.get("position", "bottom")).strip().lower()
    alignment, margin_v = alignment_map.get(requested_position, alignment_map["bottom"])

    base_style.setdefault("font", "Arial")
    base_style.setdefault("bold", True)
    base_style["size"] = base_style.get("size") or preset.get(size_preset, preset["medium"])
    base_style["margin_v"] = base_style.get("margin_v") or margin_v
    base_style["alignment"] = alignment
    base_style["play_res_x"] = canvas_width
    base_style["play_res_y"] = canvas_height
    return base_style


def _generate_subtitle_ass(
    clip_file: str,
    clip_data: Dict,
    subtitle_lang: str,
    subtitle_style: Optional[Dict],
    clip_id: str,
    temp_dir: str,
    subtitle_segments_override: Optional[list[Dict]] = None,
) -> tuple[str, list[Dict]]:
    """Generate subtitle .ASS file"""
    
    try:
        import asyncio

        subtitle_segments = _normalize_subtitle_segments(subtitle_segments_override or [])
        if not subtitle_segments:
            subtitle_segments = _transcribe_clip_subtitle_segments(clip_file, subtitle_lang)
        if subtitle_segments:
            ass_content = build_ass_from_segments(subtitle_segments, subtitle_style)
        else:
            fallback_transcript = clip_data.get("headline") or "Clip video"
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            ass_content = loop.run_until_complete(
                generate_subtitles_async(fallback_transcript, subtitle_lang, subtitle_style)
            )
        
        # Save ke file
        subtitle_file = os.path.join(temp_dir, f"subtitle_{clip_id}.ass")
        with open(subtitle_file, 'w', encoding='utf-8') as f:
            f.write(ass_content)
        
        logger.info(f"Subtitle generated: {subtitle_file}")
        return subtitle_file, subtitle_segments
        
    except Exception as e:
        logger.error(f"Subtitle generation error: {str(e)}")
        raise


def _transcribe_clip_subtitle_segments(clip_file: str, subtitle_lang: str = "id") -> list[Dict]:
    """Transcribe trimmed clip and return short timing-based subtitle chunks."""
    if WhisperModel is None:
        logger.warning("faster-whisper unavailable, cannot create timing-based subtitles")
        return []

    try:
        normalized_lang = (subtitle_lang or "id").strip().lower()
        task = "translate" if normalized_lang.startswith("en") else "transcribe"
        language_hint = None if task == "translate" else (normalized_lang or None)
        model = WhisperModel(
            Config.WHISPER_MODEL,
            device=Config.WHISPER_DEVICE,
            compute_type=Config.WHISPER_COMPUTE_TYPE,
        )
        segments, _ = model.transcribe(
            clip_file,
            beam_size=5,
            best_of=5,
            vad_filter=False,
            condition_on_previous_text=True,
            word_timestamps=True,
            language=language_hint,
            task=task,
        )
    except Exception as exc:
        logger.warning("Whisper subtitle transcription failed: %s", exc)
        return []

    subtitle_segments = []
    for segment in segments:
        words = list(getattr(segment, "words", None) or [])
        if words:
            subtitle_segments.extend(_group_words_into_subtitles(words))
            continue

        text = (getattr(segment, "text", "") or "").strip()
        if text:
            subtitle_segments.append(
                {
                    "start": max(0.0, float(segment.start)),
                    "end": max(float(segment.end), float(segment.start) + 0.4),
                    "text": text.upper(),
                }
            )

    deduped = []
    for item in subtitle_segments:
        if item["text"] and (not deduped or deduped[-1]["text"] != item["text"] or abs(deduped[-1]["start"] - item["start"]) > 0.05):
            deduped.append(item)
    return deduped


def _group_words_into_subtitles(words: list) -> list[Dict]:
    """Turn Whisper words into short TikTok-like subtitle phrases."""
    grouped_segments = []
    buffer = []

    for word in words:
        raw_word = (getattr(word, "word", "") or "").strip()
        start = getattr(word, "start", None)
        end = getattr(word, "end", None)
        if not raw_word or start is None or end is None:
            continue

        clean_word = re.sub(r"\s+", " ", raw_word).strip()
        if not clean_word:
            continue

        buffer.append(
            {
                "text": clean_word,
                "start": float(start),
                "end": float(end),
            }
        )

        should_flush = (
            len(buffer) >= 2
            or clean_word.endswith((".", "!", "?", ","))
            or (buffer and (buffer[-1]["end"] - buffer[0]["start"]) >= 0.8)
        )

        if should_flush:
            grouped_segments.append(_flush_word_buffer(buffer))
            buffer = []

    if buffer:
        grouped_segments.append(_flush_word_buffer(buffer))

    return [segment for segment in grouped_segments if segment]


def _flush_word_buffer(buffer: list[Dict]) -> Dict:
    if not buffer:
        return {}

    text = " ".join(item["text"] for item in buffer).strip().upper()
    return {
        "start": buffer[0]["start"],
        "end": max(buffer[-1]["end"], buffer[0]["start"] + 0.35),
        "text": text,
    }


def _normalize_subtitle_segments(segments: list[Dict]) -> list[Dict]:
    normalized_segments = []
    for segment in segments or []:
        text = str(segment.get("text", "")).strip()
        start = max(0.0, float(segment.get("start", 0) or 0))
        end = max(start + 0.1, float(segment.get("end", start + 0.4) or (start + 0.4)))
        if not text:
            continue
        normalized_segments.append(
            {
                "start": start,
                "end": end,
                "text": text.upper(),
            }
        )
    return normalized_segments


def _hardcode_subtitle(input_file: str, subtitle_file: str, output_file: str, clip_id: str, temp_dir: str):
    """
    Hardcode subtitle ke video menggunakan FFmpeg
    Format: vf "subtitles=file.ass"
    """

    try:
        # Copy input file to temp dir to avoid path issues
        temp_input = os.path.join(temp_dir, f"input_{clip_id}.mp4")
        import shutil
        shutil.copy2(input_file, temp_input)

        # Copy subtitle file to temp dir
        temp_subtitle = os.path.join(temp_dir, f"subtitle_{clip_id}.ass")
        shutil.copy2(subtitle_file, temp_subtitle)

        # Create temp output in same directory
        temp_output = os.path.join(temp_dir, f"output_{clip_id}.mp4")

        if not os.path.exists(temp_input) or os.path.getsize(temp_input) == 0:
            raise Exception(f"Hardcode input file is missing or empty: {temp_input}")

        if not os.path.exists(temp_subtitle) or os.path.getsize(temp_subtitle) == 0:
            raise Exception(f"Hardcode subtitle file is missing or empty: {temp_subtitle}")

        # Use normalized absolute subtitle path so libass resolves it consistently on Windows.
        subtitle_filter_path = temp_subtitle.replace("\\", "/").replace(":", "\\:")
        vf_filter = f"subtitles='{subtitle_filter_path}'"

        cmd = [
            FFMPEG_CMD,
            "-i", temp_input,
            "-vf", vf_filter,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-g", "24",
            "-keyint_min", "24",
            "-sc_threshold", "0",
            "-c:a", "aac",
            "-movflags", "+faststart",
            "-y",
            temp_output
        ]

        logger.info(f"Running FFmpeg hardcode: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            logger.error(f"FFmpeg hardcode error: {result.stderr}")
            raise Exception(f"FFmpeg hardcode failed: {result.stderr}")

        if not os.path.exists(temp_output) or os.path.getsize(temp_output) == 0:
            raise Exception("FFmpeg hardcode did not produce a valid output file")

        # Copy result to final output location
        shutil.copy2(temp_output, output_file)

        logger.info(f"Subtitle hardcoded: {output_file}")

    except Exception as e:
        logger.error(f"Hardcode subtitle error: {str(e)}")
        raise


def _log_video_timing_summary(clip_id: str, stage_timings: Dict[str, float], total_elapsed: float) -> None:
    """Emit a compact per-stage timing summary after clip generation."""
    ordered_stages = [
        "source_prepare",
        "trim",
        "format_canvas",
        "subtitle_generation",
        "hardcode_subtitle",
        "copy_final",
    ]
    summary_parts = [
        f"{stage}={stage_timings[stage]:.2f}s"
        for stage in ordered_stages
        if stage in stage_timings
    ]
    logger.info("Video timing summary [%s]: %s | total=%.2fs", clip_id, ", ".join(summary_parts), total_elapsed)


def _create_mock_video_file(output_path: str) -> str:
    """
    Create mock video file untuk testing jika download YouTube tidak tersedia.
    """

    try:
        cmd = [
            FFMPEG_CMD,
            "-f", "lavfi",
            "-i", "color=c=blue:s=1080x1920:d=30",
            "-f", "lavfi",
            "-i", "sine=f=440:d=30",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-shortest",
            "-y",
            output_path
        ]

        logger.info("Creating mock video file for testing...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            logger.error(f"Mock video creation error: {result.stderr}")
            raise Exception(f"Mock video creation failed: {result.stderr}")

        if not os.path.exists(output_path):
            raise Exception("Mock video file was not created")

        logger.info(f"Mock video created: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Mock video creation error: {str(e)}")
        raise


def _cleanup_temp_files(file_list):
    """Cleanup temporary files"""
    
    for file_path in file_list:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {file_path}: {str(e)}")


# Backward compatibility
def generate_clip(url: str, clip_data: Dict, subtitle_lang: str = "id"):
    """Synchronous wrapper untuk backward compatibility"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(
        generate_clip_async(url, clip_data, subtitle_lang)
    )
