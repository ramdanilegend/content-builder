"""
Duration Engine
===============
Resolves the final duration (ms) for a scene using this priority:

    1. mode == "fixed"           → use duration.ms
    2. voice audio exists        → use TTS duration
    3. mode == "audio" + bgm     → use BGM duration
    4. fallback                  → defaults.duration.fallback_ms

After resolution, end_delay_ms is added on top.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_duration(
    scene: dict,
    voice_duration_ms: Optional[float],
    bgm_duration_ms: Optional[float],
    defaults: dict,
) -> float:
    """
    Return the final scene duration in milliseconds.

    Parameters
    ----------
    scene            : scene dict from blueprint
    voice_duration_ms: TTS audio duration in ms, or None if no voice
    bgm_duration_ms  : BGM audio duration in ms, or None if no/looped BGM
    defaults         : blueprint["defaults"]
    """
    dur_cfg = scene.get("duration", {})
    default_dur = defaults.get("duration", {})

    mode: str = dur_cfg.get("mode", default_dur.get("mode", "auto"))
    fallback_ms: float = float(default_dur.get("fallback_ms", 3000))
    end_delay_ms: float = float(default_dur.get("end_delay_ms", 300))

    base_ms: float

    # ── Priority 1: fixed ────────────────────────────────────────────────────
    if mode == "fixed":
        base_ms = float(dur_cfg.get("ms", fallback_ms))
        logger.debug(f"  duration mode=fixed → {base_ms:.0f} ms")

    # ── Priority 2: voice audio exists ──────────────────────────────────────
    elif voice_duration_ms is not None:
        base_ms = voice_duration_ms
        logger.debug(f"  duration from voice → {base_ms:.0f} ms")

    # ── Priority 3: audio mode + BGM ────────────────────────────────────────
    elif mode == "audio" and bgm_duration_ms is not None:
        base_ms = bgm_duration_ms
        logger.debug(f"  duration from bgm → {base_ms:.0f} ms")

    # ── Priority 4: fallback ─────────────────────────────────────────────────
    else:
        base_ms = fallback_ms
        logger.debug(f"  duration fallback → {base_ms:.0f} ms")

    total_ms = base_ms + end_delay_ms
    logger.info(
        f"  ⏱  Scene duration: {total_ms:.0f} ms "
        f"(base={base_ms:.0f} + end_delay={end_delay_ms:.0f})"
    )
    return total_ms
