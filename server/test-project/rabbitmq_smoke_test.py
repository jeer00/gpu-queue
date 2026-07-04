#!/usr/bin/env python3
import json
import os
import sys
import time
import uuid

import pika

from rabbitmq_common import get_amqp_url


def main() -> int:
    amqp_url = get_amqp_url()
    queue_name = os.environ.get("GPU_QUEUE", "gpu.test.smoke")
    routing_key = os.environ.get("GPU_ROUTING_KEY", "smoke-test")
    exchange = os.environ.get("GPU_EXCHANGE", "gpu.jobs")
    timeout_seconds = float(os.environ.get("TEST_TIMEOUT_SECONDS", "10"))

    test_id = str(uuid.uuid4())
    payload = {
        "id": test_id,
        "type": routing_key,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "payload": {
            "input": "rabbitmq smoke test",
        },
    }

    params = pika.URLParameters(amqp_url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange, exchange_type="direct", durable=True)
    channel.queue_declare(queue=queue_name, durable=True)
    channel.queue_bind(exchange=exchange, queue=queue_name, routing_key=routing_key)

    channel.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
        ),
    )
    print(f"published test job {test_id} to {exchange}:{routing_key}")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        method, properties, body = channel.basic_get(queue=queue_name, auto_ack=False)
        if method is None:
            time.sleep(0.25)
            continue

        message = json.loads(body.decode("utf-8"))
        if message.get("id") == test_id:
            channel.basic_ack(method.delivery_tag)
            print(f"consumed matching test job {test_id} from {queue_name}")
            connection.close()
            return 0

        channel.basic_nack(method.delivery_tag, requeue=True)
        print(f"saw unrelated message {message.get('id')}; left it in {queue_name}")
        time.sleep(0.25)

    connection.close()
    print(f"timed out waiting for test job {test_id} on {queue_name}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
