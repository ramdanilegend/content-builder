"""
Subtitle Engine
===============
Renders subtitles as a transparent video overlay composited on top of a scene.

Modes
-----
granularity="sentence"  →  Full text visible for the entire scene (static).
granularity="word"      →  Text visible throughout; one word highlighted at a
                            time using word-boundary timestamps from edge-tts.
                            Between word timings the text is shown unhighlighted.

Highlight
---------
If highlight.enabled=true a different colour is applied to the active word.
This produces the viral "TikTok karaoke" effect.

Implementation
--------------
• PIL renders every unique frame (one per word + one neutral) to an RGBA image
  the size of the full canvas (with transparent background).
• moviepy VideoClip with a make_frame closure does a dictionary lookup per
  rendered second – fast because all unique frames are pre-computed.
• Transparency is handled by attaching a separate mask VideoClip.
"""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw
from moviepy.editor import ImageClip, VideoClip

from renderer.layer_renderer import (
    ANCHOR_MAP,
    draw_text_with_stroke,
    hex_to_rgb,
    load_font,
    measure_text,
    resolve_position,
)

logger = logging.getLogger(__name__)


class SubtitleRenderer:
    """
    Build a subtitle overlay clip for a single scene.

    Parameters
    ----------
    text              : The voice text (source of subtitle content).
    word_timings      : List of {"word", "start_ms", "end_ms"} from TTS.
    scene_duration_ms : Total scene length in ms.
    canvas_size       : (width, height) in pixels.
    subtitle_config   : scene-level subtitle overrides.
    defaults          : blueprint["defaults"] (contains subtitle defaults).
    """

    def __init__(
        self,
        text:              str,
        word_timings:      List[dict],
        scene_duration_ms: float,
        canvas_size:       Tuple[int, int],
        subtitle_config:   dict,
        defaults:          dict,
    ) -> None:
        self.text              = text.strip()
        self.word_timings      = word_timings
        self.scene_duration_ms = scene_duration_ms
        self.canvas_w, self.canvas_h = canvas_size

        # ── merge default subtitle config with scene override ────────────────
        def_sub = defaults.get("subtitle", {})

        self.enabled     = subtitle_config.get("enabled", def_sub.get("enabled", True))
        self.granularity = subtitle_config.get("granularity", def_sub.get("granularity", "sentence"))

        # highlight
        hl_cfg                = subtitle_config.get("highlight", def_sub.get("highlight", {}))
        self.highlight_on     = hl_cfg.get("enabled", False)
        self.highlight_color  = hl_cfg.get("color", "#FFD700")

        # style  (scene overrides defaults)
        style = {**def_sub.get("style", {}), **subtitle_config.get("style", {})}
        self.font_size    = int(style.get("font_size",    48))
        self.color        = style.get("color",        "#FFFFFF")
        self.stroke_color = style.get("stroke_color", "#000000")
        self.stroke_width = int(style.get("stroke_width", 3))

        # position  (scene overrides defaults)
        pos_cfg          = {**def_sub.get("position", {}), **subtitle_config.get("position", {})}
        self.pos_x       = float(pos_cfg.get("x", 50))
        self.pos_y       = float(pos_cfg.get("y", 85))
        self.pos_anchor  = pos_cfg.get("anchor", "bottom-center")

        # layout constants
        self.font        = load_font(self.font_size)
        self.line_h      = self.font_size + 10
        self.max_w_px    = int(self.canvas_w * 0.85)

        # all words in text
        self.words: List[str] = self.text.split()

        # pre-computed frame cache: word_index → RGBA numpy array (canvas-sized)
        self._frame_cache: Dict[int, np.ndarray] = {}

    # ── public ────────────────────────────────────────────────────────────────

    def build_clip(self) -> Optional[object]:
        """Return a transparent VideoClip overlay, or None if disabled."""
        if not self.enabled or not self.text:
            return None

        if self.granularity == "word" and self.word_timings:
            return self._build_word_clip()
        return self._build_sentence_clip()

    # ── sentence mode ─────────────────────────────────────────────────────────

    def _build_sentence_clip(self) -> ImageClip:
        """Single static frame for the full scene duration."""
        arr = self._get_or_render(highlight_idx=None)  # -1 key
        rgb   = arr[:, :, :3]
        alpha = arr[:, :, 3] / 255.0
        dur_s = self.scene_duration_ms / 1000.0

        clip = ImageClip(rgb, duration=dur_s)
        clip = clip.set_mask(ImageClip(alpha, ismask=True, duration=dur_s))
        return clip

    # ── word mode ─────────────────────────────────────────────────────────────

    def _build_word_clip(self) -> VideoClip:
        """
        Pre-render one frame per unique word-highlight state, then build a
        VideoClip that looks up the right frame on every rendered second.
        """
        # Pre-render neutral + one frame per word
        neutral = self._get_or_render(highlight_idx=None)
        for i in range(len(self.words)):
            self._get_or_render(highlight_idx=i)

        renderer = self  # closure capture

        def make_rgb(t: float) -> np.ndarray:
            idx = renderer._word_at(t * 1000.0)
            arr = renderer._get_or_render(highlight_idx=idx)
            return arr[:, :, :3]

        def make_mask(t: float) -> np.ndarray:
            idx = renderer._word_at(t * 1000.0)
            arr = renderer._get_or_render(highlight_idx=idx)
            return arr[:, :, 3] / 255.0

        dur_s = self.scene_duration_ms / 1000.0
        clip  = VideoClip(make_rgb,  duration=dur_s)
        clip.mask = VideoClip(make_mask, duration=dur_s, ismask=True)
        return clip

    # ── frame lookup helpers ──────────────────────────────────────────────────

    def _word_at(self, t_ms: float) -> Optional[int]:
        """Return the word index active at *t_ms*, or None if between words."""
        for i, wt in enumerate(self.word_timings):
            if wt["start_ms"] <= t_ms < wt["end_ms"]:
                return i
        return None

    def _get_or_render(self, highlight_idx: Optional[int]) -> np.ndarray:
        key = highlight_idx if highlight_idx is not None else -1
        if key not in self._frame_cache:
            self._frame_cache[key] = np.array(self._render_frame(highlight_idx))
        return self._frame_cache[key]

    # ── PIL frame renderer ────────────────────────────────────────────────────

    def _render_frame(self, highlight_idx: Optional[int]) -> Image.Image:
        """
        Render the subtitle text onto a full-canvas RGBA image.
        *highlight_idx* – word index to highlight, or None for no highlight.
        """
        words       = self.words
        font        = self.font
        sw          = self.stroke_width
        fill_rgb    = hex_to_rgb(self.color)
        stroke_rgb  = hex_to_rgb(self.stroke_color)
        hl_rgb      = hex_to_rgb(self.highlight_color)

        # ── word-wrap preserving per-word indices ─────────────────────────────
        lines, line_word_idxs = self._wrap_words_indexed(words, font, self.max_w_px)

        # measure text block
        line_widths = [
            sum(measure_text(w + " ", font) for w in ln)
            for ln in lines
        ]
        block_w = max(line_widths) if line_widths else 1
        block_h = len(lines) * self.line_h

        # text-box image (transparent)
        pad      = sw + 4
        box_w    = block_w + pad * 2
        box_h    = block_h + pad * 2
        text_img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw     = ImageDraw.Draw(text_img)

        y_cur = pad
        for ln_words, ln_idxs in zip(lines, line_word_idxs):
            # centre the line
            lw    = sum(measure_text(w + " ", font) for w in ln_words)
            x_cur = (box_w - lw) // 2

            for word, widx in zip(ln_words, ln_idxs):
                color = (
                    hl_rgb
                    if self.highlight_on and highlight_idx is not None and widx == highlight_idx
                    else fill_rgb
                )
                draw_text_with_stroke(draw, word, (x_cur, y_cur), font, color, stroke_rgb, sw)
                x_cur += measure_text(word + " ", font)

            y_cur += self.line_h

        # ── composite text box onto full canvas ───────────────────────────────
        canvas_img = Image.new("RGBA", (self.canvas_w, self.canvas_h), (0, 0, 0, 0))

        tl_x, tl_y = resolve_position(
            self.pos_x, self.pos_y, self.pos_anchor,
            box_w, box_h,
            self.canvas_w, self.canvas_h,
        )
        # clamp so text never leaves canvas
        tl_x = max(0, min(tl_x, self.canvas_w - box_w))
        tl_y = max(0, min(tl_y, self.canvas_h - box_h))

        canvas_img.paste(text_img, (tl_x, tl_y), mask=text_img)
        return canvas_img

    # ── layout helper ─────────────────────────────────────────────────────────

    def _wrap_words_indexed(
        self,
        words:     List[str],
        font,
        max_width: int,
    ) -> Tuple[List[List[str]], List[List[int]]]:
        """Wrap words into lines; also return each word's original index."""
        lines:       List[List[str]] = []
        line_idxs:   List[List[int]] = []
        cur_words:   List[str]       = []
        cur_idxs:    List[int]       = []
        cur_w        = 0

        for i, word in enumerate(words):
            ww = measure_text(word + " ", font)
            if cur_words and cur_w + ww > max_width:
                lines.append(cur_words)
                line_idxs.append(cur_idxs)
                cur_words = [word]
                cur_idxs  = [i]
                cur_w     = ww
            else:
                cur_words.append(word)
                cur_idxs.append(i)
                cur_w += ww

        if cur_words:
            lines.append(cur_words)
            line_idxs.append(cur_idxs)

        return lines, line_idxs
