from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
import asyncio
import os
import shutil
import tempfile
import uuid
from pathlib import Path

app = FastAPI(title="Clips AI Media Import")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

TEMP_DIR = Path(os.getenv("TEMP_DIR", tempfile.gettempdir())) / "clips-ai-imports"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv("MAX_IMPORT_BYTES", str(750 * 1024 * 1024)))


class ImportRequest(BaseModel):
    url: HttpUrl


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/import")
async def import_media(payload: ImportRequest):
    url = str(payload.url)
    if not ("youtube.com/" in url or "youtu.be/" in url or "tiktok.com/" in url):
        raise HTTPException(status_code=400, detail="Only public YouTube and TikTok URLs are supported.")

    if shutil.which("yt-dlp") is None:
        raise HTTPException(status_code=500, detail="yt-dlp is not installed on the server.")

    job_id = uuid.uuid4().hex
    workdir = TEMP_DIR / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    output_template = str(workdir / "video.%(ext)s")

    command = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--max-filesize", str(MAX_BYTES),
        "--format", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--", url,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=240)
        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace")[-900:] or "Could not import this URL."
            raise HTTPException(status_code=422, detail=detail)

        candidates = [p for p in workdir.iterdir() if p.is_file() and p.suffix.lower() in (".mp4", ".mkv", ".webm")]
        if not candidates:
            raise HTTPException(status_code=422, detail="No downloadable media was found.")

        source = candidates[0]
        target = workdir / "source.mp4"
        if source.suffix.lower() != ".mp4":
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise HTTPException(status_code=500, detail="ffmpeg is not installed on the server.")
            convert = await asyncio.create_subprocess_exec(
                ffmpeg, "-y", "-i", str(source), "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(convert.communicate(), timeout=300)
            if convert.returncode != 0:
                raise HTTPException(status_code=422, detail="Downloaded media could not be converted to MP4.")
        else:
            shutil.move(str(source), str(target))

        if target.stat().st_size > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Imported video exceeds the configured size limit.")

        return {"job_id": job_id, "download_url": f"/api/media/{job_id}", "expires_in": 900}
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except asyncio.TimeoutError:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Import timed out. Try a shorter public video.")


@app.get("/api/media/{job_id}")
def media(job_id: str):
    if not job_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    target = TEMP_DIR / job_id / "source.mp4"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Media has expired or does not exist.")
    return FileResponse(target, media_type="video/mp4", filename="source.mp4")


@app.delete("/api/media/{job_id}")
def cleanup(job_id: str):
    workdir = TEMP_DIR / job_id
    shutil.rmtree(workdir, ignore_errors=True)
    return {"ok": True}
