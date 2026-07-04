import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pika
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
AUDIO_DIR = DATA_DIR / "audio"
TEXT_DIR = DATA_DIR / "text"
VIDEO_DIR = DATA_DIR / "video"
RESULTS_DIR = DATA_DIR / "results"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://homeserver.local:8080").rstrip("/")
AMQP_URL = os.environ["AMQP_URL"]
EXCHANGE = os.environ.get("GPU_EXCHANGE", "gpu.jobs")

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

app = FastAPI(title="GPU Job API")

AUDIO_UPLOADS = Counter("gpu_job_api_audio_uploads_total", "Uploaded audio files")
AUDIO_UPLOAD_BYTES = Counter("gpu_job_api_audio_upload_bytes_total", "Uploaded audio bytes")
TEXT_UPLOADS = Counter("gpu_job_api_text_uploads_total", "Uploaded text files")
TEXT_UPLOAD_BYTES = Counter("gpu_job_api_text_upload_bytes_total", "Uploaded text bytes")
VIDEO_UPLOADS = Counter("gpu_job_api_video_uploads_total", "Uploaded video files")
VIDEO_UPLOAD_BYTES = Counter("gpu_job_api_video_upload_bytes_total", "Uploaded video bytes")
JOBS_PUBLISHED = Counter("gpu_job_api_jobs_published_total", "Published GPU jobs", ["type"])
RESULTS_RECEIVED = Counter("gpu_job_api_results_received_total", "Received GPU job results", ["content_type"])
RESULT_BYTES = Counter("gpu_job_api_result_bytes_total", "Received GPU job result bytes")
AUDIO_FILES = Gauge("gpu_job_api_audio_files", "Stored audio files")
AUDIO_BYTES = Gauge("gpu_job_api_audio_bytes", "Stored audio bytes")
TEXT_FILES = Gauge("gpu_job_api_text_files", "Stored text files")
TEXT_BYTES = Gauge("gpu_job_api_text_bytes", "Stored text bytes")
VIDEO_FILES = Gauge("gpu_job_api_video_files", "Stored video files")
VIDEO_BYTES = Gauge("gpu_job_api_video_bytes", "Stored video bytes")
RESULT_JOBS = Gauge("gpu_job_api_result_jobs", "Stored result job directories")


class WhisperJobRequest(BaseModel):
    input_url: str | None = None
    audio_file: str | None = None
    output_url: str | None = None
    language: str = "auto"
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class EmbeddingJobRequest(BaseModel):
    text: str | None = None
    input_url: str | None = None
    text_file: str | None = None
    output_url: str | None = None
    model: str = "nomic-embed-text"
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class VideoJobRequest(BaseModel):
    input_url: str | None = None
    video_file: str | None = None
    output_url: str | None = None
    codec: str = "h264_nvenc"
    format: str = "mp4"
    scale: str | None = "1280:-2"
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


def now_rfc3339() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_filename(name: str) -> str:
    cleaned = SAFE_NAME_RE.sub("-", Path(name).name).strip(".-")
    if not cleaned:
        cleaned = f"audio-{uuid.uuid4()}.bin"
    return cleaned


def ensure_dirs() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def stored_files(directory: Path) -> list[Path]:
    ensure_dirs()
    return [path for path in directory.iterdir() if path.is_file()]


def update_storage_metrics() -> None:
    ensure_dirs()
    audio_files = stored_files(AUDIO_DIR)
    text_files = stored_files(TEXT_DIR)
    video_files = stored_files(VIDEO_DIR)
    result_jobs = [path for path in RESULTS_DIR.iterdir() if path.is_dir()]
    AUDIO_FILES.set(len(audio_files))
    AUDIO_BYTES.set(sum(path.stat().st_size for path in audio_files))
    TEXT_FILES.set(len(text_files))
    TEXT_BYTES.set(sum(path.stat().st_size for path in text_files))
    VIDEO_FILES.set(len(video_files))
    VIDEO_BYTES.set(sum(path.stat().st_size for path in video_files))
    RESULT_JOBS.set(len(result_jobs))


def publish_job(job: dict[str, Any], routing_key: str) -> None:
    params = pika.URLParameters(AMQP_URL)
    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(job).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
        )
    finally:
        connection.close()


async def store_upload(directory: Path, file: UploadFile) -> tuple[str, int]:
    ensure_dirs()
    filename = safe_filename(file.filename or "")
    target = directory / filename

    if target.exists():
        stem = target.stem
        suffix = target.suffix
        target = directory / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        filename = target.name

    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)

    size = target.stat().st_size
    update_storage_metrics()
    return filename, size


