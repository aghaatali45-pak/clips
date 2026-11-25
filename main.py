from __future__ import annotations

import asyncio
import math
import os
import re
import shutil
import struct
import tempfile
import uuid
import wave
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
EXCITING_WORDS = {"amazing", "wow", "unbelievable", "funny", "crazy", "insane", "best", "hilarious", "omg"}


class ImportRequest(BaseModel):
    url: HttpUrl


class ClipRequest(BaseModel):
    start: float
    end: float


def supported_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com") or host == "tiktok.com" or host.endswith(".tiktok.com")


def youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or None
    if host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        pieces = [part for part in parsed.path.split("/") if part]
        if len(pieces) > 1 and pieces[0] in {"shorts", "embed", "live"}:
            return pieces[1]
    return None


async def run_process(*args: str, timeout: int) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
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
    command = ["yt-dlp", "--no-playlist", "--no-warnings", "--max-filesize", str(MAX_BYTES), "--format", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4", "--output", str(workdir / "video.%(ext)s"), "--", url]
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
    cues = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8", errors="replace")):
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
                return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds_part) + int(millis) / 1000
            cue_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", " ".join(lines[index + 1:]))).strip()
            if cue_text:
                cues.append({"start": seconds(parts[0]), "end": seconds(parts[1]), "text": cue_text})
            break
    return cues


def audio_windows(wav_path: Path) -> list[float]:
    with wave.open(str(wav_path), "rb") as audio:
        channels, sample_width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
        raw = audio.readframes(frames)
    if sample_width != 2 or not rate:
        return []
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    per_second = rate * channels
    values = []
    for offset in range(0, len(samples), per_second):
        chunk = samples[offset:offset + per_second]
        if chunk:
            values.append(math.sqrt(sum(sample * sample for sample in chunk) / len(chunk)) / 32768)
    return values


@app.post("/api/import/{job_id}/best-moments")
async def best_moments(job_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")
    workdir = TEMP_DIR / job_id
    video = workdir / "source.mp4"
    if not video.is_file():
        raise HTTPException(status_code=404, detail="Imported video has expired or does not exist.")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise HTTPException(status_code=500, detail="ffmpeg and ffprobe are required for analysis.")
    try:
        code, probe_out, _ = await run_process(ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video), timeout=20)
        duration = float(probe_out.decode().strip()) if code == 0 else 0
        if duration < 15:
            raise HTTPException(status_code=422, detail="Video must be at least 15 seconds long to find moments.")
        wav_path = workdir / "analysis.wav"
        code, _, _ = await run_process(ffmpeg, "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(wav_path), timeout=180)
        if code:
            raise HTTPException(status_code=422, detail="Could not extract audio for analysis.")
        energy = audio_windows(wav_path)
        transcript = []
        source_url_file = workdir / "source_url.txt"
        if source_url_file.exists():
            source_url = source_url_file.read_text(encoding="utf-8")
            if youtube_id(source_url):
                await run_process("yt-dlp", "--skip-download", "--no-warnings", "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,en", "--sub-format", "vtt/best", "--output", str(workdir / "captions.%(ext)s"), "--", source_url, timeout=90)
                vtt_files = list(workdir.glob("captions*.vtt"))
                if vtt_files:
                    transcript = parse_vtt(vtt_files[0])

        window, step = min(20.0, duration), 5
        max_start = max(0.0, duration - window)
        starts = [float(i) for i in range(0, int(max_start) + 1, step)]
        if not starts or starts[-1] < max_start:
            starts.append(max_start)
        candidates = []
        for start in starts:
            end = min(duration, start + window)
            energy_slice = energy[int(start):max(int(start) + 1, int(end))]
            avg = sum(energy_slice) / len(energy_slice) if energy_slice else 0.0
            peak = max(energy_slice, default=0.0)
            changes = [abs(b - a) for a, b in zip(energy_slice, energy_slice[1:])]
            sudden = sum(changes) / len(changes) if changes else 0.0
            cues = [cue for cue in transcript if cue["end"] >= start and cue["start"] <= end]
            text = " ".join(cue["text"] for cue in cues)
            hits = sorted({word for word in EXCITING_WORDS if re.search(r"\b" + re.escape(word) + r"\b", text.lower())})
            candidates.append({"start": start, "end": end, "energy": avg, "peak": peak, "change": sudden, "hits": hits, "text": text})
        if not candidates:
            raise HTTPException(status_code=422, detail="No suitable clip segments found.")
        def normalized(key: str) -> list[float]:
            values = [item[key] for item in candidates]
            low, high = min(values), max(values)
            return [(value - low) / (high - low) if high > low else 0.0 for value in values]
        norm_energy, norm_peak, norm_change, norm_keywords = (normalized(key) for key in ("energy", "peak", "change", "hits"))
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
        moments = [{"start": round(item["start"], 2), "end": round(item["end"], 2), "score": item["score"], "reason": item["reason"], "title": item["reason"], "transcript": item["text"][:220]} for item in selected]
        transcript = transcript[:1500]
        transcript_text_length = 0
        bounded_transcript = []
        for cue in transcript:
            cue_item = {"start": cue["start"], "end": cue["end"], "text": cue["text"][:500]}
            transcript_text_length += len(cue_item["text"])
            if transcript_text_length > 24000:
                break
            bounded_transcript.append(cue_item)
        return {"job_id": job_id, "duration": duration, "method": "transcript + audio energy" if bounded_transcript else "audio energy only", "count": len(moments), "moments": moments, "transcript": bounded_transcript}
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Moment analysis timed out.")
    except (OSError, ValueError, wave.Error, struct.error) as error:
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
    code, _, _ = await run_process("ffmpeg", "-y", "-ss", str(payload.start), "-i", str(video), "-t", str(payload.end - payload.start), "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(output), timeout=180)
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
