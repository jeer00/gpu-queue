#!/usr/bin/env python3
import json
import os
from datetime import datetime
import uuid

import pika

from rabbitmq_common import get_amqp_url


def main() -> int:
    input_path = os.environ.get("WHISPER_INPUT")
    if not input_path:
        raise RuntimeError("Set WHISPER_INPUT to an audio path that exists on the GPU PC")

    output_path = os.environ.get("WHISPER_OUTPUT", f"{input_path}.txt")
    language = os.environ.get("WHISPER_LANGUAGE", "auto")
    exchange = os.environ.get("GPU_EXCHANGE", "gpu.jobs")
    routing_key = "whisper"
    job_id = os.environ.get("JOB_ID", str(uuid.uuid4()))

    job = {
        "id": job_id,
        "type": "whisper",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "payload": {
            "input": input_path,
            "output": output_path,
            "language": language,
        },
    }

    connection = pika.BlockingConnection(pika.URLParameters(get_amqp_url()))
    channel = connection.channel()
    channel.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=json.dumps(job).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
        ),
    )
    connection.close()

    print(f"published whisper job {job_id}")
    print(f"input: {input_path}")
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
