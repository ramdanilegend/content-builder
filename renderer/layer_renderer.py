"""
Layer Renderer
==============
Renders individual layers onto a scene canvas:
  • image  – PIL load → resize → position → ImageClip (with alpha mask)
  • video  – VideoFileClip → loop/trim → resize → position
  • text   – PIL text with word-wrap, stroke, named-style presets → ImageClip

Position / Anchor System
-------------------------
All positions in the JSON are percentages (0-100) of canvas dimensions.

    x_px = (x / 100) * canvas_width
    y_px = (y / 100) * canvas_height

The anchor describes *which corner/edge of the object* sits at (x_px, y_px):

    anchor          x_factor   y_factor
    ─────────────────────────────────────
    center           0.5        0.5
    top-center       0.5        0.0
    bottom-center    0.5        1.0
    top-left         0.0        0.0
    top-right        1.0        0.0
    bottom-left      0.0        1.0
    bottom-right     1.0        1.0
    center-left      0.0        0.5
    center-right     1.0        0.5

    tl_x = x_px - obj_width  * x_factor
    tl_y = y_px - obj_height * y_factor
"""
import logging
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, VideoFileClip, concatenate_videoclips

logger = logging.getLogger(__name__)

# ── anchor map ────────────────────────────────────────────────────────────────

ANCHOR_MAP: dict = {
    "center":        (0.5, 0.5),
    "top-center":    (0.5, 0.0),
    "bottom-center": (0.5, 1.0),
    "top-left":      (0.0, 0.0),
    "top-right":     (1.0, 0.0),
    "bottom-left":   (0.0, 1.0),
    "bottom-right":  (1.0, 1.0),
    "center-left":   (0.0, 0.5),
    "center-right":  (1.0, 0.5),
}

# Named text-style presets
TEXT_STYLE_PRESETS: dict = {
    "title_center": {
        "font_size":    72,
        "color":        "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": 4,
        "max_width_pct": 85,
    },
    "cta_center": {
        "font_size":    64,
        "color":        "#FFD700",
        "stroke_color": "#000000",
        "stroke_width": 4,
        "max_width_pct": 80,
    },
    "subtitle": {
        "font_size":    48,
        "color":        "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": 3,
        "max_width_pct": 85,
    },
    "body": {
        "font_size":    44,
        "color":        "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": 2,
        "max_width_pct": 80,
    },
}

DEFAULT_TEXT_STYLE: dict = {
    "font_size":    52,
    "color":        "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 3,
    "max_width_pct": 80,
}

# ── public helpers ────────────────────────────────────────────────────────────

def resolve_position(
    x_pct: float,
    y_pct: float,
    anchor: str,
    obj_w: int,
    obj_h: int,
    canvas_w: int,
    canvas_h: int,
) -> Tuple[int, int]:
    """Return the top-left pixel position of an object on the canvas."""
    x_px = int(x_pct / 100.0 * canvas_w)
    y_px = int(y_pct / 100.0 * canvas_h)

    xf, yf = ANCHOR_MAP.get(anchor.lower(), (0.5, 0.5))

    tl_x = int(x_px - obj_w * xf)
    tl_y = int(y_px - obj_h * yf)
    return tl_x, tl_y


def pct_to_px(pct: float, total: int) -> int:
    return int(pct / 100.0 * total)


def get_layer_pos(layer: dict, defaults: dict) -> Tuple[float, float, str]:
    """Return (x_pct, y_pct, anchor) for a layer, falling back to defaults."""
    pos      = layer.get("position", {})
    def_pos  = defaults.get("position", {})
    x        = float(pos.get("x",      def_pos.get("x",      50)))
    y        = float(pos.get("y",      def_pos.get("y",      50)))
    anchor   = pos.get("anchor",       def_pos.get("anchor", "center"))
    return x, y, anchor


# ── image layer ───────────────────────────────────────────────────────────────

