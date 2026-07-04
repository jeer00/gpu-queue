# RabbitMQ GPU Stack

This repo contains the two sides of the RabbitMQ GPU job setup:

- `gpu-worker/`: GPU PC workers for Whisper, embeddings, and video jobs.
- `server/`: homeserver RabbitMQ/API stack.

Live credentials, IP addresses, passwords, keys, uploaded media, generated
results, and local `.env` files should stay out of git. Commit only
`.env.example` files with placeholders.

## Import Server Files

From a terminal where `ssh homeserver` works:

```sh
cd /home/jeppe/Documents/Kod/rabbitmq-gpu-stack
rsync -a --delete \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude 'audio/' \
  --exclude 'text/' \
  --exclude 'video/' \
  --exclude 'results/' \
  --exclude 'data/' \
  --exclude 'storage/' \
  homeserver:/home/homeserver/data/rabbitmq-gpu-stack/ \
  server/
```

After importing, run:

```sh
git status --short
rg -n "(password|secret|token|key|amqp://|[0-9]{1,3}(\\.[0-9]{1,3}){3})" -S .
```

Review any matches before committing.
