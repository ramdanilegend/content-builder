"""
Audio Engine
============
Responsibilities:
  • Generate TTS via edge-tts, capturing word-boundary timing
  • Cache TTS results to avoid regeneration on re-runs
  • Measure audio file duration
  • Mix voice + BGM into a CompositeAudioClip

Edge-TTS word boundary events carry offset/duration in 100-nanosecond units
(Windows FILETIME ticks).  Divide by 10 000 to get milliseconds.
"""
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

import edge_tts
from moviepy.audio.AudioClip import concatenate_audioclips
from moviepy.editor import AudioFileClip, CompositeAudioClip

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

def _ticks_to_ms(ticks: int) -> float:
    """Convert 100-nanosecond ticks (FILETIME) → milliseconds."""
    return ticks / 10_000


def _speed_to_rate(speed: float) -> str:
    """
    Convert a speed multiplier to an edge-tts rate string.
    edge-tts accepts values like '+10%', '-5%', '+0%'.
    """
    if speed == 1.0:
        return "+0%"
    pct = int(round((speed - 1.0) * 100))
    return f"{pct:+d}%"


def _pitch_to_str(pitch: float) -> str:
    """
    Convert a pitch multiplier to an edge-tts pitch string (Hz offset).
    Rough mapping: ±1.0 multiplier → ±50 Hz offset.
    """
    if pitch == 1.0:
        return "+0Hz"
    hz = int(round((pitch - 1.0) * 50))
    return f"{hz:+d}Hz"


def _cache_key(text: str, voice: str, speed: float, pitch: float) -> str:
    payload = f"{text}|{voice}|{speed:.4f}|{pitch:.4f}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


# ── public API ────────────────────────────────────────────────────────────────

async def generate_tts(
    text: str,
    voice: str,
    speed: float,
    pitch: float,
    output_dir: Path,
) -> Tuple[str, float, List[dict]]:
    """
    Generate TTS audio using edge-tts and return:
        (audio_path, duration_ms, word_timings)

    word_timings is a list of:
        {"word": str, "start_ms": float, "end_ms": float}

    Results are cached: same (text, voice, speed, pitch) → same files.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    key = _cache_key(text, voice, speed, pitch)
    audio_path  = output_dir / f"tts_{key}.mp3"
    timing_path = output_dir / f"tts_{key}.json"

    # ── cache hit ─────────────────────────────────────────────────────────────
    if audio_path.exists() and timing_path.exists():
        logger.info(f"  🎙  TTS cache hit [{key[:8]}…]")
        with open(timing_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        return str(audio_path), cached["duration_ms"], cached["word_timings"]

    # ── generate ──────────────────────────────────────────────────────────────
    logger.info(f"  🎙  TTS generating: '{text[:60]}…' | voice={voice}")

    rate_str  = _speed_to_rate(speed)
    pitch_str = _pitch_to_str(pitch)

    communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)

    audio_bytes   = bytearray()
    word_timings: List[dict] = []

    async for chunk in communicate.stream():
        ctype = chunk.get("type")
        if ctype == "audio":
            audio_bytes.extend(chunk["data"])
        elif ctype == "WordBoundary":
            start_ms = _ticks_to_ms(chunk["offset"])
            dur_ms   = _ticks_to_ms(chunk["duration"])
            word_timings.append(
                {
                    "word":     chunk["text"],
                    "start_ms": start_ms,
                    "end_ms":   start_ms + dur_ms,
                }
            )

    if not audio_bytes:
        raise RuntimeError(f"TTS returned no audio bytes for text: '{text[:40]}'")

    # Write audio
    with open(audio_path, "wb") as fh:
        fh.write(bytes(audio_bytes))

    # Measure actual duration from the file
    duration_ms = get_audio_duration_ms(str(audio_path))

    # Extend last word timing to actual file end (edge-tts timings can be
    # slightly shorter than the actual audio due to trailing silence)
    if word_timings and word_timings[-1]["end_ms"] < duration_ms:
        word_timings[-1]["end_ms"] = duration_ms

    # Cache timings
    with open(timing_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"duration_ms": duration_ms, "word_timings": word_timings},
            fh,
            ensure_ascii=False,
            indent=2,
        )

    logger.info(
        f"  🎙  TTS done: {duration_ms:.0f} ms, {len(word_timings)} words"
    )
    return str(audio_path), duration_ms, word_timings


def get_audio_duration_ms(path: str) -> float:
    """Return the duration of an audio file in milliseconds."""
    clip = AudioFileClip(path)
    ms   = clip.duration * 1000.0
    clip.close()
    return ms


def mix_audio(
    voice_path:       Optional[str],
    bgm_path:         Optional[str],
    bgm_volume:       float,
    bgm_loop:         bool,
    scene_duration_ms: float,
) -> Optional[object]:
    """
    Mix voice + BGM for a scene.

    Returns a CompositeAudioClip (or a single AudioFileClip) trimmed to
    scene_duration_ms.  Returns None if there is no audio at all.
    """
    scene_s = scene_duration_ms / 1000.0
    clips   = []

    # ── voice ─────────────────────────────────────────────────────────────────
    if voice_path and Path(voice_path).exists():
        voice_clip = AudioFileClip(voice_path)
        # Trim to scene duration (voice may include silence / end_delay)
        voice_clip = voice_clip.subclip(0, min(voice_clip.duration, scene_s))
        clips.append(voice_clip)
        logger.debug(f"  🔊 Voice: {voice_clip.duration:.2f}s")

    # ── BGM ───────────────────────────────────────────────────────────────────
    if bgm_path and Path(bgm_path).exists():
        bgm_clip = AudioFileClip(bgm_path)

        if bgm_loop:
            # Loop enough times to cover scene duration, then trim
            reps = max(1, int(scene_s / bgm_clip.duration) + 2)
            bgm_clip = concatenate_audioclips([bgm_clip] * reps)

        bgm_clip = bgm_clip.subclip(0, min(bgm_clip.duration, scene_s))
        bgm_clip = bgm_clip.volumex(bgm_volume)
        clips.append(bgm_clip)
        logger.debug(f"  🎵 BGM: {bgm_clip.duration:.2f}s @ vol={bgm_volume}")

    if not clips:
        return None
    if len(clips) == 1:
        return clips[0]

    return CompositeAudioClip(clips)
