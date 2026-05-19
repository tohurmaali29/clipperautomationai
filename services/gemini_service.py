"""
Gemini Service - AI Analysis menggunakan Gemini API biasa.
Menganalisis transcript dan mengidentifikasi segment yang viral/menarik.
"""

import json
import logging
import asyncio
import os
import re
from contextlib import contextmanager
from time import perf_counter
from typing import List, Dict, Iterable

from config import Config

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover - environment dependent
    genai = None

logger = logging.getLogger(__name__)

DEFAULT_MODEL_CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

INDONESIAN_STOPWORDS = {
    "yang", "dan", "atau", "dari", "untuk", "dengan", "karena", "juga", "dalam", "pada",
    "itu", "ini", "jadi", "ada", "aja", "saja", "banget", "bikin", "buat", "kalau", "kalo",
    "udah", "sudah", "biar", "lagi", "pas", "saat", "agar", "supaya", "mereka", "kami",
    "kita", "gue", "gua", "aku", "kamu", "dia", "nih", "nya", "kan", "si", "ke", "di",
    "nggak", "ga", "gak", "enggak", "bahwa", "seperti", "lebih", "paling", "sangat",
    "tentang", "sama", "bisa", "mau", "lah", "pun", "kok", "loh", "dong", "jadi", "terus",
}

GENERIC_HEADLINE_PATTERNS = (
    "momen viral",
    "plot twist",
    "bagian paling",
    "kisah mengejutkan",
    "momen paling",
    "opening hook",
    "main key point",
    "strong conclusion",
    "insight penting",
)


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

async def analyze_transcript_result_async(
    transcript: str,
    mode: str = "viral",
    duration: int = 30,
    transcript_segments: List[Dict] | None = None,
    candidate_moments: List[Dict] | None = None,
    source_duration: float | None = None,
) -> Dict:
    """
    Async function untuk menganalisis transcript dengan Gemini API.
    
    Args:
        transcript: Text transcript dari video YouTube
        mode: Mode analisis ('viral', 'tutorial', 'entertainment', dll)
        duration: Durasi target per clip dalam detik
    
    Returns:
        List of clips dengan format:
        [
            {
                "start": float (in seconds),
                "end": float (in seconds),
                "headline": str (judul/deskripsi segment),
                "viral_score": int (0-100)
            },
            ...
        ]
    """
    try:
        logger.info(f"Analyzing transcript with mode: {mode}, duration: {duration}s")
        started = perf_counter()
        
        result = await asyncio.to_thread(
            _analyze_transcript_sync,
            transcript,
            mode,
            duration,
            transcript_segments or [],
            candidate_moments or [],
            float(source_duration or 0),
        )
        
        logger.info("Gemini pipeline completed in %.2fs", perf_counter() - started)
        logger.info(f"Analysis complete, found {len(result['clips'])} potential clips")
        return result
        
    except Exception as e:
        logger.error(f"Error during transcript analysis: {str(e)}")
        logger.info("Using fallback mock analysis")
        return {
            "clips": _generate_mock_analysis(duration),
            "source": "mock",
            "used_fallback": True,
        }


async def analyze_transcript_async(
    transcript: str,
    mode: str = "viral",
    duration: int = 30
) -> List[Dict]:
    """Backward-compatible helper returning clips only."""
    result = await analyze_transcript_result_async(transcript, mode, duration)
    return result["clips"]

def _analyze_transcript_sync(
    transcript: str,
    mode: str,
    duration: int,
    transcript_segments: List[Dict],
    candidate_moments: List[Dict],
    source_duration: float,
) -> Dict:
    """
    Synchronous helper function untuk AI analysis
    Dijalankan dari thread pool
    """
    try:
        total_started = perf_counter()
        started = perf_counter()
        prompt = _build_analysis_prompt(
            transcript,
            mode,
            duration,
            transcript_segments=transcript_segments,
            candidate_moments=candidate_moments,
            source_duration=source_duration,
        )
        logger.info("Gemini stage build_prompt completed in %.2fs", perf_counter() - started)
        started = perf_counter()
        response_text, source = _try_generate_from_available_providers(prompt)
        logger.info("Gemini stage model_generation completed in %.2fs", perf_counter() - started)
        if not response_text:
            return {
                "clips": _generate_mock_analysis(duration),
                "source": "mock",
                "used_fallback": True,
            }

        logger.info(f"Gemini response received")
        logger.debug(f"Raw response: {response_text[:200]}...")
        
        # Extract JSON dari response
        started = perf_counter()
        clips = _parse_gemini_response(response_text)
        clips = _filter_clips_by_candidates(clips, candidate_moments, duration)
        clips = _rebalance_clips_across_timeline(
            clips,
            transcript_segments,
            duration,
            source_duration=source_duration,
            force_distribution=not bool(candidate_moments),
        )
        clips = _refine_clip_headlines(clips, transcript, source_duration=source_duration)
        logger.info("Gemini stage parse_and_refine completed in %.2fs", perf_counter() - started)
        
        if not clips:
            logger.warning("No valid clips extracted from Gemini response")
            return {
                "clips": _generate_mock_analysis(duration),
                "source": "mock",
                "used_fallback": True,
            }
        
        logger.info("Gemini sync pipeline completed in %.2fs", perf_counter() - total_started)
        return {
            "clips": clips,
            "source": source,
            "used_fallback": False,
        }
        
    except Exception as e:
        logger.error(f"Gemini analysis error: {str(e)}")
        return {
            "clips": _generate_mock_analysis(duration),
            "source": "mock",
            "used_fallback": True,
        }


