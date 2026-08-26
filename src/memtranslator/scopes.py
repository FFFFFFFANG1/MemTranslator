"""Scope and work-kind spelling normalisation (2026-07-29 / 2026-08-11).

Scope is a free key:value narrowness dict (audience, app, language, …).
Genre / work class lives in Requirement.kinds, not in scope.task.

Normalisation is SPELLING-level only: casing, separators, and unambiguous
zh→en value translation. Sibling categories stay distinct — the same store
carried a 752-word cap scoped to blog and structural rules scoped to
article; an ontology that merges blog into article would fire the wrong
caps. When in doubt a value stays as its slug.
"""
from __future__ import annotations

import re

from memtranslator.schema import WORK_KIND_ANY, WORK_KINDS

# Whole-value zh→en translations, 1:1 and unambiguous only. Compound values
# are handled by slugging first, then translating exact matches.
_VALUE_ZH = {
    "邮件": "email", "写信": "email",
    "代码": "code",
    "脚本": "script", "python脚本": "python_script", "shell脚本": "shell_script",
    "文档": "doc",
    "文章": "article", "博客": "blog",
    "报告": "report", "周报": "weekly_report",
    "会议": "meeting", "会议纪要": "meeting_minutes",
    "复盘": "postmortem", "事故复盘": "postmortem",
    "翻译": "translation",
    "论文": "paper", "调研": "research",
}

# Spelling variants of the same value (post-slug), folded to one canonical.
_VALUE_ALIASES = {
    "emails": "email", "mail": "email",
    "coding": "code",
    "scripts": "script",
    "docs": "doc", "document": "doc", "documentation": "doc",
    "articles": "article", "blog_post": "blog",
    "reports": "report",
    "meetings": "meeting", "minutes": "meeting_minutes",
    "postmortems": "postmortem", "incident_report": "postmortem",
}

_KEY_ALIASES = {"lang": "language", "语言": "language", "任务": "task",
                "recipient": "audience", "收件人": "audience"}

_SEP = re.compile(r"[\s\-/]+")

# Values that historically lived in scope.task as the genre channel and now
# belong in kinds. Seed work kinds plus common fine subtypes from the old
# task vocabulary.
_GENRE_FROM_SCOPE_TASK = (
    set(WORK_KINDS) | {WORK_KIND_ANY}
    | {"code_write", "weekly_report", "meeting_minutes", "script",
       "python_script", "shell_script", "doc", "article", "blog",
       "meeting", "translation", "paper", "research", "slide", "summary"}
)


def _slug(value: str) -> str:
    return _SEP.sub("_", value.strip().lower()).strip("_")


def normalize_value(value: str) -> str:
    s = _slug(str(value))
    s = _VALUE_ZH.get(s, s)
    return _VALUE_ALIASES.get(s, s)


def normalize_kind(value: str) -> str:
    """Spelling-normalise one work-kind slug."""
    value = normalize_value(value)
    # The LLM-facing protocol says ``all``; storage retains the historical
    # ``any`` spelling so existing stores and matching code stay compatible.
    return WORK_KIND_ANY if value == "all" else value


def normalize_scope(scope: dict | None) -> dict:
    if not scope:
        return {}
    out = {}
    for k, v in scope.items():
        key = _slug(str(k))
        key = _KEY_ALIASES.get(key, key)
        out[key] = normalize_value(v)
    return out


def _kind_coverage(kinds: list[str] | None) -> frozenset[str] | None:
    """Normalised coverage: None is broad; an empty set is legacy unknown."""
    values = {normalize_kind(kind) for kind in (kinds or [])
              if str(kind).strip()}
    if not values:
        return frozenset()
    if values & {WORK_KIND_ANY, "agent_response"}:
        return None
    # The read path intentionally treats these as one prose family.
    if values & {"report", "postmortem"}:
        values -= {"report", "postmortem"}
        values.add("__prose__")
    return frozenset(values)


def applicability_narrows(candidate_scope: dict | None,
                          candidate_kinds: list[str] | None,
                          target_scope: dict | None,
                          target_kinds: list[str] | None) -> bool:
    """Whether storing candidate metadata would cover less than target.

    Consolidation uses this as a state-safety guard. Compatibility remains a
    separate semantic check: this helper only detects a broad-to-narrow loss,
    such as adding a scope dimension or replacing ``any`` with ``report``.
    """
    candidate_scope = normalize_scope(candidate_scope)
    target_scope = normalize_scope(target_scope)
    scope_narrows = any(
        key not in target_scope for key in candidate_scope)

    candidate_coverage = _kind_coverage(candidate_kinds)
    target_coverage = _kind_coverage(target_kinds)
    if (candidate_coverage == frozenset()
            or target_coverage == frozenset()):
        # Empty metadata is unknown, not proof that the old rule was broad.
        kinds_narrow = False
    elif candidate_coverage is None:
        kinds_narrow = False
    elif target_coverage is None:
        kinds_narrow = True
    else:
        kinds_narrow = candidate_coverage < target_coverage
    return scope_narrows or kinds_narrow


def is_genre_scope_task(value: str) -> bool:
    """True when a scope.task value is genre that should live in kinds."""
    return normalize_kind(value) in _GENRE_FROM_SCOPE_TASK


def migrate_genre_from_scope(req):
    """Move genre out of scope.task into kinds (in place). Returns req.

    - empty kinds + genre task → kinds=[task], drop task from scope
    - kinds set and task is genre (dual tag or exact member) → drop task
    - non-genre / unknown free task values stay in scope
    """
    scope = normalize_scope(req.scope)
    task = scope.get("task")
    kinds = [normalize_kind(k) for k in (req.kinds or []) if str(k).strip()]
    kinds = list(dict.fromkeys(kinds))
    if task and is_genre_scope_task(task):
        if not kinds:
            kinds = [task]
        scope = {k: v for k, v in scope.items() if k != "task"}
    req.scope = scope
    req.kinds = kinds
    # Under the new protocol global means every output must obey the rule.
    # Migration may demote an invalid global declaration, but must never
    # promote an explicitly retrieval-only scoped rule merely because its
    # optional applicability metadata is incomplete.
    explicit_all = WORK_KIND_ANY in kinds
    if not (req.scope_mode == "global" and explicit_all
            and not scope and not req.applies_when):
        req.scope_mode = "scoped"
    return req
