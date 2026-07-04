package metrics

import (
	"fmt"
	"net/http"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

type Metrics struct {
	mu               sync.RWMutex
	jobsStarted      uint64
	jobsCompleted    uint64
	jobsFailed       uint64
	currentJob       uint64
	lastJobDuration  float64
	blockedByGaming  uint64
	blockedByGPUBusy uint64
	claimAttempts    uint64
}

func (m *Metrics) ClaimAttempt() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.claimAttempts++
}

func (m *Metrics) StartJob() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.jobsStarted++
	m.currentJob = 1
}

func (m *Metrics) FinishJob(duration time.Duration) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.jobsCompleted++
	m.currentJob = 0
	m.lastJobDuration = duration.Seconds()
}

func (m *Metrics) FailJob(duration time.Duration) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.jobsFailed++
	m.currentJob = 0
	m.lastJobDuration = duration.Seconds()
}

func (m *Metrics) BlockedByGaming() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.blockedByGaming++
}

func (m *Metrics) BlockedByGPUBusy() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.blockedByGPUBusy++
}

func (m *Metrics) Serve(addr string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprint(w, m.Render())
	})
	return http.ListenAndServe(addr, mux)
}

func (m *Metrics) Render() string {
	m.mu.RLock()
	body := fmt.Sprintf(`# HELP gpu_worker_jobs_started_total GPU worker jobs started.
# TYPE gpu_worker_jobs_started_total counter
gpu_worker_jobs_started_total %d
# HELP gpu_worker_jobs_completed_total GPU worker jobs completed.
# TYPE gpu_worker_jobs_completed_total counter
gpu_worker_jobs_completed_total %d
# HELP gpu_worker_jobs_failed_total GPU worker jobs failed.
# TYPE gpu_worker_jobs_failed_total counter
gpu_worker_jobs_failed_total %d
# HELP gpu_worker_current_job Whether the GPU worker is currently running a job.
# TYPE gpu_worker_current_job gauge
gpu_worker_current_job %d
# HELP gpu_worker_last_job_duration_seconds Last GPU job duration in seconds.
# TYPE gpu_worker_last_job_duration_seconds gauge
gpu_worker_last_job_duration_seconds %.6f
# HELP gpu_worker_idle_blocked_by_gaming_total Times work was delayed because gaming processes were running.
# TYPE gpu_worker_idle_blocked_by_gaming_total counter
gpu_worker_idle_blocked_by_gaming_total %d
# HELP gpu_worker_idle_blocked_by_gpu_busy_total Times work was delayed because GPU utilization was high.
# TYPE gpu_worker_idle_blocked_by_gpu_busy_total counter
gpu_worker_idle_blocked_by_gpu_busy_total %d
# HELP gpu_worker_queue_claim_attempts_total RabbitMQ delivery claim attempts.
# TYPE gpu_worker_queue_claim_attempts_total counter
gpu_worker_queue_claim_attempts_total %d
`, m.jobsStarted, m.jobsCompleted, m.jobsFailed, m.currentJob, m.lastJobDuration, m.blockedByGaming, m.blockedByGPUBusy, m.claimAttempts)
	m.mu.RUnlock()

	return body + RenderNvidia()
}

func RenderNvidia() string {
	out, err := exec.Command(
		"nvidia-smi",
		"--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
		"--format=csv,noheader,nounits",
	).Output()
	if err != nil {
		return `# HELP nvidia_gpu_metrics_available Whether nvidia-smi metrics are available.
# TYPE nvidia_gpu_metrics_available gauge
nvidia_gpu_metrics_available 0
`
	}

	var b strings.Builder
	b.WriteString(`# HELP nvidia_gpu_metrics_available Whether nvidia-smi metrics are available.
# TYPE nvidia_gpu_metrics_available gauge
nvidia_gpu_metrics_available 1
# HELP nvidia_gpu_utilization_percent GPU utilization percent.
# TYPE nvidia_gpu_utilization_percent gauge
# HELP nvidia_gpu_memory_utilization_percent GPU memory utilization percent.
# TYPE nvidia_gpu_memory_utilization_percent gauge
# HELP nvidia_gpu_memory_used_mib GPU memory used MiB.
# TYPE nvidia_gpu_memory_used_mib gauge
# HELP nvidia_gpu_memory_total_mib GPU memory total MiB.
# TYPE nvidia_gpu_memory_total_mib gauge
# HELP nvidia_gpu_temperature_celsius GPU temperature Celsius.
# TYPE nvidia_gpu_temperature_celsius gauge
# HELP nvidia_gpu_power_draw_watts GPU power draw watts.
# TYPE nvidia_gpu_power_draw_watts gauge
# HELP nvidia_gpu_power_limit_watts GPU power limit watts.
# TYPE nvidia_gpu_power_limit_watts gauge
`)

	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	for i, line := range lines {
		values := strings.Split(line, ",")
		if len(values) != 7 {
			continue
		}
		for j := range values {
			values[j] = strings.TrimSpace(values[j])
			if _, err := strconv.ParseFloat(values[j], 64); err != nil {
				values[j] = "0"
			}
		}
		label := fmt.Sprintf(`{gpu="%d"}`, i)
		fmt.Fprintf(&b, "nvidia_gpu_utilization_percent%s %s\n", label, values[0])
		fmt.Fprintf(&b, "nvidia_gpu_memory_utilization_percent%s %s\n", label, values[1])
		fmt.Fprintf(&b, "nvidia_gpu_memory_used_mib%s %s\n", label, values[2])
		fmt.Fprintf(&b, "nvidia_gpu_memory_total_mib%s %s\n", label, values[3])
		fmt.Fprintf(&b, "nvidia_gpu_temperature_celsius%s %s\n", label, values[4])
		fmt.Fprintf(&b, "nvidia_gpu_power_draw_watts%s %s\n", label, values[5])
		fmt.Fprintf(&b, "nvidia_gpu_power_limit_watts%s %s\n", label, values[6])
	}
	return b.String()
}
