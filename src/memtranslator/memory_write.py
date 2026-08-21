"""Candidate-first memory write orchestration (route A).

Flow: inventory → extract candidates → retrieve cases → CASE consolidate → ops.
Candidate extract lives in extraction.py; CASE consolidator in consolidate.py.
"""
from __future__ import annotations

from memtranslator import llm
from memtranslator.config import GEN_TEMPERATURE, MODELS
from memtranslator.consolidate import (
    CONSOLIDATION_SYSTEM,
    CandidateCase,
    TOP_K,
    build_consolidation_user_prompt,
    parse_consolidation_output,
)
from memtranslator.extraction import (
    CANDIDATE_EXTRACTION_SYSTEM,
    POTENTIAL_CHANGE,
    POTENTIAL_NEW,
    CandidateDiscard,
    CandidateItem,
    MemoryCandidate,
    build_candidate_user_prompt,
    known_work_kinds,
    parse_candidate_decisions,
    parse_candidate_output,
)
from memtranslator.retrieval import (
    EmbeddingRanker,
    default_embedding_ranker,
    flatten_memory_fields,
    flatten_requirement,
    hybrid_order,
    prepare_requirements,
)
from memtranslator.schema import Requirement


def _candidate_trace(candidate: MemoryCandidate) -> dict:
    item = candidate.item
    return {
        "id": candidate.id,
        "kind": candidate.kind,
        "change_mode": candidate.change_mode,
        "target_query": candidate.change_candidate,
        "item": ({
            "text": item.text,
            "bucket": item.bucket,
            "scope_mode": item.scope_mode,
            "applies_when": item.applies_when,
            "work_kinds": item.work_kinds,
            "key": item.key,
            "confidence": item.confidence,
        } if item is not None else None),
        "bucket": candidate.bucket,
        "scope_mode": candidate.scope_mode,
        "applies_when": candidate.applies_when,
        "work_kinds": candidate.work_kinds,
        "key": candidate.key,
        "confidence": candidate.confidence,
        "source_signal_ids": candidate.source_signal_ids,
        "source_texts": candidate.source_texts,
        "ordinal": candidate.ordinal,
    }


def _case_trace(case: CandidateCase) -> dict:
    return {
        "candidate": _candidate_trace(case.candidate),
        "memories": [memory.to_dict() for memory in case.memories],
    }

def _candidate_search_text(candidate: MemoryCandidate) -> str:
    item = candidate.item
    return flatten_memory_fields(
        candidate.retrieval_query,
        work_kinds=(item.work_kinds if item is not None
                    else candidate.work_kinds),
        applies_when=(item.applies_when if item is not None
                      else candidate.applies_when),
        scope_mode=(item.scope_mode if item is not None
                    else candidate.scope_mode),
        key=(item.key if item is not None else candidate.key))


def retrieve_cases(candidates: list[MemoryCandidate],
                   existing: list[Requirement], *,
                   embedding_ranker: EmbeddingRanker | None = None
                   ) -> list[CandidateCase]:
    """Retrieve fixed top-3 CASE memories through the shared flattened index."""
    ranker = (embedding_ranker if embedding_ranker is not None
              else default_embedding_ranker())
    documents = [flatten_requirement(requirement) for requirement in existing]
    prepare_requirements(existing, embedding_ranker=ranker)
    cases = []
    for candidate in candidates:
        query = _candidate_search_text(candidate)
        order = hybrid_order(query, documents,
                             embedding_texts=documents,
                             embedding_ranker=ranker)
        cases.append(CandidateCase(
            candidate, [existing[idx] for idx in order[:TOP_K]]))
    return cases


