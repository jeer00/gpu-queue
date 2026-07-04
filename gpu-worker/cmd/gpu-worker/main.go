package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"gpu-worker/internal/config"
	"gpu-worker/internal/metrics"
	"gpu-worker/internal/worker"
)

func main() {
	cfg := config.Load()
	if cfg.RabbitMQURL == "" {
		log.Fatal("RABBITMQ_URL is required")
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	m := &metrics.Metrics{}
	go func() {
		log.Printf("metrics listening on %s", cfg.MetricsAddr)
		if err := m.Serve(cfg.MetricsAddr); err != nil {
			log.Fatalf("metrics server failed: %v", err)
		}
	}()

	if err := worker.Run(ctx, cfg, m); err != nil && ctx.Err() == nil {
		log.Fatal(err)
	}
}
