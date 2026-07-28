"""Harvest candidate atoms from the licence-cleared sources into
bench/gen/harvest/<source>.jsonl — which is GITIGNORED. Source text never
enters the repo: the generator consumes skeletons (structured propositions),
and versioned artifacts carry only {source_id, url, licence, use} provenance.

Source list and budgets follow the adjudication table in
docs/2026-07-26-bench-scaleup-spec.md §1 verbatim. A fetcher that fails logs
a SHORTFALL and returns empty rather than aborting the run — the report at
the end says exactly which budget went unfilled, because a silently smaller
corpus reads as "covered everything" when it didn't.

    uv run python -m bench.gen.harvest
"""
import html
import json
import re
from pathlib import Path

import httpx

HARVEST = Path(__file__).resolve().parent / "harvest"

# words that mark a delivery-shaped constraint (how to deliver), used only to
# cut LLM spend before SKELETONISE — the real filter is the skeleton G1 gate
_DELIVERY = re.compile(
    r"\b(word|words|length|format|tone|style|bullet|list|heading|paragraph|"
    r"sentence|concise|summar|cite|citation|table|markdown|json|code|comment|"
    r"uppercase|lowercase|capitali[sz]|emoji|language|begin|end with|start|"
    r"first|avoid|never|always|use|keep|include|exclude|order|structure|"
    r"section|title|line|column|indent|space|abbreviat|acronym|contraction|"
    r"active voice|passive|person|pronoun|date|number|numeral|unit|quote|"
    r"punctuat|comma|period|hyphen|char)", re.I)

# content-boundness markers: these are the atoms the suite must NOT store
_CONTENT = re.compile(r"NAME_\d|\bessay\b|\bpoem\b|\bstory\b|\bsong\b|"
                      r"\brecipe\b|\blyrics\b", re.I)


def _clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", s).strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _keep(s: str) -> bool:
    return (30 <= len(s) <= 300 and _DELIVERY.search(s)
            and not _CONTENT.search(s))