def _try_generate_from_available_providers(prompt: str) -> tuple[str, str]:
    """Try Gemini API before falling back to mock output."""
    providers = [
        ("google_genai", _generate_with_google_genai),
    ]
    errors = []

    for source, fn in providers:
        try:
            response_text = fn(prompt)
            if response_text:
                return response_text, source
        except Exception as exc:
            logger.warning("%s generation failed: %s", source, exc)
            errors.append(f"{source}: {exc}")

    if errors:
        logger.warning("All AI providers failed: %s", " | ".join(errors))
    return "", "mock"


def _generate_with_google_genai(prompt: str) -> str:
    """Use Google Generative AI SDK with API key."""
    if genai is None:
        logger.info("google-generativeai SDK is unavailable")
        return ""

    if not Config.GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY not configured")
        return ""

    logger.info("Sending prompt to google-generativeai fallback...")
    with _without_broken_proxy():
        genai.configure(api_key=Config.GEMINI_API_KEY)
        last_error = None

        for model_name in _iter_model_candidates():
            try:
                logger.info("Trying Gemini model: %s", model_name)
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                response_text = getattr(response, "text", "") or ""
                if response_text:
                    logger.info("Gemini generation succeeded with model: %s", model_name)
                    return response_text
            except Exception as exc:
                last_error = exc
                logger.warning("Gemini model %s failed: %s", model_name, exc)

        if last_error is not None:
            raise last_error
    return ""


def _iter_model_candidates() -> Iterable[str]:
    """Yield likely-working model names, then discovered generateContent models."""
    yielded = set()

    for model_name in DEFAULT_MODEL_CANDIDATES:
        if model_name not in yielded:
            yielded.add(model_name)
            yield model_name

    discovered_models = _discover_generate_content_models()
    for model_name in discovered_models:
        if model_name not in yielded:
            yielded.add(model_name)
            yield model_name


def _discover_generate_content_models() -> List[str]:
    """Discover available model names from the SDK when possible."""
    if genai is None or not hasattr(genai, "list_models"):
        return []

    discovered = []
    try:
        for model in genai.list_models():
            supported_methods = getattr(model, "supported_generation_methods", []) or []
            if "generateContent" not in supported_methods:
                continue

            model_name = getattr(model, "name", "")
            if not model_name:
                continue

            if model_name.startswith("models/"):
                model_name = model_name.split("/", 1)[1]

            discovered.append(model_name)
    except Exception as exc:
        logger.warning("Failed to list Gemini models: %s", exc)
        return []

    preferred_order = []
    for candidate in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if candidate in discovered:
            preferred_order.append(candidate)

    for model_name in discovered:
        if model_name not in preferred_order and "gemini" in model_name.lower():
            preferred_order.append(model_name)

    return preferred_order

