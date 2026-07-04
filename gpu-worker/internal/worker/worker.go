package worker

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"
	"time"

	"gpu-worker/internal/config"
	"gpu-worker/internal/metrics"
	"gpu-worker/internal/rabbitmq"

	amqp "github.com/rabbitmq/amqp091-go"
)

type Job struct {
	ID        string          `json:"id"`
	Type      string          `json:"type"`
	Payload   json.RawMessage `json:"payload,omitempty"`
	CreatedAt json.RawMessage `json:"created_at,omitempty"`
}

func Run(ctx context.Context, cfg config.Config, m *metrics.Metrics) error {
	for {
		if err := connectAndConsume(ctx, cfg, m); err != nil {
			select {
			case <-ctx.Done():
				return ctx.Err()
			default:
				log.Printf("rabbitmq worker stopped: %v; reconnecting in 5s", err)
				time.Sleep(5 * time.Second)
			}
		}
	}
}

func connectAndConsume(ctx context.Context, cfg config.Config, m *metrics.Metrics) error {
	conn, err := amqp.Dial(cfg.RabbitMQURL)
	if err != nil {
		return err
	}
	defer conn.Close()

	ch, err := conn.Channel()
	if err != nil {
		return err
	}
	defer ch.Close()

	if err := rabbitmq.DeclareTopology(ch); err != nil {
		return err
	}
	if err := ch.Qos(1, 0, false); err != nil {
		return err
	}

	deliveries, err := ch.Consume(cfg.Queue, cfg.ConsumerTag, false, false, false, false, nil)
	if err != nil {
		return err
	}

	log.Printf("consuming queue=%s command_enabled=%t", cfg.Queue, cfg.CommandEnabled)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case delivery, ok := <-deliveries:
			if !ok {
				return fmt.Errorf("deliveries channel closed")
			}
			handleDelivery(ctx, cfg, m, delivery)
		}
	}
}

func handleDelivery(ctx context.Context, cfg config.Config, m *metrics.Metrics, delivery amqp.Delivery) {
	m.ClaimAttempt()

	if reason := shouldDelay(cfg, m); reason != "" {
		log.Printf("delaying job: %s; requeueing in %s", reason, cfg.BlockRequeueDelay)
		if err := delivery.Nack(false, true); err != nil {
			log.Printf("failed to requeue delivery: %v", err)
		}
		time.Sleep(cfg.BlockRequeueDelay)
		return
	}

	start := time.Now()
	m.StartJob()

	var job Job
	if err := json.Unmarshal(delivery.Body, &job); err != nil {
		m.FailJob(time.Since(start))
		log.Printf("invalid job json: %v", err)
		_ = delivery.Nack(false, false)
		return
	}
	if job.ID == "" {
		job.ID = delivery.MessageId
	}
	if job.Type == "" {
		job.Type = delivery.RoutingKey
	}

	log.Printf("starting job id=%s type=%s route=%s", job.ID, job.Type, delivery.RoutingKey)
	if err := runJobCommand(ctx, cfg, job, delivery.RoutingKey); err != nil {
		m.FailJob(time.Since(start))
		log.Printf("failed job id=%s: %v", job.ID, err)
		_ = delivery.Nack(false, false)
		return
	}

	m.FinishJob(time.Since(start))
	if err := delivery.Ack(false); err != nil {
		log.Printf("failed to ack job id=%s: %v", job.ID, err)
	}
	log.Printf("completed job id=%s duration=%s", job.ID, time.Since(start).Round(time.Millisecond))
}

func runJobCommand(ctx context.Context, cfg config.Config, job Job, routingKey string) error {
	if !cfg.CommandEnabled {
		log.Printf("dry-run complete id=%s", job.ID)
		return nil
	}
	if strings.TrimSpace(cfg.Command) == "" {
		return fmt.Errorf("GPU_WORKER_COMMAND_ENABLED=true but GPU_WORKER_COMMAND is empty")
	}

	commandCtx := ctx
	cancel := func() {}
	if cfg.JobTimeout > 0 {
		commandCtx, cancel = context.WithTimeout(ctx, cfg.JobTimeout)
	}
	defer cancel()

	cmd := exec.CommandContext(commandCtx, "/bin/sh", "-lc", cfg.Command)
	cmd.Env = append(os.Environ(),
		"GPU_JOB_ID="+job.ID,
		"GPU_JOB_TYPE="+job.Type,
		"GPU_JOB_PAYLOAD="+string(job.Payload),
		"GPU_JOB_ROUTING_KEY="+routingKey,
	)
	output, err := cmd.CombinedOutput()
	if len(output) > 0 {
		log.Printf("job output id=%s:\n%s", job.ID, strings.TrimSpace(string(output)))
	}
	return err
}

func shouldDelay(cfg config.Config, m *metrics.Metrics) string {
	if cfg.BlockWhenGaming && len(cfg.GamingProcesses) > 0 && gamingProcessRunning(cfg.GamingProcesses) {
		m.BlockedByGaming()
		return "gaming process is running"
	}

	if cfg.BlockWhenGPUBusy {
		utilization, ok := gpuUtilization()
		if ok && utilization >= cfg.GPUBusyThreshold {
			m.BlockedByGPUBusy()
			return fmt.Sprintf("GPU utilization %.0f%% >= %.0f%%", utilization, cfg.GPUBusyThreshold)
		}
	}

	return ""
}

func gamingProcessRunning(names []string) bool {
	args := append([]string{"-x"}, strings.Join(names, ","))
	err := exec.Command("pgrep", args...).Run()
	return err == nil
}

func gpuUtilization() (float64, bool) {
	out, err := exec.Command(
		"nvidia-smi",
		"--query-gpu=utilization.gpu",
		"--format=csv,noheader,nounits",
	).Output()
	if err != nil {
		return 0, false
	}

	maxUtil := 0.0
	found := false
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		value := strings.TrimSpace(line)
		if value == "" {
			continue
		}
		var parsed float64
		if _, err := fmt.Sscanf(value, "%f", &parsed); err != nil {
			continue
		}
		if parsed > maxUtil {
			maxUtil = parsed
		}
		found = true
	}
	return maxUtil, found
}