def list_stored_files(directory: Path, route: str) -> dict[str, list[dict[str, Any]]]:
    files = []
    for path in sorted(stored_files(directory)):
        files.append(
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "url": f"{PUBLIC_BASE_URL}/{route}/{path.name}",
            }
        )
    return {"files": files}


def stored_file_response(directory: Path, filename: str, detail_name: str) -> FileResponse:
    path = directory / safe_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{detail_name} file not found")
    return FileResponse(path)


def default_result_url(job_id: str) -> str:
    return f"{PUBLIC_BASE_URL}/results/{job_id}"


@app.on_event("startup")
def startup() -> None:
    ensure_dirs()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    update_storage_metrics()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/audio")
async def upload_audio(file: UploadFile = File(...)) -> dict[str, str]:
    filename, size = await store_upload(AUDIO_DIR, file)
    AUDIO_UPLOADS.inc()
    AUDIO_UPLOAD_BYTES.inc(size)

    return {
        "filename": filename,
        "url": f"{PUBLIC_BASE_URL}/audio/{filename}",
    }


@app.get("/audio")
def list_audio() -> dict[str, list[dict[str, Any]]]:
    return list_stored_files(AUDIO_DIR, "audio")


@app.get("/audio/{filename}")
def get_audio(filename: str) -> FileResponse:
    return stored_file_response(AUDIO_DIR, filename, "audio")


@app.head("/audio/{filename}")
def head_audio(filename: str) -> FileResponse:
    return get_audio(filename)


@app.post("/text")
async def upload_text(file: UploadFile = File(...)) -> dict[str, str]:
    filename, size = await store_upload(TEXT_DIR, file)
    TEXT_UPLOADS.inc()
    TEXT_UPLOAD_BYTES.inc(size)

    return {
        "filename": filename,
        "url": f"{PUBLIC_BASE_URL}/text/{filename}",
    }


@app.get("/text")
def list_text() -> dict[str, list[dict[str, Any]]]:
    return list_stored_files(TEXT_DIR, "text")


@app.get("/text/{filename}")
def get_text(filename: str) -> FileResponse:
    return stored_file_response(TEXT_DIR, filename, "text")


@app.head("/text/{filename}")
def head_text(filename: str) -> FileResponse:
    return get_text(filename)


@app.post("/video")
async def upload_video(file: UploadFile = File(...)) -> dict[str, str]:
    filename, size = await store_upload(VIDEO_DIR, file)
    VIDEO_UPLOADS.inc()
    VIDEO_UPLOAD_BYTES.inc(size)

    return {
        "filename": filename,
        "url": f"{PUBLIC_BASE_URL}/video/{filename}",
    }


@app.get("/video")
def list_video() -> dict[str, list[dict[str, Any]]]:
    return list_stored_files(VIDEO_DIR, "video")


@app.get("/video/{filename}")
def get_video(filename: str) -> FileResponse:
    return stored_file_response(VIDEO_DIR, filename, "video")


@app.head("/video/{filename}")
def head_video(filename: str) -> FileResponse:
    return get_video(filename)


@app.post("/jobs/whisper")
def create_whisper_job(request: WhisperJobRequest) -> dict[str, Any]:
    if request.input_url and request.audio_file:
        raise HTTPException(status_code=400, detail="use either input_url or audio_file, not both")

    if request.audio_file:
        filename = safe_filename(request.audio_file)
        audio_path = AUDIO_DIR / filename
        if not audio_path.is_file():
            raise HTTPException(status_code=404, detail="audio_file not found")
        input_url = f"{PUBLIC_BASE_URL}/audio/{filename}"
    elif request.input_url:
        input_url = request.input_url
    else:
        raise HTTPException(status_code=400, detail="input_url or audio_file is required")

    output_url = request.output_url or default_result_url(request.job_id)
    job = {
        "id": request.job_id,
        "type": "whisper",
        "created_at": now_rfc3339(),
        "payload": {
            "input_url": input_url,
            "output_url": output_url,
            "language": request.language,
        },
    }
    publish_job(job, routing_key="whisper")
    JOBS_PUBLISHED.labels(type="whisper").inc()
    return {
        "published": True,
        "job": job,
    }


