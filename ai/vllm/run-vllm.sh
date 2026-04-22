#!/usr/bin/env bash
set -euo pipefail

source /home/malo/ai/vllm/.venv/bin/activate

exec vllm serve Qwen/Qwen2.5-3B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager
