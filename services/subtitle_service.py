"""
Subtitle Service - Generate subtitle dalam format .ASS.
Support untuk customization warna, font, ukuran, dan positioning.
"""

import asyncio
import logging
from time import perf_counter
from typing import Dict, Optional

logger = logging.getLogger(__name__)


async def generate_subtitles_async(
    transcript: str,
    lang: str = "id",
    style: Optional[Dict] = None,
) -> str:
    """Generate subtitle content asynchronously."""
    try:
        logger.info("Generating subtitles in language: %s", lang)
        started = perf_counter()
        result = await asyncio.to_thread(_generate_subtitles_sync, transcript, lang, style)
        logger.info("Subtitle pipeline completed in %.2fs", perf_counter() - started)
        return result
    except Exception as exc:
        logger.error("Error generating subtitles: %s", exc)
        return _generate_mock_subtitles_ass(transcript, lang, style)


def build_ass_from_segments(segments: list, style: Optional[Dict] = None) -> str:
    """Public helper to build ASS subtitles from timestamped segments."""
    return _build_ass_file(segments, style)


def _generate_subtitles_sync(
    transcript: str,
    lang: str,
    style: Optional[Dict],
) -> str:
    """Generate subtitle content synchronously."""
    try:
        segments = _parse_transcript_into_segments(transcript, lang)
        logger.info("Created %s subtitle segments", len(segments))
        return _build_ass_file(segments, style)
    except Exception as exc:
        logger.error("Subtitle generation error: %s", exc)
        return _generate_mock_subtitles_ass(transcript, lang, style)


def _build_ass_file(segments: list, style: Optional[Dict]) -> str:
    """Build ASS file content manually."""
    font_name = "Arial"
    font_size = "36"
    primary_color = "&H00FFFFFF"
    outline_color = "&H00000000"
    back_color = "&H00000000"
    bold = "0"
    italic = "0"
    margin_v = "0"
    play_res_x = "1920"
    play_res_y = "1080"
    alignment = "2"

    if style:
        font_name = style.get("font", font_name)
        font_size = str(style.get("size", font_size))
        margin_v = str(style.get("margin_v", margin_v))
        play_res_x = str(style.get("play_res_x", play_res_x))
        play_res_y = str(style.get("play_res_y", play_res_y))
        alignment = str(style.get("alignment", alignment))

        color_hex = style.get("color")
        if color_hex:
            if color_hex.startswith("#"):
                color_hex = color_hex[1:]
            try:
                red = int(color_hex[0:2], 16)
                green = int(color_hex[2:4], 16)
                blue = int(color_hex[4:6], 16)
                primary_color = f"&H{blue:02X}{green:02X}{red:02X}"
            except ValueError:
                logger.warning("Invalid color format: %s", color_hex)

        outline_hex = style.get("outline_color")
        if outline_hex:
            if outline_hex.startswith("#"):
                outline_hex = outline_hex[1:]
            try:
                red = int(outline_hex[0:2], 16)
                green = int(outline_hex[2:4], 16)
                blue = int(outline_hex[4:6], 16)
                outline_color = f"&H{blue:02X}{green:02X}{red:02X}"
            except ValueError:
                logger.warning("Invalid outline color format: %s", outline_hex)

        if style.get("bold"):
            bold = "-1"
        if style.get("italic"):
            italic = "-1"

    ass_lines = [
        "[Script Info]",
        "Title: AI Video Clipper Subtitle",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},{back_color},{bold},{italic},0,0,100,100,0,0,1,2,0,{alignment},0,0,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for segment in segments:
        start_time = _seconds_to_ass_time(segment["start"])
        end_time = _seconds_to_ass_time(segment["end"])
        text = segment["text"].replace("\n", "\\N")
        ass_lines.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}")

    return "\n".join(ass_lines)


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds ke format waktu ASS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _parse_transcript_into_segments(transcript: str, lang: str, segment_duration: float = 5.0):
    """Split transcript into naive subtitle segments."""
    del lang
    words = transcript.split()
    if not words:
        return []

    words_per_second = 2.5
    words_per_segment = max(5, int(segment_duration * words_per_second))
    segments = []
    current_time = 0.0

    for index in range(0, len(words), words_per_segment):
        segment_words = words[index:index + words_per_segment]
        segment_text = " ".join(segment_words)
        if segment_text.strip():
            segments.append(
                {
                    "start": current_time,
                    "end": current_time + segment_duration,
                    "text": segment_text,
                }
            )
            current_time += segment_duration

    return segments


def _generate_mock_subtitles_ass(
    transcript: str,
    lang: str,
    style: Optional[Dict],
) -> str:
    """Generate fallback subtitle content."""
    try:
        segments = _parse_transcript_into_segments(transcript, lang)
        return _build_ass_file(segments, style)
    except Exception as exc:
        logger.error("Mock subtitle generation failed: %s", exc)
        return _minimal_ass_format(transcript[:200])


def _minimal_ass_format(text: str) -> str:
    """Return a minimal valid ASS file."""
    return f"""[Script Info]
Title: AI Video Clipper Subtitle
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,36,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{text}
"""


def generate_subtitles(transcript: str, lang: str = "id"):
    """Synchronous wrapper untuk backward compatibility."""
    return asyncio.run(generate_subtitles_async(transcript, lang))
