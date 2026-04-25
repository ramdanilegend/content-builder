#!/usr/bin/env python3
"""
Blueprint Video Generator — HTTP API
=====================================
Wraps the existing rendering pipeline in a FastAPI server so the
content-builder-fe frontend can hit it directly.

Usage
-----
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Endpoint
--------
    POST /generate
        multipart/form-data fields:
            blueprint        (str)   → serialised blueprint JSON
            output_filename  (str)   → desired filename (without .mp4)
            <asset-path>     (file)  → one field per asset, field-name = relative path
                                       e.g.  "assets/images/bg.jpg"

    GET  /health
        → {"status": "ok"}
"""

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

# Re-use helpers from the existing entry-point
from main import parse_resolution
from renderer.scene_builder import SceneBuilder

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  →  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("api")

# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Content Builder API",
    description="Video generation endpoint for content-builder-fe",
    version="1.0.0",
)

# Allow the Next.js dev server (any origin) to call us
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Sanitise a string for use as a filesystem filename."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip() or "output"


def _patch_asset_paths(blueprint: dict, work_dir: Path) -> dict:
    """
    Replace relative asset paths in the blueprint with absolute paths
    pointing into *work_dir*, where we've already written the uploaded files.

    Blueprint assets section (serialised form):
        {
          "images": {"bg_id": "assets/images/bg.jpg", ...},
          "videos": {"clip_id": "assets/videos/clip.mp4", ...},
          "audio":  {"bgm_id": "assets/audio/bgm.mp3", ...}
        }

    Global audio tracks reference asset IDs (not paths); the renderer
    resolves IDs via assets.audio — so we only need the assets map patched.
    """
    raw = blueprint.get("assets", {})
    for category in ("images", "videos", "audio"):
        section: Dict[str, str] = raw.get(category, {})
        for asset_id, rel_path in section.items():
            abs_path = str(work_dir / rel_path)
            section[asset_id] = abs_path
        raw[category] = section
    blueprint["assets"] = raw
    return blueprint


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/generate")
async def generate_video(request: Request):
    """
    Accept a multipart/form-data payload:

        blueprint        — serialised blueprint JSON (string)
        output_filename  — desired output filename without extension (string)
        <asset-path>     — one UploadFile per asset, field-name = relative path
                           e.g.  "assets/images/hero.jpg"

    Returns the rendered .mp4 file as a streaming download.
    """
    # ── parse multipart form ──────────────────────────────────────────────────
    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot parse form data: {exc}")

    blueprint_raw   = form.get("blueprint")
    output_filename = form.get("output_filename", "output")

    if not blueprint_raw:
        raise HTTPException(status_code=422, detail="Missing required field: blueprint")

    try:
        blueprint: dict = json.loads(blueprint_raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid blueprint JSON: {exc}")

    # ── create isolated working directory ─────────────────────────────────────
    work_dir = Path(tempfile.mkdtemp(prefix="bpvg_api_"))
    logger.info(f"📂  Work dir: {work_dir}  |  output_filename={output_filename!r}")

    try:
        # ── save uploaded asset files at their relative paths ─────────────────
        for field_name, field_value in form.multi_items():
            if field_name in ("blueprint", "output_filename"):
                continue

            # field_name is the relative path, e.g. "assets/images/bg.jpg"
            dest = work_dir / field_name
            dest.parent.mkdir(parents=True, exist_ok=True)

            if hasattr(field_value, "read"):
                content = await field_value.read()  # type: ignore[union-attr]
                dest.write_bytes(content)
                logger.info(f"  💾  Asset saved: {field_name} ({len(content):,} bytes)")
            else:
                logger.warning(f"  ⚠️   Field '{field_name}' is not a file – skipped")

        # ── patch asset paths to absolute ─────────────────────────────────────
        blueprint = _patch_asset_paths(blueprint, work_dir)

        # ── resolve canvas + fps ──────────────────────────────────────────────
        meta        = blueprint["meta"]
        canvas_size = parse_resolution(meta)
        fps         = int(meta.get("fps", 30))

        # ── prepare output path ───────────────────────────────────────────────
        safe_name   = _safe_name(str(output_filename))
        output_dir  = work_dir / "output"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{safe_name}.mp4"

        # ── temp dir for TTS cache & intermediate files ───────────────────────
        tts_temp = work_dir / "tts"
        tts_temp.mkdir(exist_ok=True)

        # ── run renderer ──────────────────────────────────────────────────────
        logger.info(f"🎬  Starting render → {output_path}")
        builder = SceneBuilder(
            blueprint=blueprint,
            canvas_size=canvas_size,
            fps=fps,
            temp_dir=tts_temp,
        )
        await builder.build_all(str(output_path))

        if not output_path.exists():
            raise RuntimeError("Renderer finished but output file was not created")

        logger.info(f"✅  Render complete: {output_path} ({output_path.stat().st_size:,} bytes)")

        # ── stream file back to client, clean up after send ───────────────────
        return FileResponse(
            path=str(output_path),
            media_type="video/mp4",
            filename=f"{safe_name}.mp4",
            background=BackgroundTask(shutil.rmtree, work_dir, True),
        )

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        logger.exception(f"❌  Render failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