def run_memory_write(signals: list[str], existing: list[Requirement], *,
                     embedding_ranker: EmbeddingRanker | None = None) -> dict:
    """Run the two-call candidate-first A path."""
    writer = MODELS.get("writer") or MODELS["translator"]
    inventory = known_work_kinds(existing)
    extractor_prompt = build_candidate_user_prompt(signals, inventory)
    raw_candidates = llm.complete(
        writer, CANDIDATE_EXTRACTION_SYSTEM,
        extractor_prompt,
        max_tokens=llm.budget_for(writer, 1500),
        temperature=GEN_TEMPERATURE)
    candidates, discards, flags = parse_candidate_decisions(
        raw_candidates, signals)
    attempts = [{"raw_output": raw_candidates, "flags": list(flags)}]
    if flags:
        repair_prompt = (
            extractor_prompt
            + "\n\nVALIDATION RETRY: Your previous JSON violated the output "
              "contract. Preserve every candidate/discard decision and its "
              "meaning; correct only malformed fields. In particular, never "
              "emit scoped + work_kinds=[\"all\"] + applies_when=null: choose "
              "a concrete recurring work kind, or supply the real semantic "
              "condition. Return the full corrected JSON array.\n\n"
            + "PREVIOUS OUTPUT:\n" + raw_candidates
            + "\n\nVALIDATION ERRORS:\n"
            + "\n".join(f"- {flag}" for flag in flags)
            + "\n\nJSON:")
        repaired_raw = llm.complete(
            writer, CANDIDATE_EXTRACTION_SYSTEM,
            repair_prompt,
            max_tokens=llm.budget_for(writer, 1500),
            temperature=GEN_TEMPERATURE)
        repaired_candidates, repaired_discards, repaired_flags = \
            parse_candidate_decisions(repaired_raw, signals)
        attempts.append({"raw_output": repaired_raw,
                         "flags": list(repaired_flags)})
        if len(repaired_flags) < len(flags):
            raw_candidates = repaired_raw
            candidates = repaired_candidates
            discards = repaired_discards
            flags = repaired_flags
    discard_audit = [{"reason": discard.reason,
                      "sources": discard.source_signal_ids,
                      "source_texts": discard.source_texts}
                     for discard in discards]
    trace = {
        "input_signals": list(signals),
        "extractor": {
            "model_visible_prompt": extractor_prompt,
            "raw_output": raw_candidates,
            "attempts": attempts,
            "candidates": [_candidate_trace(candidate)
                           for candidate in candidates],
            "discards": discard_audit,
            "flags": list(flags),
        },
        "consolidator": None,
        "ops": [],
    }
    public_discards = [{"reason": discard["reason"],
                        "sources": discard["sources"]}
                       for discard in discard_audit]
    if not candidates:
        return {"ops": [], "flags": flags, "candidate_count": 0,
                "discards": public_discards, "trace": trace}

    cases = retrieve_cases(candidates, existing,
                           embedding_ranker=embedding_ranker)
    consolidator_prompt = build_consolidation_user_prompt(cases)
    raw_decisions = llm.complete(
        writer, CONSOLIDATION_SYSTEM,
        consolidator_prompt,
        max_tokens=llm.budget_for(writer, 500 + 80 * len(cases)),
        temperature=GEN_TEMPERATURE)
    ops, decision_flags = parse_consolidation_output(raw_decisions, cases)
    trace["consolidator"] = {
        "model_visible_prompt": consolidator_prompt,
        "cases": [_case_trace(case) for case in cases],
        "raw_output": raw_decisions,
        "flags": list(decision_flags),
    }
    trace["ops"] = list(ops)
    return {"ops": ops, "flags": flags + decision_flags,
            "candidate_count": len(candidates),
            "discards": public_discards, "trace": trace}


__all__ = [
    "CANDIDATE_EXTRACTION_SYSTEM",
    "CONSOLIDATION_SYSTEM",
    "POTENTIAL_CHANGE",
    "POTENTIAL_NEW",
    "TOP_K",
    "CandidateCase",
    "CandidateDiscard",
    "CandidateItem",
    "MemoryCandidate",
    "build_candidate_user_prompt",
    "build_consolidation_user_prompt",
    "known_work_kinds",
    "parse_candidate_decisions",
    "parse_candidate_output",
    "parse_consolidation_output",
    "retrieve_cases",
    "run_memory_write",
]
