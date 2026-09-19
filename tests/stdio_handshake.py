"""Start the server exactly as Claude will, and do a real MCP handshake."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "run_server.py"


def frame(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


proc = subprocess.Popen(
    [str(PYTHON), "-X", "utf8", str(LAUNCHER)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=0x08000000,
)

assert proc.stdin and proc.stdout

proc.stdin.write(frame({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "handshake-test", "version": "1.0"},
    },
}))
proc.stdin.flush()

line = proc.stdout.readline()
reply = json.loads(line)
info = reply.get("result", {}).get("serverInfo", {})
print("initialize ->", info.get("name"), info.get("version"), flush=True)

proc.stdin.write(frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
proc.stdin.flush()

proc.stdin.write(frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
proc.stdin.flush()
tools = json.loads(proc.stdout.readline())["result"]["tools"]
print("tools/list ->", len(tools), "tools", flush=True)

# a real call that touches AutoCAD, through the protocol
proc.stdin.write(frame({
    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
    "params": {"name": "acad_status", "arguments": {}},
}))
proc.stdin.flush()
start = time.time()
result = json.loads(proc.stdout.readline())["result"]
payload = result.get("structuredContent") or result.get("content")
print(f"acad_status -> ({time.time()-start:.2f}s)", json.dumps(payload, indent=2)[:700], flush=True)

# and one that draws, so we know the whole path works end to end
proc.stdin.write(frame({
    "jsonrpc": "2.0", "id": 4, "method": "tools/call",
    "params": {"name": "draw_circle", "arguments": {"center": [0, 0], "radius": 250,
                                                    "layer": "MCP-CHECK"}},
}))
proc.stdin.flush()
result = json.loads(proc.stdout.readline())["result"]
print("draw_circle ->", json.dumps(result.get("structuredContent") or result.get("content"))[:300],
      flush=True)

proc.stdin.close()
try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    proc.kill()

err = (proc.stderr.read() or b"").decode("utf-8", "replace").strip()
if err:
    print("\nstderr:\n" + err[-1200:], flush=True)
print("\nhandshake OK", flush=True)
