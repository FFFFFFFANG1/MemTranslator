"""Label E1 golden requirements with the live Extractor item attributes.

Each request contains exactly one authored golden item and the exact user turn
that first introduced it according to lifecycle.  GLM-5.3 returns the live
Extractor JSON protocol; the product parser validates that output before any
attribute can be written into the corpus.  Authored text and scoring fields
are never replaced by model output.

Examples:
    PYTHONPATH=src .venv/bin/python -m bench.suites.oracle_attribute --limit 5
    PYTHONPATH=src .venv/bin/python -m bench.suites.oracle_attribute --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from memtranslator.extraction import parse_candidate_output
from memtranslator.schema import WORK_KIND_ANY

from bench.suites.config import CASES, RUN_DIR
from bench.suites.judge import _complete
from bench.suites.retry import with_retry

ATTRIBUTE_MODEL = "glm-5.3"
# Ark's GLM-5.3 endpoint requires thinking. The attribute-only prompt below is
# intentionally compact; 8k leaves headroom for ambiguous labels while still
# completing within the judge channel's 120-second request timeout.
ATTRIBUTE_MAX_TOKENS = 8192
CACHE_VERSION = 1
ATTRIBUTE_FIELDS = (
    "bucket", "scope_mode", "applies_when", "work_kinds", "key",
    "confidence",
)

# Human audit after the 2026-08-19 GLM-5.3 pass. These are intentionally
# partial: the model remains the bulk labeler, while this small, reviewable
# layer fixes counterfactual-global mistakes and clear source-task leakage.
# Every effective result is revalidated through the live Extractor parser.
MANUAL_ATTRIBUTE_OVERRIDES = {
    # Optional/conditional facets are retrieval-only, not always-in-context.
    "e-01:e01-c24": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": (
            "when output contains ordinary prose lines outside links, "
            "tables, headings, or code blocks")},
    "e-02:e02-c29": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when emphasizing or highlighting words or phrases"},
    "e-03:e03-c00": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": (
            "when an output would otherwise reuse the former instruction's "
            "disclaimer or structure")},
    "e-05:e05-c21": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when output contains natural-language prose sentences"},
    "e-06:e06-c18": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when output contains natural-language prose sentences"},
    "e-06:e06-c26": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when output contains natural-language prose sentences"},
    "e-07:e07-c24": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when output contains natural-language prose"},
    "e-07:e07-s03": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when output contains natural-language prose sentences"},
    "e-09:e09-c06": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": (
            "unless the user explicitly requests an anthropomorphic or "
            "intelligence-signaling style")},
    "e-09:e09-c12": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when the output communicates directly with a person"},
    "e-11:e11-c16": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when output contains natural-language prose sentences"},
    "e-11:e11-c24": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when describing an entity with multiple traits"},
    "e-12:e12-c06": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": (
            "unless the user explicitly requests an anthropomorphic or "
            "intelligence-signaling style")},
    "e-12:e12-c10": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when the output communicates directly with a person"},

    # Clear universality or applicability corrections from authored wording.
    "e-12:e12-c07": {
        "scope_mode": "global", "work_kinds": ["all"],
        "applies_when": None},
    "e-03:e03-c14": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when the output mentions percentages"},
    "e-04:e04-c20": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": (
            "when writing analytical prose, including reports and "
            "postmortems")},
    "e-10:e10-c21": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when writing a postmortem or any technical document"},

    # Source-task leakage or unstable facet-as-work-kind labels.
    "e-09:e09-c27": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when writing a one-line response or one-liner"},
    "e-09:e09-s01": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": "when writing a one-line response or one-liner"},
    "e-10:e10-c26": {
        "scope_mode": "scoped", "work_kinds": ["fill_in_blank"],
        "applies_when": None},
    "e-10:e10-s00": {
        "scope_mode": "scoped",
        "work_kinds": ["technical_documentation", "code_comment"],
        "applies_when": None},
    "e-11:e11-s03": {
        "scope_mode": "scoped", "work_kinds": ["all"],
        "applies_when": (
            "when writing a longer piece such as a document or extended text")},
}

ATTRIBUTE_SYSTEM = """Label one already-adjudicated atomic durable requirement
with the live Extractor item attributes. SOURCE SIGNAL is the exact user turn
that introduced it. Classify GOLDEN ITEM itself; use the source only to
disambiguate its recurring work or semantic condition. Never inherit an
unrelated task, audience, or clause from the source. Do not discard, split,
merge, rewrite, or extract another item.

