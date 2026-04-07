"""
Scene Builder
=============
Orchestrates per-scene rendering:
  1. Generate TTS voice (if audio.voice.text exists)
  2. Resolve scene duration via duration_engine
  3. Build base black canvas
  4. Render all layers in z_index order
  5. Render subtitles
  6. Mix voice + BGM audio
  7. Return a CompositeVideoClip ready for concatenation

Fade transitions (optional)
----------------------------
If a scene specifies effects: [{type: "fade_in", duration_ms: 500}] etc.,
simple fade-in / fade-out is applied using moviepy's built-in fx.
"""
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from moviepy.editor import (
    ColorClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
from moviepy.video.fx import fadein, fadeout

from renderer.audio_engine import (
    generate_tts,
    get_audio_duration_ms,
    mix_audio,
)
from renderer.duration_engine import resolve_duration
from renderer.layer_renderer import (
    render_image_layer,
    render_text_layer,
    render_video_layer,
)
from renderer.subtitle_engine import SubtitleRenderer

logger = logging.getLogger(__name__)


class SceneBuilder:
    """
    Build all scenes from a blueprint and concatenate into a final video.

    Parameters
    ----------
    blueprint   : Parsed blueprint dict.
    canvas_size : (width, height) in pixels.
    fps         : Output frames-per-second.
    temp_dir    : Writable temp directory for TTS cache and intermediate files.
    """

    def __init__(
        self,
        blueprint:   dict,
        canvas_size: Tuple[int, int],
        fps:         int,
        temp_dir:    Path,
    ) -> None:
        self.blueprint   = blueprint
        self.canvas_size = canvas_size
        self.fps         = fps
        self.temp_dir    = Path(temp_dir)
        self.defaults    = blueprint.get("defaults", {})
        self.assets      = self._resolve_assets()

    # ── public ────────────────────────────────────────────────────────────────

    async def build_all(self, output_path: str) -> None:
        """Render every scene and write the final concatenated video."""
        scenes = self.blueprint.get("scenes", [])
        if not scenes:
            logger.error("Blueprint has no scenes.")
            return

        clips = []
        for idx, scene in enumerate(scenes):
            sid = scene.get("id", str(idx))
            logger.info(f"▶  Scene [{idx + 1}/{len(scenes)}]: '{sid}'")
            clip = await self._build_scene(scene)
            if clip is not None:
                clips.append(clip)
            else:
                logger.warning(f"  Scene '{sid}' produced no clip – skipped.")

        if not clips:
            logger.error("No scenes rendered; aborting.")
            return

        logger.info(f"🎬  Concatenating {len(clips)} scene(s)…")
        final = concatenate_videoclips(clips, method="compose")

        logger.info(f"💾  Writing → {output_path}")
        final.write_videofile(
            output_path,
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            logger=None,          # suppress moviepy progress bar spam
        )

        # Release resources
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
        final.close()

    # ── scene ─────────────────────────────────────────────────────────────────

    async def _build_scene(self, scene: dict) -> Optional[CompositeVideoClip]:
        sid = scene.get("id", "?")

        # ── 1. TTS ────────────────────────────────────────────────────────────
        voice_path:       Optional[str]  = None
        voice_duration_ms: Optional[float] = None
        word_timings:     list           = []

        audio_cfg  = scene.get("audio", {})
        voice_cfg  = audio_cfg.get("voice", {})
        voice_text = voice_cfg.get("text", "").strip()

        if voice_text:
            def_voice   = self.defaults.get("voice", {})
            voice_name  = voice_cfg.get("voice",  def_voice.get("voice",  "en-US-GuyNeural"))
            voice_speed = float(def_voice.get("speed", 1.0))
            voice_pitch = float(def_voice.get("pitch", 1.0))

            tts_dir = self.temp_dir / "tts"
            tts_dir.mkdir(parents=True, exist_ok=True)

            try:
                voice_path, voice_duration_ms, word_timings = await generate_tts(
                    text=voice_text,
                    voice=voice_name,
                    speed=voice_speed,
                    pitch=voice_pitch,
                    output_dir=tts_dir,
                )
            except Exception as exc:
                logger.error(f"  TTS failed for scene '{sid}': {exc}")

        # ── 2. BGM path + duration (for duration engine) ──────────────────────
        bgm_cfg           = audio_cfg.get("bgm", {})
        bgm_src           = bgm_cfg.get("src", "")
        bgm_path:         Optional[str]   = None
        bgm_duration_ms:  Optional[float] = None

        if bgm_src:
            bgm_file = self.assets["audio"].get(bgm_src)
            if bgm_file and Path(bgm_file).exists():
                bgm_path = bgm_file
                # Only measure duration if not looped (looped BGM is trimmed later)
                if not bgm_cfg.get("loop", False):
                    try:
                        bgm_duration_ms = get_audio_duration_ms(bgm_path)
                    except Exception as exc:
                        logger.warning(f"  Cannot read BGM duration: {exc}")
            else:
                logger.warning(f"  BGM asset not found: '{bgm_src}' → '{bgm_file}'")

        # ── 3. Resolve scene duration ─────────────────────────────────────────
        duration_ms = resolve_duration(
            scene=scene,
            voice_duration_ms=voice_duration_ms,
            bgm_duration_ms=bgm_duration_ms,
            defaults=self.defaults,
        )

        # ── 4. Base canvas (black) ────────────────────────────────────────────
        cw, ch = self.canvas_size
        base   = ColorClip(size=(cw, ch), color=[0, 0, 0], duration=duration_ms / 1000.0)

        # ── 5. Render layers ──────────────────────────────────────────────────
        layer_clips = [base]
        layers = sorted(scene.get("layers", []), key=lambda l: l.get("z_index", 0))

        for layer in layers:
            ltype = layer.get("type", "")
            try:
                lclip = self._render_layer(layer, duration_ms)
                if lclip is not None:
                    layer_clips.append(lclip)
            except Exception as exc:
                logger.error(f"  Layer ({ltype}) render error: {exc}", exc_info=True)

        # ── 6. Subtitles ──────────────────────────────────────────────────────
        def_sub    = self.defaults.get("subtitle", {})
        scene_sub  = scene.get("subtitle", {})
        sub_on     = scene_sub.get("enabled", def_sub.get("enabled", True))

        if sub_on and voice_text:
            sub = SubtitleRenderer(
                text=voice_text,
                word_timings=word_timings,
                scene_duration_ms=duration_ms,
                canvas_size=self.canvas_size,
                subtitle_config=scene_sub,
                defaults=self.defaults,
            )
            sub_clip = sub.build_clip()
            if sub_clip is not None:
                layer_clips.append(sub_clip)
                logger.info(
                    f"  💬  Subtitles: granularity={sub.granularity} "
                    f"highlight={sub.highlight_on}"
                )

        # ── 7. Composite video ────────────────────────────────────────────────
        scene_video = CompositeVideoClip(layer_clips, size=self.canvas_size)
        scene_video = scene_video.set_duration(duration_ms / 1000.0)

        # ── 8. Mix audio ──────────────────────────────────────────────────────
        audio = mix_audio(
            voice_path=voice_path,
            bgm_path=bgm_path,
            bgm_volume=float(bgm_cfg.get("volume", 0.5)),
            bgm_loop=bool(bgm_cfg.get("loop", False)),
            scene_duration_ms=duration_ms,
        )
        if audio is not None:
            scene_video = scene_video.set_audio(audio)

        # ── 9. Optional effects ───────────────────────────────────────────────
        scene_video = self._apply_effects(scene_video, scene.get("effects", []), duration_ms)

        logger.info(f"  ✅  Scene '{sid}' ready ({duration_ms / 1000:.2f}s)")
        return scene_video

    # ── layer dispatch ────────────────────────────────────────────────────────

    def _render_layer(self, layer: dict, duration_ms: float):
        ltype = layer.get("type", "")

        if ltype == "image":
            return render_image_layer(
                layer, self.canvas_size, self.assets, duration_ms, self.defaults
            )
        elif ltype == "video":
            return render_video_layer(
                layer, self.canvas_size, self.assets, duration_ms, self.defaults
            )
        elif ltype == "text":
            return render_text_layer(
                layer, self.canvas_size, self.defaults, duration_ms
            )
        else:
            logger.warning(f"  Unknown layer type: '{ltype}'")
            return None

    # ── effects ───────────────────────────────────────────────────────────────

    def _apply_effects(self, clip, effects: list, duration_ms: float):
        """Apply simple fade-in / fade-out effects from the effects array."""
        for fx in effects:
            fx_type = fx.get("type", "")
            fx_ms   = float(fx.get("duration_ms", 500))
            fx_s    = min(fx_ms / 1000.0, duration_ms / 1000.0 / 2)  # cap at half-duration

            if fx_type == "fade_in":
                clip = clip.fx(fadein.fadein, fx_s)
                logger.debug(f"  Effect: fade_in {fx_s:.2f}s")
            elif fx_type == "fade_out":
                clip = clip.fx(fadeout.fadeout, fx_s)
                logger.debug(f"  Effect: fade_out {fx_s:.2f}s")
            elif fx_type == "fade":
                clip = clip.fx(fadein.fadein,   fx_s)
                clip = clip.fx(fadeout.fadeout, fx_s)
                logger.debug(f"  Effect: fade in+out {fx_s:.2f}s")
            else:
                logger.debug(f"  Effect '{fx_type}' not supported – skipped.")

        return clip

    # ── asset resolution ──────────────────────────────────────────────────────

    def _resolve_assets(self) -> dict:
        """Return the assets section verbatim (paths come from JSON)."""
        raw = self.blueprint.get("assets", {})
        return {
            "images": raw.get("images", {}),
            "videos": raw.get("videos", {}),
            "audio":  raw.get("audio",  {}),
        }
