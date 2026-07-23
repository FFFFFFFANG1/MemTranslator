"""Join submit events (from agent hooks) with translate events.

No markers are ever embedded in text — the daemon holds both sides of the
join, so a time window plus text similarity is enough. Classification feeds
two consumers: acceptance metrics for the rewrite loop, and the v1
extraction corpus.
"""
from difflib import SequenceMatcher

JOIN_WINDOW_S = 15 * 60
EDIT_SIM_THRESHOLD = 0.55
REVERT_SIM_THRESHOLD = 0.85


def _norm(s: str) -> str:
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def classify_submit(text: str, at: float, translate_events: list[dict]) -> dict:
    """Returns {classification, matched_translate_id, similarity}.

    classification ∈ accepted_verbatim | edited_after_polish | reverted | natural
    """
    candidates = [e for e in translate_events
                  if e.get("kind") == "translate"
                  and e.get("decision") == "apply"
                  and e.get("polished")
                  and 0 <= at - e["at"] <= JOIN_WINDOW_S]
    best = None
    for e in reversed(candidates):  # newest first
        sim_polished = _sim(text, e["polished"])
        sim_original = _sim(text, e.get("original", ""))
        score = max(sim_polished, sim_original)
        if best is None or score > best[0] + 1e-9:
            best = (score, sim_polished, sim_original, e)
    if best is None:
        return {"classification": "natural",
                "matched_translate_id": None, "similarity": None}
    score, sim_polished, sim_original, event = best
    tid = event["translate_id"]
    if _norm(text) == _norm(event["polished"]):
        return {"classification": "accepted_verbatim",
                "matched_translate_id": tid, "similarity": 1.0}
    if sim_original >= REVERT_SIM_THRESHOLD and sim_original >= sim_polished:
        return {"classification": "reverted",
                "matched_translate_id": tid, "similarity": sim_original}
    if sim_polished >= EDIT_SIM_THRESHOLD:
        return {"classification": "edited_after_polish",
                "matched_translate_id": tid, "similarity": sim_polished}
    return {"classification": "natural",
            "matched_translate_id": None, "similarity": None}
