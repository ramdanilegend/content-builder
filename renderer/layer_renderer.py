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
    "italic":       False,
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


# ── layer animation ───────────────────────────────────────────────────────────

SUPPORTED_ANIMATIONS = frozenset([
    "fade-in", "fade-out",
    "slide-left", "slide-right", "slide-up", "slide-down",
    "zoom-in", "zoom-out",
])


def apply_layer_animation(
    clip,
    animation: Optional[dict],
    canvas_size: Tuple[int, int],
    tl_x: int,
    tl_y: int,
    obj_w: int,
    obj_h: int,
    duration_ms: float,
):
    """
    Apply a layer-level entry animation to a positioned clip.

    Supported types: fade-in, fade-out,
                     slide-left, slide-right, slide-up, slide-down,
                     zoom-in, zoom-out

    Slide / zoom variants override the static position that was already set
    on the clip with a time-varying function. After the animation duration the
    clip snaps to its final resting position / scale.
    """
    if not animation:
        return clip

    anim_type = (animation.get("type") or "").strip()
    if not anim_type:
        return clip

    anim_s     = float(animation.get("duration", 500)) / 1000.0
    canvas_w, canvas_h = canvas_size

    # ── fade ─────────────────────────────────────────────────────────────────
    if anim_type == "fade-in":
        from moviepy.video.fx import fadein as _fi
        return clip.fx(_fi.fadein, anim_s)

    if anim_type == "fade-out":
        from moviepy.video.fx import fadeout as _fo
        return clip.fx(_fo.fadeout, anim_s)

    # ── slide ─────────────────────────────────────────────────────────────────
    if anim_type == "slide-left":
        # enters from the right edge
        def _pos(t, s=anim_s, x0=float(canvas_w), xf=float(tl_x), y=float(tl_y)):
            if t >= s:
                return (xf, y)
            p = t / s
            return (x0 + (xf - x0) * p, y)
        return clip.set_position(_pos)

    if anim_type == "slide-right":
        # enters from the left edge (off-screen)
        def _pos(t, s=anim_s, x0=float(-obj_w), xf=float(tl_x), y=float(tl_y)):
            if t >= s:
                return (xf, y)
            p = t / s
            return (x0 + (xf - x0) * p, y)
        return clip.set_position(_pos)

    if anim_type == "slide-up":
        # enters from the bottom edge
        def _pos(t, s=anim_s, x=float(tl_x), y0=float(canvas_h), yf=float(tl_y)):
            if t >= s:
                return (x, yf)
            p = t / s
            return (x, y0 + (yf - y0) * p)
        return clip.set_position(_pos)

    if anim_type == "slide-down":
        # enters from the top (off-screen above)
        def _pos(t, s=anim_s, x=float(tl_x), y0=float(-obj_h), yf=float(tl_y)):
            if t >= s:
                return (x, yf)
            p = t / s
            return (x, y0 + (yf - y0) * p)
        return clip.set_position(_pos)

    # ── zoom ──────────────────────────────────────────────────────────────────
    if anim_type in ("zoom-in", "zoom-out"):
        cx = float(tl_x + obj_w / 2)
        cy = float(tl_y + obj_h / 2)
        fw = float(obj_w)
        fh = float(obj_h)

        if anim_type == "zoom-in":
            # grows from near-zero → 1× over anim_s
            def _scale(t, s=anim_s):
                return max(0.01, t / s) if t < s else 1.0
            def _pos(t, s=anim_s, cx=cx, cy=cy, fw=fw, fh=fh):
                sc = max(0.01, t / s) if t < s else 1.0
                return (cx - fw * sc / 2, cy - fh * sc / 2)
        else:
            # zoom-out: starts at 1.5× and shrinks to 1×
            def _scale(t, s=anim_s):
                return (1.5 - 0.5 * (t / s)) if t < s else 1.0
            def _pos(t, s=anim_s, cx=cx, cy=cy, fw=fw, fh=fh):
                sc = (1.5 - 0.5 * (t / s)) if t < s else 1.0
                return (cx - fw * sc / 2, cy - fh * sc / 2)

        return clip.resize(_scale).set_position(_pos)

    logger.warning(f"Unknown layer animation type '{anim_type}' – skipped.")
    return clip


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

    animation = layer.get("animation")
    if animation:
        clip = apply_layer_animation(clip, animation, canvas_size, tl_x, tl_y, tgt_w, tgt_h, duration_ms)
        logger.debug(f"  img '{src}' anim={animation.get('type')}")

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
    clip      = clip.fl_image(lambda img: np.array(
        Image.fromarray(img).resize((tgt_w, tgt_h), Image.LANCZOS)
    ))

    # Position
    x_pct, y_pct, anchor = get_layer_pos(layer, defaults)
    tl_x, tl_y = resolve_position(x_pct, y_pct, anchor, tgt_w, tgt_h, canvas_w, canvas_h)
    clip = clip.set_position((tl_x, tl_y))

    animation = layer.get("animation")
    if animation:
        clip = apply_layer_animation(clip, animation, canvas_size, tl_x, tl_y, tgt_w, tgt_h, duration_ms)
        logger.debug(f"  vid '{src}' anim={animation.get('type')}")

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
    font_family  = style.get("font_family")
    color        = style["color"]
    stroke_color = style["stroke_color"]
    stroke_width = style["stroke_width"]
    max_w_px     = pct_to_px(style["max_width_pct"], canvas_w)
    italic       = bool(style.get("italic", False))

    font = load_font(font_size, font_family, italic=italic)

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

    animation = layer.get("animation")
    if animation:
        clip = apply_layer_animation(
            clip, animation, canvas_size,
            tl_x, tl_y, img.width, img.height, duration_ms,
        )
        logger.debug(f"  text '{content[:30]}' anim={animation.get('type')}")

    logger.debug(f"  text '{content[:30]}' → ({tl_x},{tl_y})")
    return clip