def render_image_layer(
    layer:       dict,
    canvas_size: Tuple[int, int],
    assets:      dict,
    duration_ms: float,
    defaults:    dict,
) -> Optional[ImageClip]:
    """Load an image asset, resize, position, and return as an ImageClip."""
    src = layer.get("src")
    if not src:
        logger.warning("Image layer has no 'src'.")
        return None

    img_path = assets.get("images", {}).get(src)
    if not img_path or not Path(img_path).exists():
        logger.warning(f"Image asset missing or not found: '{src}' → '{img_path}'")
        return None

    canvas_w, canvas_h = canvas_size
    duration_s = duration_ms / 1000.0

    # Load
    pil_img = Image.open(img_path).convert("RGBA")

    # Resize
    size_cfg  = layer.get("size", {})
    width_pct = float(size_cfg.get("width", 50))
    tgt_w     = pct_to_px(width_pct, canvas_w)
    tgt_h     = int(pil_img.height * tgt_w / pil_img.width)
    pil_img   = pil_img.resize((tgt_w, tgt_h), Image.LANCZOS)

    # Position
    x_pct, y_pct, anchor = get_layer_pos(layer, defaults)
    tl_x, tl_y = resolve_position(x_pct, y_pct, anchor, tgt_w, tgt_h, canvas_w, canvas_h)

    arr   = np.array(pil_img)
    rgb   = arr[:, :, :3]
    alpha = arr[:, :, 3] / 255.0

    clip = (
        ImageClip(rgb, duration=duration_s)
        .set_mask(ImageClip(alpha, ismask=True, duration=duration_s))
        .set_position((tl_x, tl_y))
    )

    logger.debug(f"  img '{src}' → ({tl_x},{tl_y}) {tgt_w}×{tgt_h}px")
    return clip


# ── video layer ───────────────────────────────────────────────────────────────

def render_video_layer(
    layer:       dict,
    canvas_size: Tuple[int, int],
    assets:      dict,
    duration_ms: float,
    defaults:    dict,
) -> Optional[VideoFileClip]:
    """Load a video asset, loop/trim, resize, position, and return as a clip."""
    src = layer.get("src")
    if not src:
        logger.warning("Video layer has no 'src'.")
        return None

    vid_path = assets.get("videos", {}).get(src)
    if not vid_path or not Path(vid_path).exists():
        logger.warning(f"Video asset missing or not found: '{src}' → '{vid_path}'")
        return None

    canvas_w, canvas_h = canvas_size
    duration_s = duration_ms / 1000.0

    clip = VideoFileClip(vid_path, audio=False)

    # Loop if requested and too short
    should_loop = layer.get("loop", False)
    if should_loop and clip.duration < duration_s:
        reps = max(2, int(duration_s / clip.duration) + 2)
        clip = concatenate_videoclips([clip] * reps)

    clip = clip.subclip(0, min(clip.duration, duration_s))

    # Resize
    size_cfg  = layer.get("size", {})
    width_pct = float(size_cfg.get("width", 50))
    tgt_w     = pct_to_px(width_pct, canvas_w)
    tgt_h     = int(clip.h * tgt_w / clip.w)
    clip      = clip.resize((tgt_w, tgt_h))

    # Position
    x_pct, y_pct, anchor = get_layer_pos(layer, defaults)
    tl_x, tl_y = resolve_position(x_pct, y_pct, anchor, tgt_w, tgt_h, canvas_w, canvas_h)
    clip = clip.set_position((tl_x, tl_y))

    logger.debug(f"  vid '{src}' → ({tl_x},{tl_y}) {tgt_w}×{tgt_h}px loop={should_loop}")
    return clip


# ── text layer ────────────────────────────────────────────────────────────────

