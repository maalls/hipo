#!/usr/bin/env bash
set -eu

echo "== chat stack quick check =="
echo "time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo

echo "[1/5] systemd services"
for svc in chat-ui cloudflared ollama-gpu-48a64803 ollama-gpu-68f663ec ollama-gpu-c26d2adb ollama-gpu-dd7734bb; do
  state="$(systemctl is-active "$svc" 2>/dev/null || true)"
  enabled="$(systemctl is-enabled "$svc" 2>/dev/null || true)"
  printf ' - %-28s active=%-10s enabled=%s\n' "$svc" "$state" "$enabled"
done
echo

echo "[2/5] listening ports"
ss -ltn | grep -E ':(8080|1143[4-9]|1144[0-9])( |$)' || echo " - no expected ports found"
echo

echo "[3/5] local api checks"
for url in \
  http://127.0.0.1:8080/health \
  http://127.0.0.1:11434/api/tags \
  http://127.0.0.1:11435/api/tags \
  http://127.0.0.1:11436/api/tags \
  http://127.0.0.1:11437/api/tags; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' -m 3 "$url" || true)"
  printf ' - %-38s -> %s\n' "$url" "$code"
done
echo

echo "[4/5] public entrypoint via cloudflare"
public_url="https://hipo.ai-oe.co/health"
public_code="$(curl -sS -o /dev/null -w '%{http_code}' -m 5 "$public_url" || true)"
printf ' - %-38s -> %s\n' "$public_url" "$public_code"
echo

echo "[5/5] vscode-server presence (forwarding context)"
if pgrep -af 'vscode-server|code-server' >/dev/null 2>&1; then
  echo " - vscode-server process: PRESENT"
  pgrep -af 'vscode-server|code-server' | head -n 5
else
  echo " - vscode-server process: NOT FOUND"
fi
echo

echo "summary:"
if [ "$(systemctl is-active chat-ui 2>/dev/null || true)" != "active" ]; then
  echo " - chat-ui is down -> restart with: sudo systemctl restart chat-ui"
elif [ "$public_code" != "200" ]; then
  echo " - local stack is up but public entrypoint is failing -> check cloudflared logs"
  echo "   command: journalctl -u cloudflared -n 100 --no-pager"
else
  echo " - stack looks healthy (local + public)."
fi
