#!/bin/sh
# MemTranslator capture hook for Claude Code (UserPromptSubmit).
# Fail-open by design: if the daemon is down, exit 0 fast and let the
# prompt through untouched. Never blocks, never modifies, never prints.
INPUT=$(cat)
printf '%s' "$INPUT" | /usr/bin/python3 -c '
import json, sys, urllib.request
try:
    d = json.load(sys.stdin)
    payload = json.dumps({
        "text": d.get("prompt", ""),
        "source": "claude-code",
        "session_id": d.get("session_id"),
        "cwd": d.get("cwd"),
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8123/api/events/submit",
        data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=1)
except Exception:
    pass
' 2>/dev/null
exit 0