# ── PIL utilities (shared with subtitle_engine) ───────────────────────────────

import os as _os

# macOS: Homebrew cask fonts install to ~/Library/Fonts/
_MAC_USER_FONTS = _os.path.expanduser("~/Library/Fonts")
_MAC_SYS_FONTS  = "/Library/Fonts"

def _mac(*names: str) -> list:
    """Return macOS font paths (user + system Library/Fonts) for each filename."""
    paths = []
    for name in names:
        paths.append(f"{_MAC_USER_FONTS}/{name}")
        paths.append(f"{_MAC_SYS_FONTS}/{name}")
    return paths


# Maps font_family names (as sent by the FE) to ordered lists of TTF/OTF paths to try.
# Each entry lists the preferred bold variant first, then regular as fallback.
# Paths cover: Linux (Docker apt) + macOS (Homebrew cask) + common system locations.
FONT_FAMILY_PATHS: dict = {

    # ── SANS-SERIF / MODERN ──────────────────────────────────────────────────

    # Clean, geometric — extremely popular in YouTube thumbnails & lower-thirds
    "Poppins": [
        "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
        "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
        "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
        *_mac("Poppins-Bold.ttf", "Poppins-SemiBold.ttf", "Poppins-Regular.ttf"),
    ],
    # Humanist sans — used heavily in news broadcasts & documentary titles
    "Open Sans": [
        "/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf",
        "/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf",
        *_mac("OpenSans-Bold.ttf", "OpenSans-Regular.ttf",
              "Open Sans Bold.ttf", "Open Sans Regular.ttf"),
    ],
    # Google's standard UI font — very clean for subtitles & lower-thirds
    "Roboto": [
        "/usr/share/fonts/truetype/roboto/hinted/Roboto-Bold.ttf",
        "/usr/share/fonts/truetype/roboto/Roboto-Bold.ttf",
        "/usr/share/fonts/truetype/roboto/hinted/Roboto-Regular.ttf",
        *_mac("Roboto-Bold.ttf", "Roboto-Regular.ttf"),
    ],
    # Ubuntu brand font — strong and modern, great for title cards
    "Ubuntu": [
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/ubuntu/ubuntu-font-family/Ubuntu-B.ttf",
        *_mac("Ubuntu-Bold.ttf", "Ubuntu-Regular.ttf", "Ubuntu Bold.ttf"),
    ],
    # GNOME's default UI font — rounded, approachable
    "Cantarell": [
        "/usr/share/fonts/truetype/cantarell/Cantarell-Bold.otf",
        "/usr/share/fonts/truetype/cantarell/Cantarell-Regular.otf",
        "/usr/share/fonts/opentype/cantarell/Cantarell-Bold.otf",
        *_mac("Cantarell-Bold.otf", "Cantarell-Regular.otf"),
    ],
    # Google Noto — excellent international character coverage
    "Noto Sans": [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans[wdth,wght].ttf",
        *_mac("NotoSans-Bold.ttf", "NotoSans-Regular.ttf",
              "NotoSans[wdth,wght].ttf"),
    ],
    # Helvetica substitute — the industry-standard look for broadcast
    "Nimbus Sans": [
        "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
        "/System/Library/Fonts/Helvetica.ttc",   # macOS system Helvetica
    ],
    # Clean geometric — popular in motion graphics
    "DejaVu Sans": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        *_mac("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"),
    ],
    # Liberation Sans (Arial substitute) — versatile broadcast standard
    "Liberation Sans": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        *_mac("LiberationSans-Bold.ttf", "Liberation Sans Bold.ttf"),
    ],
    # Arimo — Chrome OS Arial substitute, very clean
    "Arimo": [
        "/usr/share/fonts/truetype/croscore/Arimo-Bold.ttf",
        "/usr/share/fonts/truetype/croscore/Arimo-Regular.ttf",
        *_mac("Arimo-Bold.ttf", "Arimo-Regular.ttf"),
    ],
    # Like Calibri — popular in corporate & webinar-style videos
    "Carlito": [
        "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
        "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
        *_mac("Carlito-Bold.ttf", "Carlito-Regular.ttf"),
    ],
    # Free sans — general purpose, wide character set
    "FreeSans": [
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        *_mac("FreeSansBold.ttf", "FreeSans.ttf"),
    ],

    # ── CONDENSED / NARROW ───────────────────────────────────────────────────

    # Tight condensed sans — ideal for action titles & sports graphics
    "DejaVu Sans Condensed": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        *_mac("DejaVuSansCondensed-Bold.ttf", "DejaVuSansCondensed.ttf"),
    ],
    # Narrow sans — used for information-dense lower-thirds
    # (included inside font-liberation cask on macOS)
    "Liberation Sans Narrow": [
        "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Regular.ttf",
        *_mac("LiberationSansNarrow-Bold.ttf", "LiberationSansNarrow-Regular.ttf",
              "Liberation Sans Narrow Bold.ttf"),
    ],
    # Nimbus narrow — high-impact condensed (like Impact)
    "Nimbus Sans Narrow": [
        "/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Bold.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Regular.otf",
    ],

    # ── SERIF / EDITORIAL ────────────────────────────────────────────────────

    # Variable serif — used in documentary and cinematic titles
    "Lora": [
        "/usr/share/fonts/truetype/google-fonts/Lora-Variable.ttf",
        *_mac("Lora-Bold.ttf", "Lora-SemiBold.ttf",
              "Lora[wght].ttf", "Lora-Regular.ttf"),
    ],
    # DejaVu Serif — classic readable serif for editorial content
    "DejaVu Serif": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        *_mac("DejaVuSerif-Bold.ttf", "DejaVuSerif.ttf"),
    ],
    # Liberation Serif (Times New Roman substitute) — formal, news-style
    "Liberation Serif": [
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        *_mac("LiberationSerif-Bold.ttf", "Liberation Serif Bold.ttf"),
    ],
    # Tinos — Times New Roman substitute, used in broadcast journalism
    "Tinos": [
        "/usr/share/fonts/truetype/croscore/Tinos-Bold.ttf",
        "/usr/share/fonts/truetype/croscore/Tinos-Regular.ttf",
        *_mac("Tinos-Bold.ttf", "Tinos-Regular.ttf"),
    ],
    # Like Cambria — elegant serif for titles and end cards
    "Caladea": [
        "/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf",
        "/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf",
        *_mac("Caladea-Bold.ttf", "Caladea-Regular.ttf"),
    ],
    # High-quality classical serif — used in film credits & book-style titles
    "EB Garamond": [
        "/usr/share/fonts/truetype/ebgaramond/EBGaramond-Bold.ttf",
        "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Regular.ttf",
        "/usr/share/fonts/truetype/ebgaramond/EBGaramond-Regular.ttf",
        *_mac("EBGaramond-Bold.ttf", "EBGaramond12-Regular.ttf",
              "EBGaramond08-Regular.ttf"),
    ],
    # Rich scholarly serif — used in historical/cinematic productions
    "Vollkorn": [
        "/usr/share/fonts/truetype/vollkorn/Vollkorn-Bold.ttf",
        "/usr/share/fonts/truetype/vollkorn/Vollkorn-Regular.ttf",
        *_mac("Vollkorn-Bold.ttf", "Vollkorn[wght].ttf", "Vollkorn-Regular.ttf"),
    ],
    # Elegant humanist serif — popular in art-house film titles
    "Linux Libertine": [
        "/usr/share/fonts/truetype/linux-libertine/LinLibertine_RBah.ttf",
        "/usr/share/fonts/truetype/linux-libertine/LinLibertine_RB.ttf",
        "/usr/share/fonts/truetype/linux-libertine/LinLibertine_R.ttf",
        *_mac("LinLibertine_RB.ttf", "LinLibertine_R.ttf",
              "Linux Libertine Bold.ttf"),
    ],
    # Nimbus Roman (Times-compatible) — standard serif for formal productions
    "Nimbus Roman": [
        "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Bold.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Regular.otf",
        "/System/Library/Fonts/Times New Roman.ttf",   # macOS system
        "/Library/Fonts/Times New Roman.ttf",
    ],
    # FreeSerif — versatile serif, covers many Unicode scripts
    "FreeSerif": [
        "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
        *_mac("FreeSerifBold.ttf", "FreeSerif.ttf"),
    ],
    # URW Bookman (Bookman-compatible) — warm editorial serif
    "URW Bookman": [
        "/usr/share/fonts/opentype/urw-base35/URWBookman-Demi.otf",
        "/usr/share/fonts/opentype/urw-base35/URWBookman-Light.otf",
    ],
    # URW Gothic (Avant Garde-compatible) — geometric display serif
    "URW Gothic": [
        "/usr/share/fonts/opentype/urw-base35/URWGothic-Demi.otf",
        "/usr/share/fonts/opentype/urw-base35/URWGothic-Book.otf",
    ],

    # ── MONOSPACE / TECHY ────────────────────────────────────────────────────

    # DejaVu Mono — for code-style lower-thirds and techy overlays
    # (bundled inside font-dejavu cask on macOS)
    "DejaVu Mono": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        *_mac("DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf"),
    ],
    # Liberation Mono — clean monospace for terminal-style graphics
    # (bundled inside font-liberation cask on macOS)
    "Liberation Mono": [
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        *_mac("LiberationMono-Bold.ttf", "LiberationMono-Regular.ttf",
              "Liberation Mono Bold.ttf"),
    ],
    # Inconsolata — elegant programmer's font, used in tech YouTube channels
    "Inconsolata": [
        "/usr/share/fonts/truetype/inconsolata/Inconsolata.otf",
        "/usr/share/fonts/opentype/inconsolata/Inconsolata.otf",
        "/usr/share/fonts/truetype/inconsolata/Inconsolata-Bold.ttf",
        *_mac("Inconsolata-Bold.ttf", "Inconsolata-Regular.ttf", "Inconsolata.otf"),
    ],
    # Hack — ultra-clean code font, popular for "hacker" aesthetic videos
    "Hack": [
        "/usr/share/fonts/truetype/hack/Hack-Bold.ttf",
        "/usr/share/fonts/truetype/hack/Hack-Regular.ttf",
        *_mac("Hack-Bold.ttf", "Hack-Regular.ttf"),
    ],
    # FreeMono — wide character coverage, good for international text
    # (bundled inside font-gnu-freefont cask on macOS)
    "FreeMono": [
        "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        *_mac("FreeMonoBold.ttf", "FreeMono.ttf"),
    ],

    # ── DECORATIVE / SPECIAL ─────────────────────────────────────────────────

    # Jura — futuristic, angular — popular for sci-fi & gaming content
    "Jura": [
        "/usr/share/fonts/truetype/jura/Jura-Bold.ttf",
        "/usr/share/fonts/truetype/jura/Jura-Medium.ttf",
        "/usr/share/fonts/truetype/jura/Jura-Regular.ttf",
        *_mac("Jura-Bold.ttf", "Jura-Medium.ttf", "Jura-Regular.ttf",
              "Jura[wght].ttf"),
    ],
    # M+ — clean Japanese-influenced design, unique round feel
    "M Plus": [
        "/usr/share/fonts/truetype/mplus/mplus-1p-bold.ttf",
        "/usr/share/fonts/truetype/mplus/mplus-1m-bold.ttf",
        "/usr/share/fonts/truetype/mplus/mplus-1p-regular.ttf",
        *_mac("MPLUS1-Bold.ttf", "MPLUS1p-Bold.ttf",
              "MPLUS1-Regular.ttf", "mplus-1p-bold.ttf"),
    ],
    # Linux Biolinum — humanist sans companion to Libertine
    "Linux Biolinum": [
        "/usr/share/fonts/truetype/linux-libertine/LinBiolinum_RB.ttf",
        "/usr/share/fonts/truetype/linux-libertine/LinBiolinum_R.ttf",
        *_mac("LinBiolinum_RB.ttf", "LinBiolinum_R.ttf"),
    ],
    # Nimbus Mono — clean typewriter aesthetic
    "Nimbus Mono": [
        "/usr/share/fonts/opentype/urw-base35/NimbusMonoPS-Bold.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusMonoPS-Regular.otf",
    ],
}

