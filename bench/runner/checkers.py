"""Mechanical checks — deterministic, zero-LLM. Each returns (ok, why)."""
import re

_CJK = re.compile(r"[一-鿿]")


def _lang(s: str) -> str:
    """zh if CJK chars form a meaningful share of the text, else en.
    Coarse on purpose: the bench only asserts zh-in → zh-out and en-in →
    en-out; mixed borderline inputs should not use this checker."""
    cjk = len(_CJK.findall(s))
    return "zh" if cjk >= max(4, 0.1 * len(s)) else "en"


def contains_all(args, polished, case_input):
    missing = [k for k in args["keywords"] if k not in polished]
    return (not missing, f"missing keywords: {missing}" if missing else "ok")


def not_contains(args, polished, case_input):
    hit = [b for b in args["banned"] if b in polished]
    return (not hit, f"banned substrings present: {hit}" if hit else "ok")


def same_language(args, polished, case_input):
    want, got = _lang(case_input), _lang(polished)
    return (want == got, f"input lang {want}, polished lang {got}")


_REGISTRY = {
    "contains_all": contains_all,
    "not_contains": not_contains,
    "same_language": same_language,
}


def run_check(name: str, args: dict, *, polished: str,
              case_input: str) -> tuple[bool, str]:
    return _REGISTRY[name](args, polished, case_input)
