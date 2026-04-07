#!/usr/bin/env python3
"""
Generate sample assets for blueprint testing.
Creates background images, a logo, and a simple BGM wav file.
"""
import math
import struct
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
ASSETS = Path("assets")


# ── helpers ───────────────────────────────────────────────────────────────────

def load_font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def vertical_gradient(color_top, color_bottom, w=W, h=H):
    """Create a solid vertical gradient image."""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * t)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * t)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def add_noise(img, amount=12):
    """Add subtle noise texture to make gradient less flat."""
    arr = np.array(img).astype(np.int16)
    noise = np.random.randint(-amount, amount, arr.shape, dtype=np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def draw_centered_text(draw, text, y_pct, font, color="#FFFFFF", stroke_color="#000000", stroke_width=3):
    """Draw horizontally centered text at y_pct% height."""
    y = int(y_pct / 100 * H)
    try:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw, _ = font.getsize(text)
    x = (W - tw) // 2
    # stroke
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=color)


# ── background images ─────────────────────────────────────────────────────────

def make_bg_intro():
    img = vertical_gradient((10, 20, 60), (30, 80, 120))
    img = add_noise(img)
    draw = ImageDraw.Draw(img)
    # decorative circles
    for cx, cy, r, alpha in [(200, 400, 300, 30), (900, 1600, 400, 20), (540, 960, 600, 10)]:
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, alpha), width=2)
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img


def make_bg_tip1():
    img = vertical_gradient((60, 20, 10), (140, 60, 20))
    img = add_noise(img)
    draw = ImageDraw.Draw(img)
    # diagonal lines texture
    for i in range(0, W + H, 60):
        draw.line([(i, 0), (0, i)], fill=(255, 180, 50, 30), width=1)
    return img


def make_bg_tip2():
    img = vertical_gradient((10, 50, 30), (20, 100, 60))
    img = add_noise(img)
    return img


def make_bg_tip3():
    img = vertical_gradient((50, 10, 60), (100, 20, 120))
    img = add_noise(img)
    return img


def make_bg_outro():
    img = vertical_gradient((15, 15, 15), (40, 40, 40))
    img = add_noise(img, amount=6)
    return img


# ── logo ──────────────────────────────────────────────────────────────────────

def make_logo(size=200):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # circle background
    draw.ellipse([0, 0, size, size], fill=(255, 200, 0, 230))
    # letter
    font = load_font(int(size * 0.55))
    letter = "CB"
    try:
        bbox = font.getbbox(letter)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = font.getsize(letter)
    draw.text(((size - tw) // 2, (size - th) // 2 - 10), letter, font=font, fill=(20, 20, 20, 255))
    return img


# ── bgm (simple pleasant wav) ─────────────────────────────────────────────────

def make_bgm(path: Path, duration_s=30, sample_rate=44100):
    """
    Generate a gentle background music track:
    - soft pad chord (C major: C4, E4, G4) with slow attack/release
    - subtle low-pass style by blending harmonics
    """
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)

    # C major chord frequencies (C4, E4, G4 + octave doublings)
    freqs = [261.63, 329.63, 392.00, 523.25, 659.25]
    weights = [1.0, 0.7, 0.8, 0.5, 0.4]

    signal = np.zeros_like(t)
    for f, w in zip(freqs, weights):
        signal += w * np.sin(2 * np.pi * f * t)
        # add 2nd harmonic (softens tone)
        signal += (w * 0.2) * np.sin(2 * np.pi * f * 2 * t)

    # Slow envelope: fade in 3s, sustain, fade out 3s
    envelope = np.ones_like(t)
    fade_samples = int(3 * sample_rate)
    envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
    envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
    signal *= envelope

    # Normalize to 20% volume so it's background-quiet
    signal = signal / np.max(np.abs(signal)) * 0.20
    pcm = (signal * 32767).astype(np.int16)

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())

    print(f"  ✅  BGM: {path} ({duration_s}s)")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Generating sample assets…\n")

    (ASSETS / "images").mkdir(parents=True, exist_ok=True)
    (ASSETS / "audio").mkdir(parents=True, exist_ok=True)

    tasks = [
        ("bg_intro.png",  make_bg_intro),
        ("bg_tip1.png",   make_bg_tip1),
        ("bg_tip2.png",   make_bg_tip2),
        ("bg_tip3.png",   make_bg_tip3),
        ("bg_outro.png",  make_bg_outro),
    ]

    for fname, fn in tasks:
        path = ASSETS / "images" / fname
        img = fn()
        img.save(path)
        print(f"  ✅  Image: {path}")

    logo = make_logo()
    logo.save(ASSETS / "images" / "logo.png")
    print(f"  ✅  Logo: {ASSETS / 'images' / 'logo.png'}")

    make_bgm(ASSETS / "audio" / "bgm.wav")

    print("\nAll assets generated. Run:\n  python main.py blueprint.ready.json")


if __name__ == "__main__":
    main()
