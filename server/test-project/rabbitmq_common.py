import os
from pathlib import Path


DEFAULT_AMQP_HOST = "localhost"
DEFAULT_AMQP_PORT = "5672"


def load_env_file(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")

    return values


def get_amqp_url() -> str:
    if "AMQP_URL" in os.environ:
        return os.environ["AMQP_URL"]

    env = load_env_file(Path(__file__).resolve().parents[1] / ".env")
    user = os.environ.get("RABBITMQ_DEFAULT_USER") or env.get("RABBITMQ_DEFAULT_USER", "gpuworker")
    password = os.environ.get("RABBITMQ_DEFAULT_PASS") or env.get("RABBITMQ_DEFAULT_PASS")
    host = os.environ.get("AMQP_HOST", DEFAULT_AMQP_HOST)
    port = os.environ.get("AMQP_PORT", DEFAULT_AMQP_PORT)

    if not password:
        raise RuntimeError("Set AMQP_URL or RABBITMQ_DEFAULT_PASS before running")

    return f"amqp://{user}:{password}@{host}:{port}/"
