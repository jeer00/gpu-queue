package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log"
	"os"
	"time"

	"gpu-worker/internal/rabbitmq"

	amqp "github.com/rabbitmq/amqp091-go"
)

type Job struct {
	ID        string          `json:"id"`
	Type      string          `json:"type"`
	Payload   json.RawMessage `json:"payload"`
	CreatedAt string          `json:"created_at"`
}

func main() {
	url := os.Getenv("RABBITMQ_URL")
	if url == "" {
		log.Fatal("RABBITMQ_URL is required")
	}
	route := getenv("GPU_JOB_ROUTE", "whisper")
	payload := json.RawMessage(getenv("GPU_JOB_PAYLOAD", "{}"))

	conn, err := amqp.Dial(url)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	ch, err := conn.Channel()
	if err != nil {
		log.Fatal(err)
	}
	defer ch.Close()

	if err := rabbitmq.DeclareTopology(ch); err != nil {
		log.Fatal(err)
	}

	job := Job{
		ID:        newID(),
		Type:      route,
		Payload:   payload,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	body, err := json.Marshal(job)
	if err != nil {
		log.Fatal(err)
	}

	if err := ch.PublishWithContext(context.Background(), rabbitmq.ExchangeName, route, false, false, amqp.Publishing{
		ContentType:  "application/json",
		DeliveryMode: amqp.Persistent,
		MessageId:    job.ID,
		Timestamp:    time.Now().UTC(),
		Type:         route,
		Body:         body,
	}); err != nil {
		log.Fatal(err)
	}

	log.Printf("published job id=%s route=%s", job.ID, route)
}

func getenv(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func newID() string {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return time.Now().UTC().Format("20060102150405.000000000")
	}
	return hex.EncodeToString(bytes[:])
}