def _build_analysis_prompt(
    transcript: str,
    mode: str,
    duration: int,
    transcript_segments: List[Dict] | None = None,
    candidate_moments: List[Dict] | None = None,
    source_duration: float | None = None,
) -> str:
    """
    Build prompt untuk Gemini yang menghasilkan JSON output terstruktur
    
    Args:
        transcript: Video transcript
        mode: Analisis mode (viral, tutorial, dll)
        duration: Target duration per clip
    
    Returns:
        Prompt string yang siap dikirim ke Gemini
    """
    
    candidate_context = _build_candidate_context(
        transcript,
        transcript_segments or [],
        candidate_moments or [],
        duration,
        float(source_duration or 0),
    )
    analysis_target = candidate_context["target_label"]
    transcript_payload = candidate_context["payload"]
    has_heatmap = bool(candidate_moments)
    timeline_distribution_rule = ""
    if not has_heatmap and float(source_duration or 0) > 0:
        timeline_distribution_rule = f"""
Aturan distribusi waktu:
- Video berdurasi sekitar {float(source_duration):.0f} detik
- Jangan menumpuk semua clip di awal video
- Sebarkan pilihan ke beberapa zona waktu berbeda (awal, tengah awal, tengah, tengah akhir, atau akhir) jika memang ada momen menarik di sana
- Maksimal 2 clip dari 25% awal video kecuali seluruh momen terbaik benar-benar hanya ada di sana
"""

    prompt = f"""Anda adalah AI content analyst expert yang spesialisasi dalam mengidentifikasi momen paling menarik dari video untuk dijadikan short clip.

Tugas:
Analisis {analysis_target} di bawah ini dan pilih 5-7 segmen yang paling {mode} dan layak dijadikan short clip berdurasi sekitar {duration} detik.

Kriteria utama:
- pilih bagian yang paling engaging, lucu, mengejutkan, emosional, atau punya punchline kuat
- prioritaskan bagian yang isi pembahasannya jelas dan spesifik
- jangan pilih segmen yang membingungkan atau terlalu umum

Aturan headline:
1. Headline HARUS sesuai konteks isi segmen, bukan judul clickbait generik
2. Gunakan topik nyata yang benar-benar dibahas di segmen
3. Jika segmen membahas Ramadan, parfum, ngaji, podcast, keluarga, debat, atau topik lain, headline harus menyebut konteks itu
4. Jangan pakai judul generik seperti:
   - "Momen Viral..."
   - "Plot Twist..."
   - "Bagian Paling..."
   - "Kisah Mengejutkan..."
   kecuali transcript memang benar-benar mendukung
5. Headline maksimal 10 kata
6. Headline harus terasa seperti judul clip yang natural, singkat, dan relevan dengan isi ucapan di segmen
{timeline_distribution_rule}

Aturan output:
1. Return ONLY valid JSON array
2. Tidak boleh ada markdown, code block, atau penjelasan tambahan
3. Setiap item wajib punya field:
   - start
   - end
   - headline
   - viral_score
4. Estimasikan start dan end berdasarkan urutan transcript
5. Viral score dari 0 sampai 100

Contoh format:
[
  {{
    "start": 12.0,
    "end": 42.0,
    "headline": "Bahas parfum mahal buat hadiah Ramadan",
    "viral_score": 86
  }}
]

Konteks analisis:
- Jika bagian di bawah berupa kandidat heatmap, prioritaskan segmen yang memang paling kuat di antara kandidat tersebut
- Jangan memilih area di luar waktu yang tersedia pada kandidat

DATA ANALISIS:
{transcript_payload}
"""
    
    return prompt


def _build_candidate_context(
    transcript: str,
    transcript_segments: List[Dict],
    candidate_moments: List[Dict],
    duration: int,
    source_duration: float,
) -> Dict[str, str]:
    """Prefer heatmap-centered transcript slices when available."""
    if not transcript_segments or not candidate_moments:
        return {
            "target_label": "transcript video",
            "payload": _build_transcript_sample_payload(transcript, transcript_segments, source_duration),
        }

    windows = []
    for index, moment in enumerate(candidate_moments[:5], start=1):
        peak_time = float(moment.get("peak_time", 0) or 0)
        window_start = max(0.0, peak_time - max(12.0, duration * 0.6))
        window_end = peak_time + max(12.0, duration * 0.6)
        segment_text = _extract_segment_window_text(transcript_segments, window_start, window_end)
        if not segment_text:
            continue
        windows.append(
            f"[Candidate {index}] start={window_start:.1f}s end={window_end:.1f}s "
            f"peak={peak_time:.1f}s heat={float(moment.get('score', 0) or 0):.3f}\n"
            f"{segment_text}"
        )

    if not windows:
        return {
            "target_label": "transcript video",
            "payload": _build_transcript_sample_payload(transcript, transcript_segments, source_duration),
        }

    payload = "\n\n".join(windows)
    if len(payload) > 5000:
        payload = payload[:5000] + "..."

    return {
        "target_label": "kandidat momen heatmap dari video",
        "payload": payload,
    }


