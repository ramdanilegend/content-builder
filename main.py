#!/usr/bin/env python3
"""
Blueprint Video Generator
=========================
Generates a video from a JSON blueprint configuration.

Usage
-----
    python main.py [blueprint.json]

If no path is provided, looks for 'blueprint.json' in the current directory.

Output
------
    output/<meta.title>.mp4
"""
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

from renderer.scene_builder import SceneBuilder

# ── logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  →  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ── helpers ───────────────────────────────────────────────────────────────────

def load_blueprint(path: str) -> dict:
    logger.info(f"📄  Loading blueprint: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    logger.info(
        f"    title={data['meta']['title']}  "
        f"res={data['meta']['resolution']}  "
        f"fps={data['meta']['fps']}  "
        f"scenes={len(data.get('scenes', []))}"
    )
    return data


def parse_resolution(meta: dict) -> tuple:
    """Return (width, height) from meta.resolution e.g. '1080x1920'."""
    res   = meta.get("resolution", "1080x1920")
    parts = res.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid resolution format: '{res}' (expected WxH)")
    return int(parts[0]), int(parts[1])


# ── entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    blueprint_path = sys.argv[1] if len(sys.argv) > 1 else "blueprint.json"

    if not Path(blueprint_path).exists():
        logger.error(f"Blueprint not found: {blueprint_path}")
        sys.exit(1)

    # ── load blueprint ────────────────────────────────────────────────────────
    blueprint   = load_blueprint(blueprint_path)
    meta        = blueprint["meta"]
    title       = meta["title"]
    canvas_size = parse_resolution(meta)
    fps         = int(meta.get("fps", 30))

    # ── prepare directories ───────────────────────────────────────────────────
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{title}.mp4"

    # Sanitise filename
    safe_title  = "".join(c if c.isalnum() or c in " _-" else "_" for c in title).strip()
    output_path = output_dir / f"{safe_title}.mp4"

    # Temp dir for intermediate files (TTS cache, etc.)
    temp_dir = Path(tempfile.mkdtemp(prefix="bpvg_"))
    logger.info(f"🗂   Temp dir: {temp_dir}")

    # ── render ────────────────────────────────────────────────────────────────
    try:
        builder = SceneBuilder(
            blueprint=blueprint,
            canvas_size=canvas_size,
            fps=fps,
            temp_dir=temp_dir,
        )
        await builder.build_all(str(output_path))
        logger.info(f"✅  Done!  Output: {output_path.resolve()}")

    except Exception as exc:
        logger.exception(f"❌  Fatal error: {exc}")
        sys.exit(1)

    finally:
        # Clean up temp files
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
