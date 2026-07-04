#!/usr/bin/env bash
set -euo pipefail

MODEL=${WHISPER_MODEL:-/usr/share/whisper.cpp-model-large-v3-turbo-q5_0/ggml-large-v3-turbo-q5_0.bin}
PAYLOAD=${GPU_JOB_PAYLOAD:-}
if [[ -z "$PAYLOAD" ]]; then
  PAYLOAD='{}'
fi
WORK_DIR=${GPU_WORKER_JOB_DIR:-/home/jeppe/Documents/Kod/gpu-worker/jobs}
HOMESERVER_IP=${HOMESERVER_IP:-}
export LD_LIBRARY_PATH="/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

input=$(jq -r '.input // empty' <<<"$PAYLOAD")
input_url=$(jq -r '.input_url // empty' <<<"$PAYLOAD")
output=$(jq -r '.output // empty' <<<"$PAYLOAD")
result_url=$(jq -r '.result_url // .output_url // empty' <<<"$PAYLOAD")
language=$(jq -r '.language // "auto"' <<<"$PAYLOAD")

if [[ -z "$input" && -z "$input_url" ]]; then
  echo "missing required payload field: input or input_url" >&2
  exit 64
fi

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

if [[ -n "$input_url" ]]; then
  mkdir -p "$WORK_DIR"
  extension="${input_url%%\?*}"
  extension="${extension##*.}"
  if [[ "$extension" == "$input_url" || ${#extension} -gt 8 ]]; then
    extension="wav"
  fi
  input="$WORK_DIR/${GPU_JOB_ID:-job}.$extension"

  curl_args=(--fail --location --show-error --silent)
  resolve_arg=$(add_homeserver_resolve "$input_url")
  if [[ -n "$resolve_arg" ]]; then
    curl_args+=("$resolve_arg")
  fi

  curl "${curl_args[@]}" --output "$input" "$input_url"
fi

if [[ ! -f "$input" ]]; then
  echo "input file does not exist: $input" >&2
  exit 66
fi

format="-otxt"
if [[ -z "$output" ]]; then
  if [[ -n "$input_url" ]]; then
    mkdir -p "$WORK_DIR/output"
    output="$WORK_DIR/output/${GPU_JOB_ID:-job}"
  else
    output="${input%.*}"
  fi
else
  case "$output" in
    *.json)
      format="-oj"
      output="${output%.json}"
      ;;
    *.srt)
      format="-osrt"
      output="${output%.srt}"
      ;;
    *.vtt)
      format="-ovtt"
      output="${output%.vtt}"
      ;;
    *.txt)
      format="-otxt"
      output="${output%.txt}"
      ;;
  esac
fi

mkdir -p "$(dirname "$output")"

start_ns=$(date +%s%N)

whisper-cli \
  --model "$MODEL" \
  --file "$input" \
  --language "$language" \
  "$format" \
  --output-file "$output"

end_ns=$(date +%s%N)
duration_seconds=$(awk "BEGIN { printf \"%.2f\", ($end_ns - $start_ns) / 1000000000 }")

if [[ -n "$result_url" ]]; then
  transcript="${output}.txt"
  if [[ ! -f "$transcript" ]]; then
    echo "expected transcript file does not exist: $transcript" >&2
    exit 70
  fi

  post_args=(--fail --location --show-error --silent)
  resolve_arg=$(add_homeserver_resolve "$result_url")
  if [[ -n "$resolve_arg" ]]; then
    post_args+=("$resolve_arg")
  fi

  jq -n \
    --arg id "${GPU_JOB_ID:-}" \
    --arg type "${GPU_JOB_TYPE:-whisper}" \
    --arg status "completed" \
    --rawfile text "$transcript" \
    --arg language "$language" \
    --argjson duration_seconds "$duration_seconds" \
    '{
      id: $id,
      type: $type,
      status: $status,
      text: $text,
      language: $language,
      duration_seconds: $duration_seconds
    }' |
    curl "${post_args[@]}" \
      --request POST \
      --header "content-type: application/json" \
      --data-binary @- \
      "$result_url"
fi