def _build_transcript_sample_payload(
    transcript: str,
    transcript_segments: List[Dict],
    source_duration: float,
    max_chars: int = 5000,
) -> str:
    """
    Build a transcript payload that represents the whole video instead of only
    the first characters. This avoids biasing Gemini toward opening segments.
    """
    if transcript_segments and source_duration > 0:
        windows = []
        normalized_points = [0.08, 0.28, 0.5, 0.72, 0.92]
        window_span = max(35.0, min(90.0, source_duration * 0.12))

        for index, ratio in enumerate(normalized_points, start=1):
            center = min(source_duration, max(0.0, source_duration * ratio))
            window_start = max(0.0, center - window_span / 2.0)
            window_end = min(source_duration, center + window_span / 2.0)
            segment_text = _extract_segment_window_text(transcript_segments, window_start, window_end)
            if not segment_text:
                continue
            windows.append(
                f"[Window {index}] start={window_start:.1f}s end={window_end:.1f}s\n{segment_text}"
            )

        if windows:
            payload = "\n\n".join(windows)
            if len(payload) > max_chars:
                payload = payload[:max_chars] + "..."
            return payload

    if len(transcript) <= max_chars:
        return transcript

    window_count = 5
    chunk_size = max(350, min(900, max_chars // window_count))
    total_length = len(transcript)
    sampled_chunks = []

    for ratio in [0.0, 0.22, 0.45, 0.68, 0.9]:
        start = int(max(0, min(total_length - chunk_size, ratio * total_length)))
        end = min(total_length, start + chunk_size)
        chunk = transcript[start:end].strip()
        if chunk:
            sampled_chunks.append(chunk)

    payload = "\n\n...\n\n".join(sampled_chunks)
    if len(payload) > max_chars:
        payload = payload[:max_chars] + "..."
    return payload


def _extract_segment_window_text(transcript_segments: List[Dict], start: float, end: float) -> str:
    parts = []
    for segment in transcript_segments:
        seg_start = float(segment.get("start", 0) or 0)
        seg_duration = float(segment.get("duration", 0) or 0)
        seg_end = seg_start + max(seg_duration, 0.0)
        if seg_end < start or seg_start > end:
            continue
        text = str(segment.get("text", "")).strip()
        if text:
            parts.append(f"[{seg_start:.1f}s] {text}")
    return " ".join(parts).strip()

def _parse_gemini_response(response_text: str) -> List[Dict]:
    """
    Parse JSON response dari Gemini
    
    Args:
        response_text: Raw response text dari Gemini
    
    Returns:
        List of clip dictionaries dengan struktur yang benar
    """
    try:
        # Try to extract JSON dari response
        # Gemini might wrap JSON dalam markdown code blocks
        
        # Remove markdown code blocks jika ada
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        # Parse JSON
        clips = json.loads(response_text.strip())
        
        # Validate structure
        if not isinstance(clips, list):
            logger.warning("Response is not a JSON array")
            return []
        
        # Validate each clip
        validated_clips = []
        for clip in clips:
            if isinstance(clip, dict) and all(k in clip for k in ["start", "end", "headline", "viral_score"]):
                # Ensure types
                clip_data = {
                    "start": float(clip["start"]),
                    "end": float(clip["end"]),
                    "headline": str(clip["headline"]),
                    "viral_score": int(clip["viral_score"])
                }
                validated_clips.append(clip_data)
        
        logger.info(f"Validated {len(validated_clips)} clips from Gemini response")
        return validated_clips
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {str(e)}")
        logger.debug(f"Failed to parse: {response_text[:200]}")
        return []
    except Exception as e:
        logger.error(f"Response parsing error: {str(e)}")
        return []


def _refine_clip_headlines(clips: List[Dict], transcript: str, source_duration: float | None = None) -> List[Dict]:
    """Rewrite headlines that are generic or weakly tied to the segment context."""
    if not clips or not transcript.strip():
        return clips

    total_timeline = float(source_duration or 0) or max((float(clip.get("end", 0)) for clip in clips), default=0.0) or 1.0
    words = transcript.split()
    transcript_len = len(words)
    if not transcript_len:
        return clips

    refined_clips = []
    for clip in clips:
        segment_text = _estimate_segment_text(words, transcript_len, clip, total_timeline)
        suggested_headline = _build_context_headline(segment_text)
        current_headline = str(clip.get("headline", "")).strip()

        if suggested_headline and _should_replace_headline(current_headline, segment_text):
            clip["headline"] = suggested_headline

        refined_clips.append(clip)

    return refined_clips


def _filter_clips_by_candidates(clips: List[Dict], candidate_moments: List[Dict], duration: int) -> List[Dict]:
    """Keep Gemini output close to heatmap candidate peaks when heatmap exists."""
    if not clips or not candidate_moments:
        return clips

    filtered = []
    tolerance = max(18.0, duration * 0.9)
    remaining_candidates = list(candidate_moments)

    for clip in clips:
        clip_mid = (float(clip.get("start", 0)) + float(clip.get("end", 0))) / 2.0
        nearest = min(
            remaining_candidates,
            key=lambda item: abs(float(item.get("peak_time", 0)) - clip_mid),
            default=None,
        )
        if nearest is None:
            continue

        distance = abs(float(nearest.get("peak_time", 0)) - clip_mid)
        if distance <= tolerance:
            clip["heatmap_score"] = float(nearest.get("score", 0) or 0)
            filtered.append(clip)

    if filtered:
        return filtered

    rescued = []
    for candidate in candidate_moments[:4]:
        peak_time = float(candidate.get("peak_time", 0) or 0)
        rescued.append({
            "start": max(0.0, peak_time - duration / 2.0),
            "end": max(duration, peak_time + duration / 2.0),
            "headline": "Momen Puncak Heatmap",
            "viral_score": 70,
            "heatmap_score": float(candidate.get("score", 0) or 0),
        })
    return rescued


def _estimate_segment_text(words: List[str], transcript_len: int, clip: Dict, total_timeline: float) -> str:
    start_ratio = max(0.0, min(1.0, float(clip.get("start", 0)) / total_timeline))
    end_ratio = max(start_ratio, min(1.0, float(clip.get("end", 0)) / total_timeline))

    start_index = max(0, min(transcript_len - 1, int(start_ratio * transcript_len)))
    end_index = max(start_index + 1, min(transcript_len, int(end_ratio * transcript_len)))
    segment_words = words[start_index:end_index]

    # Add a small buffer around the estimated slice to preserve context.
    buffer_size = min(18, transcript_len // 20 + 6)
    buffered_start = max(0, start_index - buffer_size)
    buffered_end = min(transcript_len, end_index + buffer_size)
    return " ".join(words[buffered_start:buffered_end]).strip()


def _rebalance_clips_across_timeline(
    clips: List[Dict],
    transcript_segments: List[Dict],
    duration: int,
    source_duration: float = 0.0,
    force_distribution: bool = False,
) -> List[Dict]:
    """
    When no heatmap is available, reduce early-video bias by ensuring clips are
    spread across the source timeline when possible.
    """
    if not force_distribution or not clips or not transcript_segments:
        return clips

    total_timeline = float(source_duration or 0) or max(
        (
            float(segment.get("start", 0) or 0) + float(segment.get("duration", 0) or 0)
            for segment in transcript_segments
        ),
        default=0.0,
    )
    if total_timeline <= 0:
        return clips

    clip_count = len(clips)
    if clip_count < 4:
        return clips

    bucket_count = min(4, clip_count)
    bucket_size = total_timeline / bucket_count
    buckets: dict[int, list[Dict]] = {}
    for clip in clips:
        mid = (float(clip.get("start", 0) or 0) + float(clip.get("end", 0) or 0)) / 2.0
        bucket_index = min(bucket_count - 1, int(mid / bucket_size)) if bucket_size else 0
        buckets.setdefault(bucket_index, []).append(clip)

    # If we already cover multiple zones, don't over-correct.
    if len(buckets) >= min(3, bucket_count):
        return clips

    selected = []
    used_bucket_indexes = set()

    # Keep the strongest clip from each represented bucket first.
    for bucket_index in sorted(buckets):
        strongest = max(buckets[bucket_index], key=lambda item: int(item.get("viral_score", 0) or 0))
        selected.append(strongest)
        used_bucket_indexes.add(bucket_index)

    # Fill missing buckets with representative windows from transcript segments.
    for bucket_index in range(bucket_count):
        if bucket_index in used_bucket_indexes:
            continue
        fallback_clip = _build_bucket_fallback_clip(
            transcript_segments,
            bucket_index,
            bucket_size,
            total_timeline,
            duration,
        )
        if fallback_clip:
            selected.append(fallback_clip)

    # Fill remaining quota with strongest unused original clips.
    selected_keys = {
        (float(item.get("start", 0) or 0), float(item.get("end", 0) or 0), str(item.get("headline", "")))
        for item in selected
    }
    for clip in sorted(clips, key=lambda item: int(item.get("viral_score", 0) or 0), reverse=True):
        key = (float(clip.get("start", 0) or 0), float(clip.get("end", 0) or 0), str(clip.get("headline", "")))
        if key in selected_keys:
            continue
        selected.append(clip)
        selected_keys.add(key)
        if len(selected) >= clip_count:
            break

    return sorted(selected[:clip_count], key=lambda item: float(item.get("start", 0) or 0))


def _build_bucket_fallback_clip(
    transcript_segments: List[Dict],
    bucket_index: int,
    bucket_size: float,
    total_timeline: float,
    duration: int,
) -> Dict | None:
    bucket_start = bucket_index * bucket_size
    bucket_end = min(total_timeline, bucket_start + bucket_size)
    segment_text = _extract_segment_window_text(transcript_segments, bucket_start, bucket_end)
    if not segment_text:
        return None

    peak_time = min(total_timeline, max(bucket_start, bucket_start + bucket_size / 2.0))
    clip_start = max(0.0, peak_time - duration / 2.0)
    clip_end = min(total_timeline, clip_start + duration)
    clip_start = max(0.0, clip_end - duration)

    return {
        "start": round(clip_start, 1),
        "end": round(clip_end, 1),
        "headline": _build_context_headline(segment_text) or f"Momen Zona {bucket_index + 1}",
        "viral_score": 72,
    }


def _build_context_headline(segment_text: str) -> str:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", segment_text)
    ordered_keywords = []

    for token in tokens:
        lowered = token.lower()
        if len(lowered) < 4 or lowered in INDONESIAN_STOPWORDS:
            continue
        if lowered not in ordered_keywords:
            ordered_keywords.append(lowered)

    if not ordered_keywords:
        return ""

    picked = ordered_keywords[:6]
    lead = picked[:4]
    if len(lead) >= 4:
        headline = f"Bahas {' '.join(lead[:2])} dan {' '.join(lead[2:4])}"
    elif len(lead) == 3:
        headline = f"Bahas {lead[0]} {lead[1]} {lead[2]}"
    elif len(lead) == 2:
        headline = f"Bahas {lead[0]} dan {lead[1]}"
    else:
        headline = f"Bahas {lead[0]}"

    headline = headline.replace("  ", " ").strip()
    words = headline.split()
    if len(words) > 10:
        headline = " ".join(words[:10])
    return headline.title()


def _should_replace_headline(headline: str, segment_text: str) -> bool:
    lowered_headline = headline.lower().strip()
    if not lowered_headline:
        return True

    if any(pattern in lowered_headline for pattern in GENERIC_HEADLINE_PATTERNS):
        return True

    headline_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", headline)
        if len(token) >= 4 and token.lower() not in INDONESIAN_STOPWORDS
    }
    if not headline_tokens:
        return True

    context_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9'-]+", segment_text)
        if len(token) >= 4 and token.lower() not in INDONESIAN_STOPWORDS
    }
    if not context_tokens:
        return False

    overlap = len(headline_tokens & context_tokens)
    return overlap == 0

def _generate_mock_analysis(duration: int) -> List[Dict]:
    """
    Generate mock analysis hasil untuk demo/fallback
    Ketika Gemini tidak available atau error
    """
    return [
        {
            "start": 10.0,
            "end": 10.0 + duration,
            "headline": "Opening Hook - Intro Menarik",
            "viral_score": 82
        },
        {
            "start": 45.0,
            "end": 45.0 + duration,
            "headline": "Main Key Point - Insight Penting",
            "viral_score": 88
        },
        {
            "start": 90.0,
            "end": 90.0 + duration,
            "headline": "Plot Twist - Unexpected Moment",
            "viral_score": 92
        },
        {
            "start": 150.0,
            "end": 150.0 + duration,
            "headline": "Strong Conclusion - Call to Action",
            "viral_score": 78
        },
        {
            "start": 210.0,
            "end": 210.0 + duration,
            "headline": "Momen Paling Ramai di Tengah Bahasan",
            "viral_score": 84
        },
        {
            "start": 280.0,
            "end": 280.0 + duration,
            "headline": "Obrolan yang Mulai Memanas",
            "viral_score": 86
        },
    ]

# Backward compatibility
def analyze_transcript(transcript: str, mode: str = "viral", duration: int = 30):
    """
    Synchronous wrapper untuk backward compatibility dengan Flask
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return {
        "clips": loop.run_until_complete(
            analyze_transcript_async(transcript, mode, duration)
        )
    }