def _get(url: str, timeout: float = 30) -> str:
    r = httpx.get(url, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _rows(dataset: str, config: str, split: str, n: int) -> list[dict]:
    out = []
    for offset in range(0, n, 100):
        url = (f"https://datasets-server.huggingface.co/rows?"
               f"dataset={dataset}&config={config}&split={split}"
               f"&offset={offset}&length=100")
        out += [r["row"] for r in json.loads(_get(url))["rows"]]
    return out


# ---------------------------------------------------------------------------
# fetchers — each returns list[dict(raw, source, license, url)]
# ---------------------------------------------------------------------------

def fetch_google_styleguide() -> list[dict]:
    files = {
        "pyguide": "https://raw.githubusercontent.com/google/styleguide/gh-pages/pyguide.md",
        "shellguide": "https://raw.githubusercontent.com/google/styleguide/gh-pages/shellguide.md",
        "docguide": "https://raw.githubusercontent.com/google/styleguide/gh-pages/docguide/style.md",
    }
    out = []
    for name, url in files.items():
        text = _get(url)
        text = re.sub(r"```.*?```", " ", text, flags=re.S)     # drop code blocks
        for s in _sentences(_clean(text)):
            if _keep(s):
                out.append({"raw": s, "source": f"google-styleguide/{name}",
                            "license": "CC-BY-3.0", "url": url})
    return out


def fetch_pep8() -> list[dict]:
    text = _get("https://peps.python.org/pep-0008/")
    body = text.split("<section", 1)[-1]
    return [{"raw": s, "source": "pep8", "license": "public-domain",
             "url": "https://peps.python.org/pep-0008/"}
            for s in _sentences(_clean(body)) if _keep(s)]


def fetch_devdocs_highlights() -> list[dict]:
    text = _get("https://developers.google.com/style/highlights")
    items = re.findall(r"<li[^>]*>(.*?)</li>", text, flags=re.S)
    out = []
    for it in items:
        s = _clean(it)
        if _keep(s):
            out.append({"raw": s, "source": "google-devdocs-style",
                        "license": "CC-BY-4.0",
                        "url": "https://developers.google.com/style/highlights"})
    return out


def fetch_govuk() -> list[dict]:
    url = ("https://guidance.publishing.service.gov.uk/"
           "writing-to-gov-uk-standards/style-guides/a-to-z-style-guide/")
    text = _get(url)
    items = re.findall(r"<p[^>]*>(.*?)</p>", text, flags=re.S)
    out = []
    for it in items:
        s = _clean(it)
        if _keep(s):
            out.append({"raw": s, "source": "govuk-a-to-z",
                        "license": "OGL-3.0", "url": url})
    return out


def fetch_commit_family() -> list[dict]:
    out = []
    for name, lic, url in (
            ("conventional-commits", "CC-BY-3.0",
             "https://www.conventionalcommits.org/en/v1.0.0/"),
            ("keep-a-changelog", "MIT",
             "https://keepachangelog.com/en/1.1.0/"),
            ("semver", "CC-BY-3.0",
             "https://raw.githubusercontent.com/semver/semver/master/semver.md")):
        try:
            text = _get(url)
        except httpx.HTTPError as e:
            print(f"SHORTFALL {name}: {e}")
            continue
        if url.endswith(".md"):
            text = re.sub(r"```.*?```", " ", text, flags=re.S)
        for s in _sentences(_clean(text)):
            if _keep(s):
                out.append({"raw": s, "source": name, "license": lic,
                            "url": url})
    return out


def fetch_ifeval_templates() -> list[dict]:
    url = ("https://raw.githubusercontent.com/google-research/google-research/"
           "master/instruction_following_eval/instructions.py")
    text = _get(url)
    descs = re.findall(r'_description\s*=\s*\(\s*((?:"[^"]*"\s*)+)\)', text)
    out = []
    for d in descs:
        s = " ".join(re.findall(r'"([^"]*)"', d))
        s = _clean(s)
        if 20 <= len(s) <= 300:
            out.append({"raw": s, "source": "ifeval-templates",
                        "license": "Apache-2.0", "url": url})
    return out


def fetch_wildifeval(budget_rows: int = 1500) -> list[dict]:
    rows = _rows("gililior%2Fwild-if-eval", "default", "test", budget_rows)
    out = []
    for r in rows:
        for c in r.get("decomposition") or []:
            s = _clean(c)
            if _keep(s):
                out.append({"raw": s, "source": "wild-if-eval",
                            "license": "Apache-2.0",
                            "url": "https://huggingface.co/datasets/gililior/wild-if-eval",
                            "conversation_id": r.get("conversation_id")})
    return out


def fetch_infobench() -> list[dict]:
    rows = _rows("kqsong%2FInFoBench", "default", "train", 500)
    out = []
    for r in rows:
        for c in r.get("decomposed_questions") or []:
            s = _clean(c)
            if _keep(s):
                out.append({"raw": s, "source": "infobench",
                            "license": "MIT",
                            "url": "https://huggingface.co/datasets/kqsong/InFoBench"})
    return out


def fetch_prism() -> list[dict]:
    """Human-written fields only (CC BY 4.0 column); model text is NC and
    never touched. ~64% of PRISM is value/safety content — those are exactly
    the distractor pool, kept but tagged content=True."""
    rows = _rows("HannahRoseKirk%2Fprism-alignment", "survey", "train", 400)
    out = []
    for r in rows:
        s = _clean(r.get("system_string") or "")
        if 30 <= len(s) <= 400:
            out.append({"raw": s, "source": "prism/system_string",
                        "license": "CC-BY-4.0",
                        "url": "https://huggingface.co/datasets/HannahRoseKirk/prism-alignment",
                        "content": not bool(_DELIVERY.search(s))})
    return out


FETCHERS = {
    "google-styleguide": fetch_google_styleguide,
    "pep8": fetch_pep8,
    "google-devdocs": fetch_devdocs_highlights,
    "govuk": fetch_govuk,
    "commit-family": fetch_commit_family,
    "ifeval-templates": fetch_ifeval_templates,
    "wild-if-eval": fetch_wildifeval,
    "infobench": fetch_infobench,
    "prism": fetch_prism,
}


def main():
    HARVEST.mkdir(exist_ok=True)
    total = 0
    for name, fn in FETCHERS.items():
        try:
            items = fn()
        except Exception as e:                      # noqa: BLE001 — report, don't die
            print(f"SHORTFALL {name}: {type(e).__name__}: {e}")
            items = []
        p = HARVEST / f"{name}.jsonl"
        p.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n"
                             for i in items))
        total += len(items)
        print(f"{name:20s} {len(items):5d} -> {p.name}")
    print(f"total candidates: {total}")


if __name__ == "__main__":
    main()
