from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import httpx
from time import perf_counter
import uvicorn
import json
import subprocess
import asyncio
from pathlib import Path

app = FastAPI()

VLLM_URL = "http://127.0.0.1:11435"
VLLM_BASE_URL = VLLM_URL.rsplit(":", 1)[0]

# Path to the ollama monitor script
OLLAMA_MONITOR_SCRIPT = Path(__file__).parent.parent.parent / "monitoring" / "ollama_monitor.py"


def get_ollama_instances():
    """
    Get list of running Ollama instances with GPU information.
    Returns a list of dicts with port, pid, and GPU name.
    """
    if not OLLAMA_MONITOR_SCRIPT.exists():
        return []
    
    try:
        result = subprocess.run(
            ["python3", str(OLLAMA_MONITOR_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return []
        
        # Monitor now returns a flat array: [{pid, port, gpu: {...}}]
        entries = json.loads(result.stdout)
        instances = []
        for entry in entries:
            gpu = entry.get("gpu") or {}
            short_name = (
                gpu.get("name", "Unknown GPU")
                .replace("NVIDIA GeForce ", "")
                .replace("NVIDIA ", "")
            )
            vram = gpu.get("memory", {}).get("total", "")
            label = f"{short_name} ({vram})" if vram else short_name
            instances.append({
                "pid":  entry.get("pid"),
                "port": entry["port"],
                "gpu":  label,
                "gpu_index": gpu.get("index"),
            })
        return instances
    
    except Exception as e:
        print(f"Error running ollama monitor: {e}")
        return []


HTML = r"""
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Hipo Chat</title>
  <style>
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #0b1020;
      color: #e8ecf1;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
    }
    .app {
      width: min(900px, 95vw);
      height: min(85vh, 900px);
      background: #121933;
      border-radius: 16px;
      display: flex;
      flex-direction: column;
      box-shadow: 0 10px 40px rgba(0,0,0,.35);
      overflow: hidden;
    }
    .app.app-multi {
      width: min(1280px, 98vw);
    }
    .app.app-many {
      width: min(1500px, 99vw);
    }
    @media (max-width: 1024px) {
      .app,
      .app.app-multi,
      .app.app-many {
        width: 95vw;
      }
    }
    .header {
      padding: 18px 22px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }
    .title {
      font-size: 20px;
      font-weight: 700;
    }
    .target {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #c2d0e4;
      flex-wrap: wrap;
    }
    .targets-list {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .target-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,.15);
      background: #0f1530;
      color: white;
      padding: 6px 10px;
      font-size: 12px;
      user-select: none;
    }
    .target-item input {
      margin: 0;
      accent-color: #22c55e;
    }
    .target-empty {
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,.15);
      background: #0f1530;
      color: #9fb0c8;
      padding: 6px 10px;
      font-size: 12px;
    }
    .messages {
      flex: 1;
      overflow-y: auto;
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .msg {
      max-width: 80%;
      padding: 12px 14px;
      border-radius: 14px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .user {
      align-self: flex-end;
      background: #3b82f6;
      color: white;
    }
    .assistant {
      align-self: flex-start;
      background: #1d274d;
      color: #e8ecf1;
    }
    .composer {
      display: flex;
      gap: 10px;
      padding: 16px;
      border-top: 1px solid rgba(255,255,255,.08);
    }
    textarea {
      flex: 1;
      resize: none;
      min-height: 56px;
      max-height: 180px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,.12);
      background: #0f1530;
      color: white;
      padding: 14px;
      font: inherit;
      outline: none;
    }
    button {
      border: 0;
      border-radius: 12px;
      padding: 0 18px;
      background: #22c55e;
      color: #08110c;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled {
      opacity: .6;
      cursor: not-allowed;
    }
    .hint {
      padding: 0 18px 12px;
      font-size: 12px;
      color: #9fb0c8;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    .hint-model {
      font-size: 11px;
      color: #7f93b2;
    }
    .msg-meta {
      font-size: 10px;
      color: #4a5a7a;
      margin-top: 5px;
      text-align: left;
      padding-left: 2px;
      align-self: flex-start;
    }
    .compare-row {
      width: 100%;
      display: grid;
      gap: 10px;
      align-items: stretch;
    }
    .compare-card {
      background: #1d274d;
      color: #e8ecf1;
      border-radius: 14px;
      padding: 10px 12px;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .compare-head {
      font-size: 11px;
      color: #a7b8d3;
      border-bottom: 1px solid rgba(255,255,255,.08);
      padding-bottom: 6px;
    }
    .compare-body {
      font-size: 14px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .compare-meta {
      font-size: 10px;
      color: #4a5a7a;
    }
    .typing-indicator {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-left: 6px;
      vertical-align: middle;
    }
    .typing-dot {
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: #7f93b2;
      opacity: 0.35;
      animation: blink 1.1s infinite ease-in-out;
    }
    .typing-dot:nth-child(2) {
      animation-delay: 0.2s;
    }
    .typing-dot:nth-child(3) {
      animation-delay: 0.4s;
    }
    @keyframes blink {
      0%, 80%, 100% { opacity: 0.35; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-1px); }
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <div class="title">Hipo</div>
      <div class="target">
        <span>Cibles:</span>
        <div id="target-list" class="targets-list">
          <span class="target-empty">Chargement...</span>
        </div>
      </div>
    </div>
    <div id="messages" class="messages">
      <div class="msg assistant">Bonjour. Posez votre question.</div>
    </div>
    <div class="composer">
      <textarea id="input" placeholder="Écrivez votre message..."></textarea>
      <button id="send">Envoyer</button>
    </div>
      <div class="hint">
        <span>Prototype de partage branché sur Ollama local.</span>
      <span id="request-time" class="hint-model">Temps: -</span>
    </div>
  </div>

  <script>
    const MODEL_NAME = "qwen2.5:3b";
    const messagesEl = document.getElementById("messages");
    const inputEl = document.getElementById("input");
    const sendBtn = document.getElementById("send");
    const targetListEl = document.getElementById("target-list");
    const requestTimeEl = document.getElementById("request-time");
    const appEl = document.querySelector(".app");

    const systemMessage = { role: "system", content: "You are a helpful assistant. Be concise." };
    const historiesByPort = {};
    let availableInstances = [];

    // Load available Ollama instances
    async function loadOllamaInstances() {
      try {
        const res = await fetch("/api/ollama-instances");
        const data = await res.json();
        
        targetListEl.innerHTML = "";
        availableInstances = data.instances || [];
        
        if (availableInstances.length > 0) {
          availableInstances.forEach((instance, index) => {
            const label = document.createElement("label");
            label.className = "target-item";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.dataset.index = String(index);
            checkbox.checked = index === 0;

            const text = document.createElement("span");
            text.textContent = `Port ${instance.port} (${instance.gpu})`;

            label.appendChild(checkbox);
            label.appendChild(text);
            targetListEl.appendChild(label);
          });
          updateAppWidth();
        } else {
          const empty = document.createElement("span");
          empty.className = "target-empty";
          empty.textContent = "Aucune instance Ollama trouvée";
          targetListEl.appendChild(empty);
          updateAppWidth();
        }
      } catch (err) {
        console.error("Error loading Ollama instances:", err);
        targetListEl.innerHTML = '<span class="target-empty">Erreur de chargement</span>';
        updateAppWidth();
      }
    }

    function getSelectedInstances() {
      const checked = Array.from(
        targetListEl.querySelectorAll('input[type="checkbox"]:checked')
      );
      return checked
        .map((el) => availableInstances[Number(el.dataset.index)])
        .filter(Boolean);
    }

    function updateAppWidth() {
      const selectedCount = getSelectedInstances().length;
      appEl.classList.toggle("app-multi", selectedCount > 1);
      appEl.classList.toggle("app-many", selectedCount > 2);
    }

    // Load instances when page loads
    loadOllamaInstances();

    function addMessage(role, text) {
      const div = document.createElement("div");
      div.className = "msg " + (role === "user" ? "user" : "assistant");
      div.textContent = text;
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function createComparisonRow(instances) {
      const cols = Math.max(1, instances.length);
      const row = document.createElement("div");
      row.className = "compare-row";
      row.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;

      const cards = new Map();
      instances.forEach((instance) => {
        const gpuLabel = (instance.gpu || "").replace(/\s*\([^)]*MiB\)\s*$/, "");
        const title = gpuLabel ? `Port ${instance.port} · ${gpuLabel}` : `Port ${instance.port}`;

        const card = document.createElement("div");
        card.className = "compare-card";

        const head = document.createElement("div");
        head.className = "compare-head";
        head.textContent = title;

        const body = document.createElement("div");
        body.className = "compare-body";
        body.textContent = "";

        const meta = document.createElement("div");
        meta.className = "compare-meta";
        meta.textContent = "Generation en cours";

        const typing = document.createElement("span");
        typing.className = "typing-indicator";
        for (let i = 0; i < 3; i += 1) {
          const dot = document.createElement("span");
          dot.className = "typing-dot";
          typing.appendChild(dot);
        }
        meta.appendChild(typing);

        card.appendChild(head);
        card.appendChild(body);
        card.appendChild(meta);
        row.appendChild(card);

        cards.set(instance.port, { body, meta, gpuLabel, typing });
      });

      messagesEl.appendChild(row);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return cards;
    }

    async function streamOneInstance(instance, text, cardRef) {
      const portKey = String(instance.port);
      if (!historiesByPort[portKey]) {
        historiesByPort[portKey] = [systemMessage];
      }
      const portHistory = historiesByPort[portKey];
      portHistory.push({ role: "user", content: text });

      const res = await fetch("/v1/chat/completions/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: MODEL_NAME,
          messages: portHistory,
          temperature: 0.3,
          vllm_port: instance.port,
          gpu_index: instance.gpu_index,
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(`Streaming failed for port ${instance.port}`);
      }

      const decoder = new TextDecoder();
      const reader = res.body.getReader();
      let buffer = "";
      let reply = "";
      let usedModel = MODEL_NAME;
      let elapsedMs = null;
      let tpsStr = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const eventBlock of events) {
          const lines = eventBlock.split("\n").filter(Boolean);
          let eventName = "message";

          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            }
            if (!line.startsWith("data:")) {
              continue;
            }

            const dataStr = line.slice(5).trim();
            if (dataStr === "[DONE]") {
              continue;
            }

            if (eventName === "metrics") {
              try {
                const metrics = JSON.parse(dataStr);
                elapsedMs = Number(metrics.elapsed_ms);
                const tps = Number(metrics.tokens_per_sec);
                if (Number.isFinite(tps)) {
                  tpsStr = `${tps.toFixed(1)} tok/s`;
                }
              } catch (e) {
                // ignore malformed metrics events
              }
              continue;
            }

            try {
              const chunk = JSON.parse(dataStr);
              if (chunk?.model) {
                usedModel = chunk.model;
              }
              const delta = chunk?.choices?.[0]?.delta?.content || "";
              if (delta) {
                reply += delta;
                cardRef.body.textContent = reply;
                messagesEl.scrollTop = messagesEl.scrollHeight;
              }
            } catch (e) {
              // ignore malformed data lines
            }
          }
        }
      }

      const elapsedStr = Number.isFinite(elapsedMs)
        ? `${(elapsedMs / 1000).toFixed(2)} s`
        : null;
      const meta = [usedModel, cardRef.gpuLabel, tpsStr, elapsedStr]
        .filter(Boolean)
        .join(" · ");
      cardRef.meta.textContent = meta || "Termine";
      cardRef.typing = null;

      if (!reply.trim()) {
        reply = "Erreur: réponse vide";
        cardRef.body.textContent = reply;
      }
      portHistory.push({ role: "assistant", content: reply });

      return { elapsedMs };
    }

    async function sendMessage() {
      const text = inputEl.value.trim();
      if (!text) return;

      const selectedInstances = getSelectedInstances();
      if (!selectedInstances.length) {
        addMessage("assistant", "Selectionnez au moins une cible.");
        return;
      }

      addMessage("user", text);
      inputEl.value = "";
      sendBtn.disabled = true;
      requestTimeEl.textContent = "Temps: en cours...";
      const startAt = performance.now();

      try {
        const cards = createComparisonRow(selectedInstances);

        const tasks = selectedInstances.map(async (instance) => {
          const cardRef = cards.get(instance.port);
          try {
            return await streamOneInstance(instance, text, cardRef);
          } catch (err) {
            cardRef.body.textContent = "Erreur de connexion au serveur.";
            cardRef.meta.textContent = cardRef.gpuLabel || "Erreur";
            cardRef.typing = null;
            return { elapsedMs: null };
          }
        });

        const results = await Promise.all(tasks);

        const validElapsed = results
          .map((r) => r.elapsedMs)
          .filter((v) => Number.isFinite(v));
        if (validElapsed.length) {
          requestTimeEl.textContent = `Temps: ${(Math.max(...validElapsed) / 1000).toFixed(2)} s`;
        } else {
          const total = (performance.now() - startAt) / 1000;
          requestTimeEl.textContent = `Temps: ${total.toFixed(2)} s`;
        }
      } catch (err) {
        requestTimeEl.textContent = "Temps: indisponible";
        addMessage("assistant", "Erreur de connexion au serveur.");
      } finally {
        sendBtn.disabled = false;
        inputEl.focus();
      }
    }

    sendBtn.addEventListener("click", sendMessage);
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
    targetListEl.addEventListener("change", (e) => {
      if (e.target && e.target.matches('input[type="checkbox"]')) {
        updateAppWidth();
      }
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML

@app.get("/api/ollama-instances")
async def get_instances():
    """Get list of running Ollama instances with GPU information."""
    instances = get_ollama_instances()
    return JSONResponse(content={"instances": instances})

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
    
    print(f"[CHAT] Using port: {selected_port}")

    target_url = f"{VLLM_BASE_URL}:{selected_port}"

    start_time = perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{target_url}/v1/chat/completions", json=payload)
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
