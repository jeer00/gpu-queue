#!/usr/bin/env bash
set -euo pipefail

PAYLOAD=${GPU_JOB_PAYLOAD:-}
if [[ -z "$PAYLOAD" ]]; then
  PAYLOAD='{}'
fi

WORK_DIR=${GPU_WORKER_JOB_DIR:-/home/jeppe/Documents/Kod/gpu-worker/jobs}
HOMESERVER_IP=${HOMESERVER_IP:-}
OLLAMA_URL=${OLLAMA_URL:-http://localhost:11434}
DEFAULT_MODEL=${OLLAMA_EMBED_MODEL:-nomic-embed-text}

add_homeserver_resolve() {
  local url=$1
  if [[ -z "$HOMESERVER_IP" ]]; then
    return 0
  fi
  if [[ "$url" =~ ^http://homeserver\.local(:([0-9]+))?/ ]]; then
    echo "--resolve=homeserver.local:${BASH_REMATCH[2]:-80}:$HOMESERVER_IP"
  elif [[ "$url" =~ ^https://homeserver\.local(:([0-9]+))?/ ]]; then
    echo "--resolve=homeserver.local:${BASH_REMATCH[2]:-443}:$HOMESERVER_IP"
  fi
}

model=$(jq -r --arg fallback "$DEFAULT_MODEL" '.model // $fallback' <<<"$PAYLOAD")
has_inline_text=$(jq -r 'has("text") or has("input")' <<<"$PAYLOAD")
input_url=$(jq -r '.input_url // empty' <<<"$PAYLOAD")
result_url=$(jq -r '.result_url // .output_url // empty' <<<"$PAYLOAD")

if [[ "$has_inline_text" != "true" && -z "$input_url" ]]; then
  echo "missing required payload field: text, input, or input_url" >&2
  exit 64
fi

mkdir -p "$WORK_DIR"
input_file="$WORK_DIR/${GPU_JOB_ID:-job}.embedding-input"
payload_file="$WORK_DIR/${GPU_JOB_ID:-job}.embedding-payload.json"

if [[ -n "$input_url" ]]; then
  curl_args=(--fail --location --show-error --silent)
  resolve_arg=$(add_homeserver_resolve "$input_url")
  if [[ -n "$resolve_arg" ]]; then
    curl_args+=("$resolve_arg")
  fi
  curl "${curl_args[@]}" --output "$input_file" "$input_url"
else
  jq -r '.text // .input' <<<"$PAYLOAD" > "$input_file"
fi

jq -n \
  --arg model "$model" \
  --rawfile input "$input_file" \
  '{model: $model, input: $input}' \
  > "$payload_file"

start_ns=$(date +%s%N)
response=$(
  curl --fail --show-error --silent \
    --request POST \
    --header "content-type: application/json" \
    --data-binary @"$payload_file" \
    "$OLLAMA_URL/api/embed"
)
end_ns=$(date +%s%N)
duration_seconds=$(awk "BEGIN { printf \"%.2f\", ($end_ns - $start_ns) / 1000000000 }")

result=$(
  jq -n \
    --arg id "${GPU_JOB_ID:-}" \
    --arg type "${GPU_JOB_TYPE:-embedding}" \
    --arg status "completed" \
    --arg model "$model" \
    --argjson duration_seconds "$duration_seconds" \
    --argjson ollama "$response" \
    '{
      id: $id,
      type: $type,
      status: $status,
      model: $model,
      duration_seconds: $duration_seconds,
      embeddings: $ollama.embeddings,
      embedding: ($ollama.embedding // null)
    }'
)

if [[ -n "$result_url" ]]; then
  post_args=(--fail --location --show-error --silent)
  resolve_arg=$(add_homeserver_resolve "$result_url")
  if [[ -n "$resolve_arg" ]]; then
    post_args+=("$resolve_arg")
  fi
  curl "${post_args[@]}" \
    --request POST \
    --header "content-type: application/json" \
    --data-binary "$result" \
    "$result_url"
else
  jq . <<<"$result"
fi