@app.post("/jobs/embedding")
def create_embedding_job(request: EmbeddingJobRequest) -> dict[str, Any]:
    sources = [request.text is not None, request.input_url is not None, request.text_file is not None]
    if sum(sources) != 1:
        raise HTTPException(status_code=400, detail="use exactly one of text, input_url, or text_file")

    output_url = request.output_url or default_result_url(request.job_id)
    payload: dict[str, Any] = {
        "output_url": output_url,
        "model": request.model,
    }

    if request.text is not None:
        payload["text"] = request.text
    elif request.text_file is not None:
        filename = safe_filename(request.text_file)
        text_path = TEXT_DIR / filename
        if not text_path.is_file():
            raise HTTPException(status_code=404, detail="text_file not found")
        payload["input_url"] = f"{PUBLIC_BASE_URL}/text/{filename}"
    elif request.input_url is not None:
        payload["input_url"] = request.input_url

    job = {
        "id": request.job_id,
        "type": "embedding",
        "created_at": now_rfc3339(),
        "payload": payload,
    }
    publish_job(job, routing_key="embedding")
    JOBS_PUBLISHED.labels(type="embedding").inc()
    return {
        "published": True,
        "job": job,
    }


@app.post("/jobs/video")
def create_video_job(request: VideoJobRequest) -> dict[str, Any]:
    if request.input_url and request.video_file:
        raise HTTPException(status_code=400, detail="use either input_url or video_file, not both")

    if request.video_file:
        filename = safe_filename(request.video_file)
        video_path = VIDEO_DIR / filename
        if not video_path.is_file():
            raise HTTPException(status_code=404, detail="video_file not found")
        input_url = f"{PUBLIC_BASE_URL}/video/{filename}"
    elif request.input_url:
        input_url = request.input_url
    else:
        raise HTTPException(status_code=400, detail="input_url or video_file is required")

    payload = {
        "input_url": input_url,
        "output_url": request.output_url or default_result_url(request.job_id),
        "codec": request.codec,
        "format": request.format,
    }
    if request.scale:
        payload["scale"] = request.scale

    job = {
        "id": request.job_id,
        "type": "video",
        "created_at": now_rfc3339(),
        "payload": payload,
    }
    publish_job(job, routing_key="video")
    JOBS_PUBLISHED.labels(type="video").inc()
    return {
        "published": True,
        "job": job,
    }


@app.post("/results/{job_id}")
async def receive_result(job_id: str, request: Request) -> JSONResponse:
    ensure_dirs()
    result_dir = RESULTS_DIR / safe_filename(job_id)
    result_dir.mkdir(parents=True, exist_ok=True)

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        saved: dict[str, str] = {}
        fields: dict[str, Any] = {}
        for key, value in form.multi_items():
            if isinstance(value, StarletteUploadFile):
                filename = safe_filename(value.filename or key)
                target = result_dir / filename
                bytes_written = 0
                with target.open("wb") as out:
                    while chunk := await value.read(1024 * 1024):
                        bytes_written += len(chunk)
                        out.write(chunk)
                RESULT_BYTES.inc(bytes_written)
                saved[key] = filename
            else:
                fields[key] = value

        (result_dir / "metadata.json").write_text(json.dumps(fields, indent=2), encoding="utf-8")
        RESULTS_RECEIVED.labels(content_type="multipart").inc()
        update_storage_metrics()
        return JSONResponse({"stored": True, "job_id": job_id, "files": saved, "fields": fields})

    body = await request.body()
    if "application/json" in content_type:
        data = json.loads(body.decode("utf-8") or "{}")
        (result_dir / "result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        RESULTS_RECEIVED.labels(content_type="json").inc()
        RESULT_BYTES.inc(len(body))
        update_storage_metrics()
        return JSONResponse({"stored": True, "job_id": job_id, "result": data})

    target = result_dir / "result.bin"
    target.write_bytes(body)
    RESULTS_RECEIVED.labels(content_type="binary").inc()
    RESULT_BYTES.inc(len(body))
    update_storage_metrics()
    return JSONResponse({"stored": True, "job_id": job_id, "bytes": len(body)})


@app.get("/results/{job_id}")
def get_result(job_id: str) -> dict[str, Any]:
    result_dir = RESULTS_DIR / safe_filename(job_id)
    if not result_dir.is_dir():
        raise HTTPException(status_code=404, detail="result not found")

    files = []
    for path in sorted(result_dir.iterdir()):
        if path.is_file():
            files.append({"filename": path.name, "bytes": path.stat().st_size})

    result_file = result_dir / "result.json"
    if result_file.is_file():
        return {
            "job_id": job_id,
            "files": files,
            "result": json.loads(result_file.read_text(encoding="utf-8")),
        }

    return {"job_id": job_id, "files": files}