Applicability:
- work_kinds is a non-empty list of English slugs for recurring artifacts or
  activities, such as email, report, postmortem, code. Invent a narrow slug
  only when needed. Never use agent_response.
- global is reserved for a rule relevant to every possible agent output,
  including unrelated code, email, image, and analysis tasks. Its only legal
  shape is scope_mode="global", work_kinds=["all"], applies_when=null.
- Every task-specific or conditional rule is retrieval-only and uses
  scope_mode="scoped". Use concrete work_kinds with applies_when null or a
  narrower condition, or ["all"] with a non-empty semantic condition.
  scoped + ["all"] + null is invalid.
- If any ordinary task makes the rule irrelevant, it is scoped. Rules tied to
  optional content such as units, dates, abbreviations, code blocks, links,
  citations, or named entities use ["all"] plus a short applies_when when they
  cross task kinds. applies_when is natural language, not keywords, and must
  not merely repeat the item or a concrete work kind.

Other fields:
- bucket is exactly one of: task_goal (objective), reasoning_policy (method or
  evidence), deliverables (required information/artifact), output_contract
  (rendering/order/length/structure/language), communication_style
  (tone/register/voice), execution_policy (tools/workflow/input/channel).
- key is a stable lowercase English facet label with a dot, such as
  length.max or tone.register. It is not a work-kind label.
- confidence is an integer 0-10.

Preserve GOLDEN ITEM verbatim as item.text. Return exactly the same candidate
wrapper used by the live Extractor, with potential_new only:
[{"decision":"candidate","kind":"potential_new","change_mode":null,
  "item":{"text":"<exact golden item>","bucket":"<bucket>",
  "scope_mode":"global|scoped","applies_when":"<condition>"|null,
  "work_kinds":["slug"],"key":"facet.attribute","confidence":0},
  "target_query":null,"sources":[1]}]
