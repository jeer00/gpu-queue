# RabbitMQ Smoke Test

Tiny test client for the GPU RabbitMQ stack.

## Run on the homeserver

```sh
cd /home/homeserver/data/rabbitmq-gpu-stack/test-project
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python rabbitmq_smoke_test.py
```

## Run from the GPU PC

Copy or clone this `test-project` folder onto the GPU PC, then run:

```sh
cd test-project
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
AMQP_URL='<amqp-url-from-your-local-env>' .venv/bin/python rabbitmq_smoke_test.py
```

If `homeserver.local` does not resolve from the GPU PC, use the homeserver LAN IP:

```sh
AMQP_URL='<amqp-url-from-your-local-env>' .venv/bin/python rabbitmq_smoke_test.py
```

Expected output:

```text
published test job ... to gpu.jobs:whisper
consumed matching test job ... from gpu.whisper
```

## Publish a real Whisper worker job

The GPU worker expects `created_at` as a string and the Whisper input inside
`payload`. The `WHISPER_INPUT` path must exist on the GPU PC, not just on the
homeserver.

```sh
cd /home/homeserver/data/rabbitmq-gpu-stack/test-project
WHISPER_INPUT='/path/on/gpu-pc/audio.wav' \
WHISPER_OUTPUT='/path/on/gpu-pc/output.txt' \
.venv/bin/python publish_whisper_job.py
```

If publishing from the GPU PC:

```sh
AMQP_URL='<amqp-url-from-your-local-env>' \
WHISPER_INPUT='/path/on/gpu-pc/audio.wav' \
WHISPER_OUTPUT='/path/on/gpu-pc/output.txt' \
.venv/bin/python publish_whisper_job.py
```
