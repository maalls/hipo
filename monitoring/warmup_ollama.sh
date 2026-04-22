#!/bin/bash
# Warmup script: load Ollama models sequentially to avoid GPU discovery timeout
# Call this after ollama-gpu services start to initialize models one by one

set -e

MODEL="qwen2.5:latest"
MAPPING_FILE="${MAPPING_FILE:-/tmp/ollama_gpu_mapping.json}"
WARMUP_PROMPT="Hello, how are you?"
TIMEOUT=120

if [ -f "$MAPPING_FILE" ]; then
  mapfile -t PORTS < <(python3 - "$MAPPING_FILE" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

ports = sorted(int(p) for p in data.keys())
for p in ports:
    print(p)
PY
  )
else
  PORTS=(11434 11435 11436 11437)
fi

if [ "${#PORTS[@]}" -eq 0 ]; then
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: No ports found for warmup"
  exit 1
fi

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting Ollama model warmup (sequential)"

for port in "${PORTS[@]}"; do
  base_url="http://127.0.0.1:$port"
  
  # Wait for Ollama to be ready on this port (max 30s)
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Waiting for port $port to be ready..."
  for i in $(seq 1 30); do
    if curl -sS -m 2 "$base_url/api/tags" >/dev/null 2>&1; then
      echo "[$(date +'%Y-%m-%d %H:%M:%S')] Port $port is ready"
      break
    fi
    if [ $i -eq 30 ]; then
      echo "[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: Port $port not ready after 30s, skipping"
      continue 2
    fi
    sleep 1
  done
  
  # Check if model is already loaded
  if curl -sS "$base_url/api/tags" | grep -q "\"name\":\"$MODEL\""; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] Model $MODEL already loaded on port $port"
    continue
  fi
  
  # Load the model via a short generate request
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Loading model $MODEL on port $port..."
  if timeout $TIMEOUT curl -sS -X POST \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"$WARMUP_PROMPT\",\"stream\":false}" \
    "$base_url/api/generate" >/dev/null 2>&1; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] Model loaded successfully on port $port"
  else
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: Failed to load model on port $port"
  fi
  
  # Small delay before next port to avoid GPU thrashing
  sleep 2
done

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Ollama warmup complete"
