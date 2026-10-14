#!/bin/sh
set -eu
cd "$(dirname "$0")"
export BETAR_WEB_PORT="${BETAR_WEB_PORT:-5173}"
export BETAR_ENGINE_PORT="${BETAR_ENGINE_PORT:-8765}"
if [ ! -x .venv/bin/python ] || [ ! -d web/node_modules ]; then
  echo '请先按 README.md 安装本地依赖。'
  exit 1
fi
.venv/bin/python - <<'PY'
import os
import socket
ports = [int(os.environ[name]) for name in ("BETAR_ENGINE_PORT", "BETAR_WEB_PORT")]
if len(set(ports)) != 2 or any(not 1024 <= port <= 65535 for port in ports):
    raise SystemExit("网页与检查程序须使用两个不同的 1024–65535 端口。")
for port in ports:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"端口 {port} 已被使用。请打开已有工作台，或先关闭你之前启动的服务。")
PY
.venv/bin/python -m boulderlab.server --port "$BETAR_ENGINE_PORT" --web-port "$BETAR_WEB_PORT" &
engine_pid=$!
cleanup() {
  kill "$engine_pid" 2>/dev/null || true
  if [ -n "${web_pid:-}" ]; then kill "$web_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
npm --prefix web run dev -- --host 127.0.0.1 --port "$BETAR_WEB_PORT" --strictPort &
web_pid=$!
wait "$web_pid"