# Italic (bold-italic preferred, plain italic as fallback) font paths per family
FONT_FAMILY_ITALIC_PATHS: dict = {
    "Poppins": [
        "/usr/share/fonts/truetype/google-fonts/Poppins-BoldItalic.ttf",
        "/usr/share/fonts/truetype/google-fonts/Poppins-Italic.ttf",
        *_mac("Poppins-BoldItalic.ttf", "Poppins-Italic.ttf"),
    ],
    "Lora": [
        "/usr/share/fonts/truetype/google-fonts/Lora-Italic-Variable.ttf",
        *_mac("Lora-BoldItalic.ttf", "Lora-Italic.ttf", "Lora-Italic-Variable.ttf"),
    ],
    "DejaVu Sans": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        *_mac("DejaVuSans-BoldOblique.ttf", "DejaVuSans-Oblique.ttf"),
    ],
    "DejaVu Sans Condensed": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-BoldOblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Oblique.ttf",
        *_mac("DejaVuSansCondensed-BoldOblique.ttf", "DejaVuSansCondensed-Oblique.ttf"),
    ],
    "DejaVu Serif": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        *_mac("DejaVuSerif-BoldItalic.ttf", "DejaVuSerif-Italic.ttf"),
    ],
    "DejaVu Mono": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-BoldOblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf",
        *_mac("DejaVuSansMono-BoldOblique.ttf", "DejaVuSansMono-Oblique.ttf"),
    ],
    "Liberation Sans": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-BoldItalic.ttf",
        *_mac("LiberationSans-BoldItalic.ttf", "LiberationSans-Italic.ttf"),
    ],
    "Liberation Serif": [
        "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-BoldItalic.ttf",
        *_mac("LiberationSerif-BoldItalic.ttf", "LiberationSerif-Italic.ttf"),
    ],
    "Liberation Mono": [
        "/usr/share/fonts/truetype/liberation/LiberationMono-BoldItalic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Italic.ttf",
        *_mac("LiberationMono-BoldItalic.ttf", "LiberationMono-Italic.ttf"),
    ],
    "Caladea": [
        "/usr/share/fonts/truetype/crosextra/Caladea-BoldItalic.ttf",
        "/usr/share/fonts/truetype/crosextra/Caladea-Italic.ttf",
        *_mac("Caladea-BoldItalic.ttf", "Caladea-Italic.ttf"),
    ],
    "Carlito": [
        "/usr/share/fonts/truetype/crosextra/Carlito-BoldItalic.ttf",
        "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf",
        *_mac("Carlito-BoldItalic.ttf", "Carlito-Italic.ttf"),
    ],
    "Nimbus Sans": [
        "/usr/share/fonts/opentype/urw-base35/NimbusSans-BoldItalic.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusSans-Italic.otf",
    ],
    "Nimbus Sans Narrow": [
        "/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-BoldOblique.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Oblique.otf",
    ],
    "Nimbus Roman": [
        "/usr/share/fonts/opentype/urw-base35/NimbusRoman-BoldItalic.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Italic.otf",
    ],
    "Nimbus Mono": [
        "/usr/share/fonts/opentype/urw-base35/NimbusMonoPS-BoldItalic.otf",
        "/usr/share/fonts/opentype/urw-base35/NimbusMonoPS-Italic.otf",
    ],
    "URW Bookman": [
        "/usr/share/fonts/opentype/urw-base35/URWBookman-DemiItalic.otf",
        "/usr/share/fonts/opentype/urw-base35/URWBookman-LightItalic.otf",
    ],
    "URW Gothic": [
        "/usr/share/fonts/opentype/urw-base35/URWGothic-DemiOblique.otf",
        "/usr/share/fonts/opentype/urw-base35/URWGothic-BookOblique.otf",
    ],
    "EB Garamond": [
        "/usr/share/fonts/truetype/ebgaramond/EBGaramond-BoldItalic.ttf",
        "/usr/share/fonts/truetype/ebgaramond/EBGaramond-Italic.ttf",
        *_mac("EBGaramond-BoldItalic.ttf", "EBGaramond-Italic.ttf"),
    ],
}

