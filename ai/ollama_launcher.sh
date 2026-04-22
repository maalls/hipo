#!/bin/bash
# Start Ollama instances with staggered startup.
# GPU selection is configurable via ENABLED_GPUS (default: 3,2,1,0).

set -euo pipefail

DELAY="${DELAY:-5}"                  # seconds between each startup
BASE_PORT="${BASE_PORT:-11434}"      # first port, then +1 for each GPU
MODELS_DIR="${MODELS_DIR:-/var/lib/ollama-models}"
MAPPING_FILE="${MAPPING_FILE:-/tmp/ollama_gpu_mapping.json}"
ENABLED_GPUS="${ENABLED_GPUS:-3,2,1,0}"

IFS=',' read -r -a GPU_LIST <<< "$ENABLED_GPUS"

if [ "${#GPU_LIST[@]}" -eq 0 ]; then
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: ENABLED_GPUS is empty"
  exit 1
fi

for i in "${!GPU_LIST[@]}"; do
  gpu="${GPU_LIST[$i]//[[:space:]]/}"
  if ! [[ "$gpu" =~ ^[0-9]+$ ]]; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: Invalid GPU index '$gpu' in ENABLED_GPUS='$ENABLED_GPUS'"
    exit 1
  fi
  GPU_LIST[$i]="$gpu"
done

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting ${#GPU_LIST[@]} Ollama instance(s)"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] ENABLED_GPUS=$ENABLED_GPUS BASE_PORT=$BASE_PORT DELAY=${DELAY}s"

# Create GPU mapping file for monitor.
{
  echo "{"
  last_index=$(( ${#GPU_LIST[@]} - 1 ))
  for i in "${!GPU_LIST[@]}"; do
    port=$((BASE_PORT + i))
    gpu_index="${GPU_LIST[$i]}"
    comma="," 
    if [ "$i" -eq "$last_index" ]; then
      comma=""
    fi
    printf '  "%d": {"port": %d, "gpu_index": %d}%s\n' "$port" "$port" "$gpu_index" "$comma"
  done
  echo "}"
} > "$MAPPING_FILE"

for i in "${!GPU_LIST[@]}"; do
  port=$((BASE_PORT + i))
  gpu_index="${GPU_LIST[$i]}"

  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Launching Ollama on port $port (GPU $gpu_index)..."

  CUDA_VISIBLE_DEVICES="$gpu_index" OLLAMA_HOST="127.0.0.1:$port" OLLAMA_MODELS="$MODELS_DIR" \
    sudo -E -u ollama /usr/local/bin/ollama serve &

  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Waiting ${DELAY}s before next instance..."
  sleep "$DELAY"
done

echo "[$(date +'%Y-%m-%d %H:%M:%S')] All configured Ollama instances launched"

# Wait indefinitely (parent process will manage lifecycle)
wait
