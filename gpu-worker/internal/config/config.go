package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	RabbitMQURL       string
	Queue             string
	ConsumerTag       string
	MetricsAddr       string
	CommandEnabled    bool
	Command           string
	JobTimeout        time.Duration
	GamingProcesses   []string
	BlockWhenGaming   bool
	BlockWhenGPUBusy  bool
	GPUBusyThreshold  float64
	BlockRequeueDelay time.Duration
}

func Load() Config {
	return Config{
		RabbitMQURL:       env("RABBITMQ_URL", ""),
		Queue:             env("GPU_WORKER_QUEUE", "gpu.whisper"),
		ConsumerTag:       env("GPU_WORKER_CONSUMER_TAG", "gamingpc-gpu-worker"),
		MetricsAddr:       env("GPU_WORKER_METRICS_ADDR", ":9101"),
		CommandEnabled:    envBool("GPU_WORKER_COMMAND_ENABLED", false),
		Command:           env("GPU_WORKER_COMMAND", ""),
		JobTimeout:        time.Duration(envInt("GPU_WORKER_JOB_TIMEOUT_SECONDS", 0)) * time.Second,
		GamingProcesses:   envList("GPU_WORKER_GAMING_PROCESSES", []string{"steam", "steamwebhelper"}),
		BlockWhenGaming:   envBool("GPU_WORKER_BLOCK_WHEN_GAMING", true),
		BlockWhenGPUBusy:  envBool("GPU_WORKER_BLOCK_WHEN_GPU_BUSY", true),
		GPUBusyThreshold:  envFloat("GPU_WORKER_GPU_BUSY_THRESHOLD_PERCENT", 85),
		BlockRequeueDelay: time.Duration(envInt("GPU_WORKER_BLOCK_REQUEUE_DELAY_SECONDS", 30)) * time.Second,
	}
}

func env(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func envBool(key string, fallback bool) bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv(key)))
	if value == "" {
		return fallback
	}
	return value == "1" || value == "true" || value == "yes" || value == "on"
}

func envInt(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func envFloat(key string, fallback float64) float64 {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseFloat(value, 64)
	if err != nil {
		return fallback
	}
	return parsed
}

func envList(key string, fallback []string) []string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parts := strings.Split(value, ",")
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}
