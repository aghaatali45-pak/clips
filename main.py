from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import struct
import tempfile
import uuid
import wave
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="Clips AI Media Import")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

TEMP_DIR = Path(os.getenv("TEMP_DIR", tempfile.gettempdir())) / "clips-ai-imports"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv("MAX_IMPORT_BYTES", str(750 * 1024 * 1024)))
EXCITING_WORDS = {
    "amazing", "wow", "unbelievable", "funny", "crazy", "insane", "best", "hilarious", "omg",
}


class ImportRequest(BaseModel):
    url: HttpUrl


class ClipRequest(BaseModel):
    start: float
    end: float


def supported_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com" or host.endswith(".tiktok.com") or host == "tiktok.com"


def youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or None
    if host.endswith("youtube.com") or host == "youtube.com":
        if parsed.path == "/watch":
            from urllib.parse import parse_qs
            return parse_qs(parsed.query).get("v", [None])[0]
        pieces = [part for part in parsed.path.split("/") if part]
        if len(pieces) > 1 and pieces[0] in {"shorts", "embed", "live"}:
            return pieces[1]
    return None


async def run_process(*args: str, timeout: int) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    return process.returncode or 0, stdout, stderr


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/import")
async def import_media(payload: ImportRequest):
    url = str(payload.url)
    if not supported_url(url):
        raise HTTPException(status_code=400, detail="Only public YouTube and TikTok URLs are supported.")
    if shutil.which("yt-dlp") is None:
        raise HTTPException(status_code=500, detail="yt-dlp is not installed on the server.")

    job_id = uuid.uuid4().hex
    workdir = TEMP_DIR / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    output_template = str(workdir / "video.%(ext)s")
    command = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--max-filesize", str(MAX_BYTES),
        "--format", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
        "--output", output_template, "--", url,
    ]
    try:
        code, _, stderr = await run_process(*command, timeout=240)
        if code:
            raise HTTPException(status_code=422, detail=stderr.decode("utf-8", "replace")[-900:] or "Could not import this URL.")
        candidates = [p for p in workdir.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm"}]
        if not candidates:
            raise HTTPException(status_code=422, detail="No downloadable media was found.")
        source, target = candidates[0], workdir / "source.mp4"
        if source.suffix.lower() != ".mp4":
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise HTTPException(status_code=500, detail="ffmpeg is not installed on the server.")
            code, _, _ = await run_process(ffmpeg, "-y", "-i", str(source), "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(target), timeout=300)
            if code:
                raise HTTPException(status_code=422, detail="Downloaded media could not be converted to MP4.")
        else:
            shutil.move(str(source), str(target))
        if target.stat().st_size > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Imported video exceeds the configured size limit.")
        (workdir / "source_url.txt").write_text(url, encoding="utf-8")
        return {"job_id": job_id, "download_url": f"/api/media/{job_id}", "expires_in": 900}
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except asyncio.TimeoutError:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Import timed out. Try a shorter public video.")


def parse_vtt(path: Path) -> list[dict]:
    if not path.exists():
        return []
    timestamp = re.compile(r"(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})")
    cues: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for block in re.split(r"\n\s*\n", text):
        lines = block.splitlines()
        for index, line in enumerate(lines):
            if "-->" not in line or index + 1 >= len(lines):
                continue
            parts = line.split("-->", 1)
            def seconds(value: str) -> float:
                match = timestamp.search(value)
                if not match:
                    return 0.0
                hours, minutes, seconds_part, millis = match.groups()
                return (int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds_part) + int(millis) / 1000)
            cue_text = re.sub(r"<[^>]+>", "", " ".join(lines[index + 1:])).strip()
            cue_text = re.sub(r"\s+", " ", cue_text)
            if cue_text:
                cues.append({"start": seconds(parts[0]), "end": seconds(parts[1]), "text": cue_text})
            break
    return cues


def audio_windows(wav_path: Path, duration: float) -> list[float]:
    with wave.open(str(wav_path), "rb") as audio:
        channels, sample_width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
        raw = audio.readframes(frames)
    if sample_width != 2 or not rate:
        return []
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    per_second = rate * channels
    step = max(1, per_second)
    rms_values: list[float] = []
    for offset in range(0, len(samples), step):
        chunk = samples[offset:offset + step]
        if not chunk:
            continue
        rms_values.append(math.sqrt(sum(sample * sample for sample in chunk) / len(chunk)) / 32768)
    return rms_values


def parse_timestamp(value: str) -> float:
    match = re.search(r"(?:(\d+):)?(\d{2}):(\d{2})", value)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


@app.post("/api/import/{job_id}/best-moments")
async def best_moments(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    workdir = TEMP_DIR / job_id
    video = workdir / "source.mp4"
    if not video.is_file():
        raise HTTPException(status_code=404, detail="Imported video has expired or does not exist.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="ffmpeg is not installed on the server.")

    try:
        code, stdout, _ = await run_process(
            ffmpeg, "-i", str(video), "-f", "null", "-", timeout=60,
        )
        metadata = (stdout.decode("utf-8", "replace"))
        # ffmpeg reports duration on stderr; probe in the same lightweight install.
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            probe_code, probe_out, _ = await run_process(ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video), timeout=20)
            duration = float(probe_out.decode().strip()) if probe_code == 0 else 0
        else:
            duration_match = re.search(rb"Duration: (\d+:\d+:\d+(?:\.\d+)?)", _)
            duration = parse_timestamp(duration_match.group(1).decode()) if duration_match else 0
        if duration < 15:
            raise HTTPException(status_code=422, detail="Video must be at least 15 seconds long to find moments.")
        wav_path = workdir / "analysis.wav"
        code, _, stderr = await run_process(ffmpeg, "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(wav_path), timeout=180)
        if code:
            raise HTTPException(status_code=422, detail="Could not extract audio for analysis.")
        energy = audio_windows(wav_path, duration)

        transcript: list[dict] = []
        source_url_file = workdir / "source_url.txt"
        if source_url_file.exists():
            source_url = source_url_file.read_text(encoding="utf-8")
            video_id = youtube_id(source_url)
            if video_id:
                sub_template = str(workdir / "captions.%(ext)s")
                await run_process(
                    "yt-dlp", "--skip-download", "--no-warnings", "--write-subs", "--write-auto-subs",
                    "--sub-langs", "en.*,en", "--sub-format", "vtt/best", "--output", sub_template,
                    "--", source_url, timeout=90,
                )
                vtt_files = list(workdir.glob("captions*.vtt"))
                if vtt_files:
                    transcript = parse_vtt(vtt_files[0])

        max_length = min(30.0, duration)
        min_length = min(15.0, max_length)
        window = min(20.0, max_length)
        step = 5.0
        candidates = []
        max_start = max(0.0, duration - window)
        starts = [float(i) for i in range(0, int(max_start) + 1, int(step))]
        if not starts or starts[-1] < max_start:
            starts.append(max_start)
        for start in starts:
            end = min(duration, start + window)
            if end - start < min_length:
                continue
            energy_slice = energy[int(start):max(int(start) + 1, int(end))]
            avg_energy = sum(energy_slice) / len(energy_slice) if energy_slice else 0.0
            peak = max(energy_slice, default=0.0)
            changes = [abs(b - a) for a, b in zip(energy_slice, energy_slice[1:])]
            sudden = sum(changes) / len(changes) if changes else 0.0
            text_cues = [cue for cue in transcript if cue["end"] >= start and cue["start"] <= end]
            text = " ".join(cue["text"] for cue in text_cues)
            lower_text = text.lower()
            keyword_hits = sorted({word for word in EXCITING_WORDS if re.search(r"\b" + re.escape(word) + r"\b", lower_text)})
            candidates.append({"start": start, "end": end, "energy": avg_energy, "peak": peak, "change": sudden, "hits": keyword_hits, "text": text})

        if not candidates:
            raise HTTPException(status_code=422, detail="No suitable clip segments found.")
        def normalized(key: str) -> list[float]:
            values = [item[key] for item in candidates]
            lo, hi = min(values), max(values)
            return [(value - lo) / (hi - lo) if hi > lo else 0.0 for value in values]
        norm_energy, norm_peak, norm_change, norm_keywords = normalized("energy"), normalized("peak"), normalized("change"), normalized("hits")
        for index, item in enumerate(candidates):
            item["score"] = round(100 * (0.35 * norm_energy[index] + 0.25 * norm_peak[index] + 0.20 * norm_change[index] + 0.20 * norm_keywords[index]))
            item["reason"] = ", ".join(item["hits"][:3]) if item["hits"] else ("Audio energy peak" if item["peak"] > item["energy"] * 1.5 else "High-energy moment")

        selected = []
        for item in sorted(candidates, key=lambda candidate: candidate["score"], reverse=True):
            if all(item["end"] <= chosen["start"] or item["start"] >= chosen["end"] for chosen in selected):
                selected.append(item)
                if len(selected) == 4:
                    break
        selected.sort(key=lambda item: item["start"])
        result = [{"start": round(item["start"], 2), "end": round(item["end"], 2), "score": item["score"], "reason": item["reason"], "transcript": item["text"][:220]} for item in selected]
        return {"job_id": job_id, "method": "transcript + audio energy" if transcript else "audio energy only", "count": len(result), "moments": result}
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Moment analysis timed out.")
    except (OSError, ValueError, wave.Error) as error:
        raise HTTPException(status_code=422, detail=f"Could not analyze media: {error}")


@app.post("/api/import/{job_id}/clip")
async def create_clip(job_id: str, payload: ClipRequest):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    workdir = TEMP_DIR / job_id
    video = workdir / "source.mp4"
    if not video.is_file():
        raise HTTPException(status_code=404, detail="Imported video has expired or does not exist.")
    if payload.start < 0 or payload.end <= payload.start or not 15 <= payload.end - payload.start <= 30:
        raise HTTPException(status_code=422, detail="Clip duration must be between 15 and 30 seconds.")
    output = workdir / f"clip-{uuid.uuid4().hex}.mp4"
    code, _, _ = await run_process(
        "ffmpeg", "-y", "-ss", str(payload.start), "-i", str(video), "-t", str(payload.end - payload.start),
        "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(output), timeout=180,
    )
    if code or not output.is_file():
        raise HTTPException(status_code=422, detail="Could not cut the requested clip.")
    return {"download_url": f"/api/import/{job_id}/clips/{output.name}", "filename": output.name}


@app.get("/api/import/{job_id}/clips/{filename}")
def download_clip(job_id: str, filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id) or not re.fullmatch(r"clip-[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(status_code=400, detail="Invalid media path.")
    target = TEMP_DIR / job_id / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Clip not found or expired.")
    return FileResponse(target, media_type="video/mp4", filename=filename)


@app.get("/api/media/{job_id}")
def media(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    target = TEMP_DIR / job_id / "source.mp4"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Media has expired or does not exist.")
    return FileResponse(target, media_type="video/mp4", filename="source.mp4")


@app.delete("/api/media/{job_id}")
def cleanup(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    shutil.rmtree(TEMP_DIR / job_id, ignore_errors=True)
    return {"ok": True}
