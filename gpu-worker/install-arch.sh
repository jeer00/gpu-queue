#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

sudo pacman -S --needed go prometheus-node-exporter
mkdir -p bin
go build -buildvcs=false -o bin/gpu-worker ./cmd/gpu-worker
go build -buildvcs=false -o bin/publish-test-job ./cmd/publish-test-job

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

sudo systemctl enable --now prometheus-node-exporter

echo "Edit $(pwd)/.env, then run:"
echo "  sudo cp $(pwd)/systemd/gpu-worker.service /etc/systemd/system/gpu-worker.service"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now gpu-worker.service"
