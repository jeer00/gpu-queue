# RabbitMQ GPU Stack

Server-side stack for GPU job queueing and monitoring.

## Services

- RabbitMQ AMQP: `http://homeserver.local:5672`
- RabbitMQ management UI: `http://homeserver.local:15672`
- RabbitMQ Prometheus metrics: `http://homeserver.local:15692/metrics`
- GPU Job API: set by `JOB_API_PUBLIC_BASE_URL` in `.env`
- Prometheus: `http://homeserver.local:9091`
- Grafana: `http://homeserver.local:3001`
- Homeserver Node Exporter: `http://homeserver.local:9100/metrics`

## Start

```sh
cd /home/homeserver/data/rabbitmq-gpu-stack
cp .env.example .env
editor .env
docker compose up -d
```

This directory includes a generated `.env` on this machine. Keep it private. Regenerate it from `.env.example` if you want different credentials.

## RabbitMQ Topology

- Exchange: `gpu.jobs`, type `direct`
- Dead-letter exchange: `gpu.dead`, type `direct`
- Queues: `gpu.whisper`, `gpu.embeddings`, `gpu.video`, `gpu.dead`
- Routing keys: `whisper`, `embedding`, `video`

The worker should connect with `RABBITMQ_URL` from its local env file and consume from the queue matching the job type.

## GPU Job API

The `job-api` service keeps RabbitMQ messages small. Audio and results move over
HTTP, while RabbitMQ carries job metadata.

Upload audio:

```sh
curl -F file=@test-project/audio/article-one-voice.wav \
  "$JOB_API_PUBLIC_BASE_URL/audio"
```

Publish a Whisper job for an uploaded file:

```sh
curl -X POST "$JOB_API_PUBLIC_BASE_URL/jobs/whisper" \
  -H 'content-type: application/json' \
  -d '{"audio_file":"article-one-voice.wav","language":"auto"}'
```

The published RabbitMQ job has this shape:

```json
{
  "id": "job-id",
  "type": "whisper",
  "created_at": "2026-07-04T13:45:00+02:00",
  "payload": {
    "input_url": "<JOB_API_PUBLIC_BASE_URL>/audio/article-one-voice.wav",
    "output_url": "<JOB_API_PUBLIC_BASE_URL>/results/job-id",
    "language": "auto"
  }
}
```

The GPU worker should download `payload.input_url`, run Whisper, then `POST` the
result to `payload.output_url`. For JSON results:

```sh
curl -X POST "$JOB_API_PUBLIC_BASE_URL/results/job-id" \
  -H 'content-type: application/json' \
  -d '{"status":"completed","text":"transcript here"}'
```

Read a stored result:

```sh
curl "$JOB_API_PUBLIC_BASE_URL/results/job-id"
```

Upload text for embedding:

```sh
curl -F file=@notes.txt \
  "$JOB_API_PUBLIC_BASE_URL/text"
```

Publish an embedding job from inline text:

```sh
curl -X POST "$JOB_API_PUBLIC_BASE_URL/jobs/embedding" \
  -H 'content-type: application/json' \
  -d '{"text":"text to embed","model":"nomic-embed-text"}'
```

Publish an embedding job from an uploaded text file:

```sh
curl -X POST "$JOB_API_PUBLIC_BASE_URL/jobs/embedding" \
  -H 'content-type: application/json' \
  -d '{"text_file":"notes.txt","model":"nomic-embed-text"}'
```

Upload video:

```sh
curl -F file=@input.mp4 \
  "$JOB_API_PUBLIC_BASE_URL/video"
```

Publish a video job for an uploaded file:

```sh
curl -X POST "$JOB_API_PUBLIC_BASE_URL/jobs/video" \
  -H 'content-type: application/json' \
  -d '{"video_file":"input.mp4","codec":"h264_nvenc","format":"mp4","scale":"1280:-2"}'
```

Routing:

```text
POST /jobs/whisper   -> exchange gpu.jobs, routing key whisper
POST /jobs/embedding -> exchange gpu.jobs, routing key embedding
POST /jobs/video     -> exchange gpu.jobs, routing key video
```

Result callbacks:

```text
application/json     whisper and embedding results
multipart/form-data  video results, for example metadata={...} and video=@output.mp4
```

API metrics are exposed at:

```text
<JOB_API_PUBLIC_BASE_URL>/metrics
```

Useful Prometheus queries:

```promql
gpu_job_api_jobs_published_total
gpu_job_api_results_received_total
gpu_job_api_audio_files
gpu_job_api_text_files
gpu_job_api_video_files
gpu_job_api_result_jobs
rabbitmq_queue_messages_ready{queue=~"gpu\\.(whisper|embeddings|video|dead)"}
rate(rabbitmq_queue_messages_delivered_total{queue=~"gpu\\.(whisper|embeddings|video)"}[5m])
```

## Prometheus Targets

Prometheus scrapes server-side services immediately:

- `rabbitmq:15692`
- `node-exporter:9100`

It also includes placeholders for the gaming PC:

- `gamingpc.local:9100`
- `gamingpc.local:9101`

Update `prometheus.yml` if the gaming PC uses a fixed LAN IP instead of local DNS.

## Alerts

Prometheus loads alert rules from `rules/gpu-worker-alerts.yml`. These rules appear in Prometheus immediately, but notifications require adding Alertmanager later.