def render_text_layer(
    layer:       dict,
    canvas_size: Tuple[int, int],
    defaults:    dict,
    duration_ms: float,
) -> Optional[ImageClip]:
    """
    Render a text layer as a PIL image converted to an ImageClip.
    Supports named style presets and inline style overrides.
    """
    content = layer.get("content", "").strip()
    if not content:
        logger.warning("Text layer has empty 'content'.")
        return None

    canvas_w, canvas_h = canvas_size
    duration_s = duration_ms / 1000.0

    # Resolve style
    style = _resolve_text_style(layer)
    font_size    = style["font_size"]
    color        = style["color"]
    stroke_color = style["stroke_color"]
    stroke_width = style["stroke_width"]
    max_w_px     = pct_to_px(style["max_width_pct"], canvas_w)

    font = load_font(font_size)

    # Word-wrap
    lines = wrap_text(content, font, max_w_px)

    # Measure block
    line_h  = font_size + 10
    block_w = max(measure_text(ln, font) for ln in lines) if lines else 1
    block_h = len(lines) * line_h

    pad = stroke_width + 4
    img = Image.new("RGBA", (block_w + pad * 2, block_h + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y_cur = pad
    for line in lines:
        # Center each line
        lw   = measure_text(line, font)
        x_cur = (img.width - lw) // 2
        draw_text_with_stroke(
            draw, line, (x_cur, y_cur), font,
            hex_to_rgb(color), hex_to_rgb(stroke_color), stroke_width,
        )
        y_cur += line_h

    # Position on canvas
    x_pct, y_pct, anchor = get_layer_pos(layer, defaults)
    tl_x, tl_y = resolve_position(
        x_pct, y_pct, anchor, img.width, img.height, canvas_w, canvas_h
    )

    arr   = np.array(img)
    rgb   = arr[:, :, :3]
    alpha = arr[:, :, 3] / 255.0

    clip = (
        ImageClip(rgb, duration=duration_s)
        .set_mask(ImageClip(alpha, ismask=True, duration=duration_s))
        .set_position((tl_x, tl_y))
    )

    logger.debug(f"  text '{content[:30]}' → ({tl_x},{tl_y})")
    return clip


# ── PIL utilities (shared with subtitle_engine) ───────────────────────────────

def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Try common system TTF paths; fall back to PIL default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    logger.warning("No TTF font found – using PIL bitmap default (low quality)")
    return ImageFont.load_default()


def measure_text(text: str, font: ImageFont.FreeTypeFont) -> int:
    """Return pixel width of *text* using *font*."""
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    except AttributeError:
        # Pillow < 9 fallback
        w, _ = font.getsize(text)
        return w


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """Hard-wrap *text* into lines that fit *max_width* pixels."""
    words   = text.split()
    lines:  List[str] = []
    current: List[str] = []
    cur_w   = 0

    for word in words:
        ww = measure_text(word + " ", font)
        if current and cur_w + ww > max_width:
            lines.append(" ".join(current))
            current = [word]
            cur_w   = ww
        else:
            current.append(word)
            cur_w += ww

    if current:
        lines.append(" ".join(current))

    return lines or [text]


def draw_text_with_stroke(
    draw:         ImageDraw.Draw,
    text:         str,
    pos:          Tuple[int, int],
    font:         ImageFont.FreeTypeFont,
    fill:         Tuple[int, int, int],
    stroke:       Tuple[int, int, int],
    stroke_width: int,
) -> None:
    """Draw *text* with a coloured stroke outline."""
    x, y = pos
    sw = stroke_width
    for dx in range(-sw, sw + 1):
        for dy in range(-sw, sw + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke)
    draw.text((x, y), text, font=font, fill=fill)


def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ── internal ──────────────────────────────────────────────────────────────────

def _resolve_text_style(layer: dict) -> dict:
    """
    Build the final style dict for a text layer by merging:
      1. DEFAULT_TEXT_STYLE (base)
      2. Named preset (if layer['style'] is a string key)
      3. Inline style dict (if layer['style'] is a dict)
    """
    style = dict(DEFAULT_TEXT_STYLE)
    raw   = layer.get("style")

    if isinstance(raw, str) and raw in TEXT_STYLE_PRESETS:
        style.update(TEXT_STYLE_PRESETS[raw])
    elif isinstance(raw, dict):
        style.update(raw)

    return style
