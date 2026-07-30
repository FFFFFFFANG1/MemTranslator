"""Controlled scope vocabulary (2026-07-29).

Scope was a dead field: values measured on one real replay store included
task=script, task=python脚本, task=code documentation and
task=code_documentation — four spellings across two dimensions. The scope
filter string-compares, and the hotkey context rarely supplies dimensions,
so unnormalised free text could never match anything mechanically.

Normalisation here is SPELLING-level only: casing, separators, and
unambiguous zh→en value translation. It deliberately does NOT fold sibling
categories into each other — the same store carried a 752-word cap scoped
to blog and structural rules scoped to article; an ontology that merges
blog into article would fire the wrong caps. When in doubt a value stays
as its slug.
"""
import re

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


def _slug(value: str) -> str:
    return _SEP.sub("_", value.strip().lower()).strip("_")


def normalize_value(value: str) -> str:
    s = _slug(str(value))
    s = _VALUE_ZH.get(s, s)
    return _VALUE_ALIASES.get(s, s)


def normalize_scope(scope: dict | None) -> dict:
    if not scope:
        return {}
    out = {}
    for k, v in scope.items():
        key = _slug(str(k))
        key = _KEY_ALIASES.get(key, key)
        out[key] = normalize_value(v)
    return out


# ---------------------------------------------------------------------------
# Comparison-side vocabulary (2026-07-30, weak-backbone iteration R6).
#
# Measured on a qwen-built chained store: extraction invents free-form task
# values ("headings_and_subheadings", "client_facing_communications") that
# no context can ever equal, so the scope filter turned those rules
# permanently unreachable. Exclusion now requires BOTH sides to speak the
# controlled vocabulary — an uninterpretable value degrades to "unknown
# dimension, keep the entry", the same never-exclude-on-missing principle
# the filter already follows. Storage stays untouched (spelling-level
# doctrine above); only the comparison relaxes.
#
# The code family folds for comparison: a python_script rule governs a
# code-write task — one activity, many spellings (mirrors kinds.py's
# taxonomy). Prose genres deliberately stay distinct (blog caps must not
# fire on articles — the doctrine's original counterexample).
_TASK_VOCAB = (set(_VALUE_ZH.values()) | set(_VALUE_ALIASES.values())
               | {"email", "code", "code_write", "script", "doc", "article",
                  "blog", "report", "weekly_report", "meeting",
                  "meeting_minutes", "postmortem", "translation", "paper",
                  "research", "slide", "summary"})
_CODE_FAMILY = {"code", "code_write", "coding", "script",
                "python_script", "shell_script"}


def task_comparable(want: str, have: str) -> bool | None:
    """None = cannot compare (either side out of vocabulary) → caller keeps
    the entry; True/False = a real vocabulary-level verdict."""
    if want not in _TASK_VOCAB or have not in _TASK_VOCAB:
        return None
    if want == have:
        return True
    if want in _CODE_FAMILY and have in _CODE_FAMILY:
        return True
    return False
