# GPU Worker on the Gaming PC

This folder is only for the gaming PC side of the homelab setup.

It provides:

- `cmd/gpu-worker`: RabbitMQ consumer for durable GPU jobs.
- Worker Prometheus metrics on `:9101/metrics`.
- NVIDIA metrics from `nvidia-smi` on the same metrics endpoint.
- systemd unit template for the worker.
- queue topology helper for `gpu.jobs`, `gpu.whisper`, `gpu.embeddings`, `gpu.video`, and `gpu.dead`.
- Job command scripts for Whisper, Ollama embeddings, and ffmpeg video jobs.

## Install on Arch

```sh
sudo pacman -S go prometheus-node-exporter
sudo systemctl enable --now prometheus-node-exporter

cd /home/jeppe/Documents/Kod/gpu-worker
mkdir -p bin
go build -buildvcs=false -o bin/gpu-worker ./cmd/gpu-worker
go build -buildvcs=false -o bin/publish-test-job ./cmd/publish-test-job
```

## Configure

Copy the env file:

```sh
cp .env.example .env
```

Edit:

```env
RABBITMQ_URL=<set-this-in-your-local-env>
GPU_WORKER_QUEUE=gpu.whisper
GPU_WORKER_COMMAND_ENABLED=false
GPU_WORKER_COMMAND=
```

The worker starts in dry-run mode. It consumes jobs, acknowledges them, and updates metrics without running local GPU commands.

When ready, set:

```env
GPU_WORKER_COMMAND_ENABLED=true
GPU_WORKER_COMMAND=/path/to/your/gpu-command
```

The command receives:

- `GPU_JOB_ID`
- `GPU_JOB_TYPE`
- `GPU_JOB_PAYLOAD`
- `GPU_JOB_ROUTING_KEY`

## Run Manually

```sh
set -a
. ./.env
set +a
./bin/gpu-worker
```

Metrics:

```sh
curl http://localhost:9101/metrics
```

## Install systemd Service

This keeps everything in the workspace folder and points systemd at it.

```sh
sudo cp systemd/gpu-worker.service /etc/systemd/system/gpu-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-worker.service
```

Logs:

```sh
journalctl -u gpu-worker.service -f
```

## Additional Workers

The worker process consumes one queue and runs one command. Run separate
services for each job type:

```sh
cp .env.embeddings.example .env.embeddings
cp .env.video.example .env.video
```

Edit both files so `RABBITMQ_URL` matches `.env`, then install:

```sh
sudo cp systemd/gpu-worker-embeddings.service /etc/systemd/system/gpu-worker-embeddings.service
sudo cp systemd/gpu-worker-video.service /etc/systemd/system/gpu-worker-video.service
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-worker-embeddings.service
sudo systemctl enable --now gpu-worker-video.service
```

Embedding jobs use Ollama's `/api/embed` endpoint. Install an embedding model
first, for example:

```sh
ollama pull nomic-embed-text
```

## URL Job Payloads

Whisper:

```json
{
  "id": "job-id",
  "type": "whisper",
  "payload": {
    "input_url": "http://homeserver.local:8081/audio/file.wav",
    "result_url": "http://homeserver.local:8081/results/job-id",
    "language": "auto"
  }
}
```

Embeddings:

```json
{
  "id": "job-id",
  "type": "embedding",
  "payload": {
    "text": "text to embed",
    "result_url": "http://homeserver.local:8081/results/job-id",
    "model": "nomic-embed-text"
  }
}
```

Video:

```json
{
  "id": "job-id",
  "type": "video",
  "payload": {
    "input_url": "http://homeserver.local:8081/video/input.mp4",
    "result_url": "http://homeserver.local:8081/results/job-id",
    "codec": "h264_nvenc",
    "format": "mp4",
    "scale": "1280:-2"
  }
}
```

Whisper and embeddings POST JSON results. Video POSTs multipart form data with
`metadata` and `video` parts.

## Publish a Test Job

From any machine that can reach RabbitMQ:

```sh
set -a
. ./.env
set +a
GPU_JOB_ROUTE=whisper \
GPU_JOB_PAYLOAD='{"input":"test.wav"}' \
./bin/publish-test-job
```

## Prometheus Target

On the homeserver Prometheus config, scrape this gaming PC:

```yaml
  - job_name: "gpu-worker"
    static_configs:
      - targets:
          - "gamingpc.local:9101"

  - job_name: "gaming-pc-node"
    static_configs:
      - targets:
          - "gamingpc.local:9100"
```

## Job Format

Messages should be JSON:

```json
{
  "id": "unique-job-id",
  "type": "whisper",
  "payload": {
    "input": "path-or-url",
    "output": "path-or-url"
  }
}
```

Failed command executions are rejected without requeue, so RabbitMQ dead-letters them to `gpu.dead`.
