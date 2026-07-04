# RabbitMQ GPU Stack

This repo contains the two sides of the RabbitMQ GPU job setup:

- `gpu-worker/`: GPU PC workers for Whisper, embeddings, and video jobs.
- `server/`: homeserver RabbitMQ/API stack.

Live credentials, IP addresses, passwords, keys, uploaded media, generated
results, and local `.env` files should stay out of git. Commit only
`.env.example` files with placeholders.

Use the `.env.example` files as templates for local configuration.
