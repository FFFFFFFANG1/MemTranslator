"""Platform-neutral data contracts for focused-input transactions."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class TextRange:
    location: int
    length: int

    @property
    def end(self) -> int:
        return self.location + self.length


@dataclass(frozen=True)
class InputSnapshot:
    identity: str
    full_text: str
    target_range: TextRange
    app_name: str = ""
    app_bundle_id: str = ""
    window_title: str = ""
    role: str = ""
    subrole: str = ""
    identifier: str = ""
    editable: bool = True
    secure: bool = False
    value_settable: bool = True
    selection_settable: bool = True
    screen_bounds: tuple[float, float, float, float] | None = None
    captured_at: float = field(default_factory=time.time)

    @property
    def target_text(self) -> str:
        return self.full_text[self.target_range.location:self.target_range.end]

    @property
    def prefix(self) -> str:
        return self.full_text[:self.target_range.location]

    @property
    def suffix(self) -> str:
        return self.full_text[self.target_range.end:]

    def context(self) -> dict:
        return {key: value for key, value in asdict(self).items()
                if key not in {"full_text", "target_range", "captured_at"}
                and value not in ("", False, None)}


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    strategy: str
    expected_full_text: str = ""
    reason: str = ""


@dataclass(frozen=True)
class FeedbackEvent:
    translate_id: str
    original: str
    polished: str
    final_text: str
    trigger: str
    input_context: dict
