package rabbitmq

import amqp "github.com/rabbitmq/amqp091-go"

const (
	ExchangeName   = "gpu.jobs"
	DeadExchange   = "gpu.dead"
	DeadQueueName  = "gpu.dead"
	WhisperQueue   = "gpu.whisper"
	EmbeddingQueue = "gpu.embeddings"
	VideoQueue     = "gpu.video"
)

var QueueBindings = map[string]string{
	WhisperQueue:   "whisper",
	EmbeddingQueue: "embedding",
	VideoQueue:     "video",
}

func DeclareTopology(ch *amqp.Channel) error {
	if err := ch.ExchangeDeclare(ExchangeName, "direct", true, false, false, false, nil); err != nil {
		return err
	}
	if err := ch.ExchangeDeclare(DeadExchange, "direct", true, false, false, false, nil); err != nil {
		return err
	}
	if _, err := ch.QueueDeclare(DeadQueueName, true, false, false, false, nil); err != nil {
		return err
	}
	if err := ch.QueueBind(DeadQueueName, DeadQueueName, DeadExchange, false, nil); err != nil {
		return err
	}

	for queue, routingKey := range QueueBindings {
		if _, err := ch.QueueDeclare(queue, true, false, false, false, amqp.Table{
			"x-dead-letter-exchange":    DeadExchange,
			"x-dead-letter-routing-key": DeadQueueName,
		}); err != nil {
			return err
		}
		if err := ch.QueueBind(queue, routingKey, ExchangeName, false, nil); err != nil {
			return err
		}
	}

	return nil
}