Output strictly one JSON array and nothing else."""


@dataclass(frozen=True)
class AnnotationJob:
    episode_id: str
    item_id: str
    text: str
    source_seq: int
    source_message: str
    fingerprint: str

    @property
    def cache_key(self) -> str:
        return f"{self.episode_id}:{self.item_id}"


def _fingerprint(episode_id: str, item_id: str, text: str, source_seq: int,
                 source_message: str) -> str:
    payload = json.dumps(
        {"episode": episode_id, "id": item_id, "text": text,
         "source_seq": source_seq, "source_message": source_message},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def load_episodes(spec: str = "") -> list[dict]:
    if spec.strip():
        episode_ids = [value.strip() for value in spec.split(",")
                       if value.strip()]
    else:
        episode_ids = [f"e-{number:02d}" for number in range(1, 13)]
    return [json.loads(
        (CASES / "episodes" / f"{episode_id}.json").read_text())
            for episode_id in episode_ids]


def annotation_jobs(episodes: list[dict]) -> list[AnnotationJob]:
    """Resolve each item to exactly one authored introduction, without IR."""
    jobs = []
    for episode in episodes:
        turns = {turn["seq"]: turn["user_input"]
                 for turn in episode["user_turns"]}
        lifecycle = episode["ground_truth"]["lifecycle"]
        for node in episode["ground_truth"]["requirements"]:
            introductions = [
                effect for effect in lifecycle
                if effect.get("id") == node["id"]
                and effect.get("op") in {"assert", "contradict"}
            ]
            if len(introductions) != 1:
                raise ValueError(
                    f"{episode['id']}:{node['id']} needs exactly one "
                    f"introduction, found {len(introductions)}")
            source_seq = introductions[0]["seq"]
            if source_seq not in turns:
                raise ValueError(
                    f"{episode['id']}:{node['id']} introduction turn "
                    f"{source_seq} does not exist")
            source_message = turns[source_seq]
            jobs.append(AnnotationJob(
                episode_id=episode["id"], item_id=node["id"],
                text=node["text"], source_seq=source_seq,
                source_message=source_message,
                fingerprint=_fingerprint(
                    episode["id"], node["id"], node["text"], source_seq,
                    source_message)))
    return jobs


def build_prompt(job: AnnotationJob, validation_error: str = "") -> str:
    payload = {
        "golden_item": job.text,
        "source_signal": {"signal": 1, "text": job.source_message},
    }
    prompt = (
        "Attribute this one already-adjudicated golden requirement:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nJSON:")
    if validation_error:
        prompt += (
            "\n\nYour previous answer failed the live Extractor parser: "
            f"{validation_error}. Return a corrected full JSON array.")
    return prompt


def parse_annotation(raw: str, job: AnnotationJob) -> dict:
    """Validate through the live parser and return corpus-facing attributes."""
    if not raw.strip():
        raise ValueError("candidate output empty (completion budget exhausted)")
    candidates, flags = parse_candidate_output(raw, [job.source_message])
    if flags:
        raise ValueError("; ".join(flags))
    if len(candidates) != 1 or candidates[0].item is None:
        raise ValueError(
            f"expected exactly one candidate with an item, found "
            f"{len(candidates)}")
    candidate = candidates[0]
    if candidate.source_signal_ids != [1]:
        raise ValueError("candidate sources must be exactly [1]")
    item = candidate.item
    work_kinds = ["all" if kind == WORK_KIND_ANY else kind
                  for kind in item.work_kinds]
    return {
        "bucket": item.bucket,
        "scope_mode": item.scope_mode,
        "applies_when": item.applies_when or None,
        "work_kinds": work_kinds,
        "key": item.key,
        "confidence": item.confidence,
    }


def effective_attributes(job: AnnotationJob, record: dict) -> dict:
    """Overlay human review, then validate the final public protocol shape."""
    attributes = dict(record["attributes"])
    attributes.update(MANUAL_ATTRIBUTE_OVERRIDES.get(job.cache_key, {}))
    item = {"text": job.text, **attributes}
    raw = json.dumps([{
        "decision": "candidate", "kind": "potential_new",
        "change_mode": None, "item": item, "target_query": None,
        "sources": [1],
    }], ensure_ascii=False)
    return parse_annotation(raw, job)


def annotate_job(
        job: AnnotationJob, *, model: str = ATTRIBUTE_MODEL, attempts: int = 3,
        complete_fn: Callable[..., str] | None = None) -> dict:
    complete = complete_fn or _complete
    validation_error = ""
    for attempt in range(1, max(1, attempts) + 1):
        prompt = build_prompt(job, validation_error)
        raw = with_retry(
            lambda: complete(
                ATTRIBUTE_SYSTEM, prompt, model=model,
                max_tokens=ATTRIBUTE_MAX_TOKENS),
            f"oracle-attribute/{job.cache_key}")
        try:
            attributes = parse_annotation(raw, job)
        except ValueError as error:
            validation_error = str(error)
            if attempt == attempts:
                raise ValueError(
                    f"{job.cache_key} remained invalid after {attempts} "
                    f"attempts: {validation_error}") from error
            continue
        return {
            "episode": job.episode_id,
            "id": job.item_id,
            "source_seq": job.source_seq,
            "source_message": job.source_message,
            "golden_text": job.text,
            "fingerprint": job.fingerprint,
            "model": model,
            "attributes": attributes,
            "raw_output": raw,
        }
    raise AssertionError("unreachable")


def _load_cache(path: Path, model: str) -> dict:
    if not path.exists():
        return {"version": CACHE_VERSION, "model": model, "records": {}}
    payload = json.loads(path.read_text())
    if (payload.get("version") != CACHE_VERSION
            or payload.get("model") != model
            or not isinstance(payload.get("records"), dict)):
        return {"version": CACHE_VERSION, "model": model, "records": {}}
    return payload


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def run_annotations(jobs: list[AnnotationJob], *, model: str,
                    workers: int, attempts: int, cache_path: Path,
                    force: bool = False) -> tuple[dict, list[tuple[str, str]]]:
    cache = _load_cache(cache_path, model)
    records = cache["records"]
    pending = [job for job in jobs if force or not (
        isinstance(records.get(job.cache_key), dict)
        and records[job.cache_key].get("fingerprint") == job.fingerprint)]
    failures: list[tuple[str, str]] = []
    started = time.time()
    print(f"oracle attributes: {len(jobs)} total, {len(pending)} pending, "
          f"model={model}, workers={workers}", flush=True)

    def save_record(job: AnnotationJob, record: dict) -> None:
        records[job.cache_key] = record
        cache["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        _write_json_atomic(cache_path, cache)

    if workers <= 1:
        futures = [(job, None) for job in pending]
        for done, (job, _) in enumerate(futures, 1):
            try:
                save_record(job, annotate_job(
                    job, model=model, attempts=attempts))
            except Exception as error:  # keep full-run progress resumable
                failures.append((job.cache_key, str(error)))
            if done % 10 == 0 or done == len(pending):
                print(f"  {done}/{len(pending)}  "
                      f"{time.time() - started:.0f}s", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            future_jobs = {
                pool.submit(annotate_job, job, model=model,
                            attempts=attempts): job
                for job in pending
            }
            for done, future in enumerate(as_completed(future_jobs), 1):
                job = future_jobs[future]
                try:
                    save_record(job, future.result())
                except Exception as error:  # keep full-run progress resumable
                    failures.append((job.cache_key, str(error)))
                if done % 10 == 0 or done == len(pending):
                    print(f"  {done}/{len(pending)}  "
                          f"{time.time() - started:.0f}s", flush=True)
    return records, failures


def apply_annotations(episodes: list[dict], records: dict, *,
                      require_complete: bool = True) -> int:
    jobs = annotation_jobs(episodes)
    by_key = {job.cache_key: job for job in jobs}
    missing = [key for key, job in by_key.items()
               if not isinstance(records.get(key), dict)
               or records[key].get("fingerprint") != job.fingerprint
               or not isinstance(records[key].get("attributes"), dict)]
    if require_complete and missing:
        raise ValueError(
            f"cannot apply incomplete attributes: {len(missing)} missing or "
            f"stale; first={missing[:5]}")
    changed = 0
    for episode in episodes:
        for node in episode["ground_truth"]["requirements"]:
            key = f"{episode['id']}:{node['id']}"
            job = by_key[key]
            record = records.get(key)
            if (not isinstance(record, dict)
                    or record.get("fingerprint") != job.fingerprint
                    or not isinstance(record.get("attributes"), dict)):
                continue
            attributes = effective_attributes(job, record)
            if any(field not in attributes for field in ATTRIBUTE_FIELDS):
                raise ValueError(f"{key} has incomplete attributes")
            before = {field: node.get(field) for field in ATTRIBUTE_FIELDS}
            node.update({field: attributes[field]
                         for field in ATTRIBUTE_FIELDS})
            changed += before != attributes
    return changed


def write_episode_files(episodes: list[dict]) -> None:
    directory = CASES / "episodes"
    for episode in episodes:
        path = directory / f"{episode['id']}.json"
        path.write_text(
            json.dumps(episode, ensure_ascii=False, indent=2) + "\n")


def audit_summary(records: dict, jobs: list[AnnotationJob]) -> dict:
    valid_jobs = [job for job in jobs
                  if isinstance(records.get(job.cache_key), dict)
                  and records[job.cache_key].get("fingerprint")
                  == job.fingerprint]
    attributes = [effective_attributes(job, records[job.cache_key])
                  for job in valid_jobs]
    work_kinds = Counter(
        kind for value in attributes for kind in value["work_kinds"])
    low_confidence = [job.cache_key
                      for job, value in zip(valid_jobs, attributes)
                      if value["confidence"] <= 5]
    global_ids = [job.cache_key
                  for job, value in zip(valid_jobs, attributes)
                  if value["scope_mode"] == "global"]
    return {
        "records": len(valid_jobs),
        "scope_modes": dict(Counter(
            value["scope_mode"] for value in attributes)),
        "buckets": dict(Counter(value["bucket"] for value in attributes)),
        "work_kinds": dict(work_kinds.most_common()),
        "global_ids": global_ids,
        "low_confidence_ids": low_confidence,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Add live Extractor attributes to E1 golden items")
    parser.add_argument("--episodes", default="",
                        help="comma-separated episode ids; default all 12")
    parser.add_argument("--model", default=ATTRIBUTE_MODEL)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0,
                        help="smoke-test only; --apply requires a full run")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--apply", action="store_true",
                        help="write validated attributes into episode JSON")
    parser.add_argument(
        "--cache", type=Path,
        default=RUN_DIR / "oracle-attributes-glm-5.3.json")
    args = parser.parse_args(argv)
    if args.apply and args.limit:
        parser.error("--apply cannot be combined with --limit")

    episodes = load_episodes(args.episodes)
    jobs = annotation_jobs(episodes)
    if args.limit:
        jobs = jobs[:max(0, args.limit)]
    records, failures = run_annotations(
        jobs, model=args.model.strip() or ATTRIBUTE_MODEL,
        workers=max(1, args.workers), attempts=max(1, args.attempts),
        cache_path=args.cache, force=args.force)
    summary = audit_summary(records, jobs)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if failures:
        for key, error in failures:
            print(f"FAILED {key}: {error}", flush=True)
        raise SystemExit(f"{len(failures)} annotation(s) failed; rerun resumes")
    if args.apply:
        changed = apply_annotations(episodes, records, require_complete=True)
        write_episode_files(episodes)
        print(f"wrote {changed} changed golden items across "
              f"{len(episodes)} episode files", flush=True)


if __name__ == "__main__":
    main()
