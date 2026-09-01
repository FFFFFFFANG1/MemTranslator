"""Synchronous localhost client used by the menu-bar process."""
from __future__ import annotations

import json
import urllib.request

from memtranslator.config import DAEMON_URL
from memtranslator.hotkey.models import FeedbackEvent, LearnEvent


class DaemonClient:
    def __init__(self, base_url: str = DAEMON_URL):
        self.base_url = base_url.rstrip("/")

    @property
    def streaming_enabled(self) -> bool:
        # Tests and embedders sometimes replace the instance's synchronous
        # transport. That does not implicitly provide an NDJSON transport.
        return "_post" not in self.__dict__

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

    def translate_stream(self, text: str, context: dict, on_ready) -> dict:
        """Consume NDJSON while handing the safe patch to the UI immediately."""
        request = urllib.request.Request(
            self.base_url + "/api/translate/stream",
            data=json.dumps({"text": text, "context": context},
                            ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line)
                if event.get("type") == "error":
                    raise OSError(event.get("error") or "translator stream failed")
                if event.get("type") == "rewrite_ready":
                    on_ready(event)
                if event.get("type") == "done":
                    return event["translation"]
        raise OSError("translator stream ended before done")

    def feedback(self, event: FeedbackEvent) -> dict:
        return self._post("/api/desktop/feedback", {
            "translate_id": event.translate_id,
            "final_text": event.final_text,
            "trigger": event.trigger,
            "source": "macos-accessibility",
            "input_context": event.input_context,
        })

    def learn(self, event: LearnEvent) -> dict:
        # The daemon endpoint keeps its v0 wire name for compatibility; the
        # desktop product action and its Python interface are Learn.
        return self._post("/api/desktop/capture", {
            "capture_id": event.learn_id,
            "text": event.text,
            "input_context": event.input_context,
            "translate_id": event.translate_id,
        })
