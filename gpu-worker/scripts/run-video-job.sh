#!/usr/bin/env bash
set -euo pipefail

PAYLOAD=${GPU_JOB_PAYLOAD:-}
if [[ -z "$PAYLOAD" ]]; then
  PAYLOAD='{}'
fi

WORK_DIR=${GPU_WORKER_JOB_DIR:-/home/jeppe/Documents/Kod/gpu-worker/jobs}
HOMESERVER_IP=${HOMESERVER_IP:-}

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

input=$(jq -r '.input // empty' <<<"$PAYLOAD")
input_url=$(jq -r '.input_url // empty' <<<"$PAYLOAD")
result_url=$(jq -r '.result_url // .output_url // empty' <<<"$PAYLOAD")
codec=$(jq -r '.codec // "h264_nvenc"' <<<"$PAYLOAD")
preset=$(jq -r '.preset // "p4"' <<<"$PAYLOAD")
cq=$(jq -r '.cq // "23"' <<<"$PAYLOAD")
format=$(jq -r '.format // "mp4"' <<<"$PAYLOAD")
scale=$(jq -r '.scale // empty' <<<"$PAYLOAD")

if [[ -z "$input" && -z "$input_url" ]]; then
  echo "missing required payload field: input or input_url" >&2
  exit 64
fi

mkdir -p "$WORK_DIR" "$WORK_DIR/output"

if [[ -n "$input_url" ]]; then
  extension="${input_url%%\?*}"
  extension="${extension##*.}"
  if [[ "$extension" == "$input_url" || ${#extension} -gt 8 ]]; then
    extension="input"
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

output="$WORK_DIR/output/${GPU_JOB_ID:-job}.${format}"
start_ns=$(date +%s%N)

ffmpeg_args=(-hide_banner -y -i "$input")
if [[ -n "$scale" ]]; then
  ffmpeg_args+=(-vf "scale=${scale}")
fi
ffmpeg_args+=(
  -c:v "$codec"
  -preset "$preset"
  -cq "$cq"
  -c:a aac
  -movflags +faststart
  "$output"
)

ffmpeg "${ffmpeg_args[@]}"

end_ns=$(date +%s%N)
duration_seconds=$(awk "BEGIN { printf \"%.2f\", ($end_ns - $start_ns) / 1000000000 }")
bytes=$(stat -c '%s' "$output")

metadata=$(
  jq -n \
    --arg id "${GPU_JOB_ID:-}" \
    --arg type "${GPU_JOB_TYPE:-video}" \
    --arg status "completed" \
    --arg codec "$codec" \
    --arg format "$format" \
    --argjson bytes "$bytes" \
    --argjson duration_seconds "$duration_seconds" \
    '{
      id: $id,
      type: $type,
      status: $status,
      codec: $codec,
      format: $format,
      bytes: $bytes,
      duration_seconds: $duration_seconds
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
    --form "metadata=$metadata;type=application/json" \
    --form "video=@${output}" \
    "$result_url"
else
  jq . <<<"$metadata"
fi