# Default fallback order for italic when no family match found
_DEFAULT_ITALIC_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
    *_mac("DejaVuSans-BoldOblique.ttf", "DejaVuSans-Oblique.ttf"),
]

# Default fallback order when no font_family is specified
_DEFAULT_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    # macOS system fonts
    f"{_MAC_USER_FONTS}/OpenSans-Bold.ttf",
    f"{_MAC_USER_FONTS}/Roboto-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def load_font(size: int, font_family: Optional[str] = None, italic: bool = False) -> ImageFont.FreeTypeFont:
    """Try to load a font by family name, then fall back to system defaults.

    If *italic* is True, prefer bold-italic / oblique variants of the font.
    Falls back to the regular bold variant if no italic file is found.
    """
    candidates: List[str] = []

    if italic:
        # Prefer italic paths first, then fall back to regular bold paths
        if font_family and font_family in FONT_FAMILY_ITALIC_PATHS:
            candidates = FONT_FAMILY_ITALIC_PATHS[font_family]
        elif font_family:
            logger.warning(f"No italic variant for '{font_family}', falling back to regular bold.")
        # Add regular paths as fallback so we always get the right family
        if font_family and font_family in FONT_FAMILY_PATHS:
            candidates = candidates + FONT_FAMILY_PATHS[font_family]
        candidates = candidates + _DEFAULT_ITALIC_FONT_CANDIDATES + _DEFAULT_FONT_CANDIDATES
    else:
        if font_family and font_family in FONT_FAMILY_PATHS:
            candidates = FONT_FAMILY_PATHS[font_family]
        elif font_family:
            logger.warning(f"Unknown font_family '{font_family}', falling back to defaults.")
        candidates = candidates + _DEFAULT_FONT_CANDIDATES

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
