"""Build a pinned OASST1 root-prompt pool for E1 noise expansion.

The source is the official supplemental prompts export.  It already contains
initial prompter messages only; this script applies structural/official-label
filters but deliberately makes no semantic judgement about whether a prompt
contains a durable requirement.  The benchmark contract assumes it does not.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


SOURCE_REVISION = "fdf72ae0827c1cda404aff25b6603abec9e3399b"
SOURCE_URL = (
    "https://huggingface.co/datasets/OpenAssistant/oasst1/resolve/"
    f"{SOURCE_REVISION}/2023-04-12_oasst_prompts.messages.jsonl.gz")
REJECT_LABELS = (
    "spam", "pii", "not_appropriate", "hate_speech", "sexual_content")


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _label_value(row: dict, name: str) -> float:
    value = ((row.get("labels") or {}).get(name) or {}).get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 1.0


def select_rows(rows, *, caps: dict[str, int], max_chars: int) -> list[dict]:
    candidates: dict[str, list[dict]] = {language: [] for language in caps}
    seen_text = set()
    for row in rows:
        language = row.get("lang")
        text = _normalise(str(row.get("text") or ""))
        if language not in caps or not 12 <= len(text) <= max_chars:
            continue
        if (row.get("role") != "prompter" or row.get("parent_id") is not None
                or row.get("review_result") is not True
                or row.get("deleted") or row.get("synthetic")):
            continue
        if any(_label_value(row, name) > 0 for name in REJECT_LABELS):
            continue
        folded = text.casefold()
        if folded in seen_text:
            continue
        seen_text.add(folded)
        message_id = str(row.get("message_id") or "")
        if not message_id:
            continue
        candidates[language].append({
            "id": f"oasst1:{message_id}",
            "lang": language,
            "text": text,
        })

    selected = []
    for language, cap in caps.items():
        ranked = sorted(
            candidates[language],
            key=lambda row: hashlib.sha256(
                f"memtranslator-noise-v1:{row['id']}".encode()).digest())
        if len(ranked) < cap:
            raise ValueError(
                f"OASST1 source has only {len(ranked)} usable {language} "
                f"root prompts; requested {cap}")
        selected.extend(ranked[:cap])
    return sorted(selected, key=lambda row: (row["lang"], row["id"]))


def _read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--english", type=int, default=4096)
    parser.add_argument("--chinese", type=int, default=800)
    parser.add_argument("--max-chars", type=int, default=500)
    args = parser.parse_args()
    selected = select_rows(
        _read_rows(args.source), caps={"en": args.english, "zh": args.chinese},
        max_chars=args.max_chars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n"
                for row in selected))
    print(json.dumps({
        "output": str(args.output),
        "source_url": SOURCE_URL,
        "source_revision": SOURCE_REVISION,
        "counts": {
            language: sum(row["lang"] == language for row in selected)
            for language in ("en", "zh")},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
