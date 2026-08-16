"""Synchronous localhost client used by the menu-bar process."""
from __future__ import annotations

import json
import urllib.request

from memtranslator.hotkey.models import FeedbackEvent


class DaemonClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8123"):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload: dict, timeout: float = 20) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def translate(self, text: str, context: dict) -> dict:
        return self._post("/api/translate", {"text": text, "context": context})

    def feedback(self, event: FeedbackEvent) -> dict:
        return self._post("/api/desktop/feedback", {
            "translate_id": event.translate_id,
            "final_text": event.final_text,
            "trigger": event.trigger,
            "source": "macos-accessibility",
            "input_context": event.input_context,
        })
