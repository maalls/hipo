from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import httpx
from time import perf_counter
import uvicorn
import json
import asyncio
from pathlib import Path

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

VLLM_URL = "http://127.0.0.1:11435"
VLLM_BASE_URL = VLLM_URL.rsplit(":", 1)[0]

# Hardcoded Ollama instance config.
# Each entry maps a GPU to a port. Edit this to add/remove instances.
OLLAMA_INSTANCES = [
    {
        "pid":       None,
        "port":      11434,
        "gpu":       "RTX 3090 (24 GiB)",
        "gpu_index": 0,
        "gpu_uuid":  "GPU-c26d2adb-e44d-e390-cbf0-73f6eb8ea866",
    },
]


def get_ollama_instances():
    return OLLAMA_INSTANCES

@app.get("/")
async def index(request: Request):
  return templates.TemplateResponse(
    request=request,
    name="index.html",
    context={"model_name": "qwen2.5:3b"},
  )

@app.get("/api/ollama-instances")
async def get_instances():
    """Get list of running Ollama instances with GPU information."""
    instances = get_ollama_instances()
    return JSONResponse(content={"instances": instances})

@app.post("/v2/chat/completions")
async def chat_completions(request: Request):
    return JSONResponse('ok')
@app.post("/v1/chat/completions")

async def chat_completions(request: Request):
    
    payload = await request.json()
    selected_port = payload.pop("vllm_port", None)
    gpu_index = payload.pop("gpu_index", None)
    
    print(f"[CHAT] Selected port: {selected_port}, GPU index: {gpu_index}")

    try:
        selected_port = int(selected_port) if selected_port is not None else None
    except (TypeError, ValueError):
        selected_port = None

    # Get valid ports from running instances
    instances = get_ollama_instances()
    valid_ports = {inst['port'] for inst in instances}

    if not valid_ports:
        return JSONResponse(
            status_code=503,
            content={"error": "No Ollama instances running"}
        )

    if selected_port not in valid_ports:
        # Use first available port as fallback
        selected_port = instances[0]['port']
    
    print(f"[CHAT] Using port: {selected_port}!!")

    target_url = f"{VLLM_BASE_URL}:{selected_port}"

    start_time = perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{target_url}/v2/chat/completions", json=payload)
    elapsed_ms = (perf_counter() - start_time) * 1000

    response_json = resp.json()
    completion_tokens = None
    try:
      usage = response_json.get("usage", {}) if isinstance(response_json, dict) else {}
      completion_tokens = usage.get("completion_tokens")
      if completion_tokens is None:
        completion_tokens = usage.get("total_tokens")
    except AttributeError:
      completion_tokens = None

    tokens_per_sec = None
    if isinstance(completion_tokens, (int, float)) and elapsed_ms > 0:
      tokens_per_sec = completion_tokens / (elapsed_ms / 1000.0)

    headers = {"X-LLM-Execution-Time-Ms": f"{elapsed_ms:.0f}"}
    if tokens_per_sec is not None:
      headers["X-LLM-Tokens-Per-Sec"] = f"{tokens_per_sec:.3f}"

    return JSONResponse(
      status_code=resp.status_code,
      content=response_json,
      headers=headers,
    )

@app.post("/v1/chat/completions/stream")
async def chat_completions_stream(request: Request):
    payload = await request.json()
    selected_port = payload.pop("vllm_port", None)
    payload.pop("gpu_index", None)

    try:
        selected_port = int(selected_port) if selected_port is not None else None
    except (TypeError, ValueError):
        selected_port = None

    instances = get_ollama_instances()
    valid_ports = {inst["port"] for inst in instances}

    if not valid_ports:
        return JSONResponse(
            status_code=503,
            content={"error": "No Ollama instances running"},
        )

    if selected_port not in valid_ports:
        selected_port = instances[0]["port"]

    target_url = f"{VLLM_BASE_URL}:{selected_port}/v1/chat/completions"
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}

    async def event_generator():
        start_time = perf_counter()
        completion_tokens = None

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", target_url, json=payload) as resp:
                if resp.status_code >= 400:
                    err = await resp.aread()
                    msg = err.decode("utf-8", errors="ignore")
                    yield f"event: error\ndata: {json.dumps({'status': resp.status_code, 'error': msg})}\n\n"
                    return

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                        usage = chunk.get("usage") if isinstance(chunk, dict) else None
                        if isinstance(usage, dict):
                            completion_tokens = usage.get("completion_tokens", completion_tokens)
                            if completion_tokens is None:
                                completion_tokens = usage.get("total_tokens")
                    except json.JSONDecodeError:
                        pass

                    yield f"data: {data_str}\n\n"

        elapsed_ms = (perf_counter() - start_time) * 1000
        tokens_per_sec = None
        if isinstance(completion_tokens, (int, float)) and elapsed_ms > 0:
            tokens_per_sec = completion_tokens / (elapsed_ms / 1000.0)

        metrics = {
            "elapsed_ms": round(elapsed_ms, 0),
            "tokens_per_sec": round(tokens_per_sec, 3) if tokens_per_sec is not None else None,
        }
        yield f"event: metrics\ndata: {json.dumps(metrics)}\n\n"
        await asyncio.sleep(0)
        yield "data: [DONE]\\n\\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/health")
async def health():
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8080)
