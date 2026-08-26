"""Closed vocabularies and node types for the Suite E constraint graph.

Everything the relation algebra consumes is a selection from a closed set,
never free text. Two rules about the same thing that landed on different keys
would never conflict, so the supersede chain would silently vanish — key is a
multiple-choice question, not a fill-in (design §1.1). The one honest escape
hatch is value type "freeform": entries the annotator cannot fit into a typed
slot get no chain edges at all, so every edge that DOES exist was computed.

Scope discipline (M2 decision #1): every dimension must be EXPLICIT — a
concrete vocabulary value or the literal "ANY". A missing dimension is a
validation error, not a default. `None` = "whole universe" was the default
landing spot whenever the annotator lacked information, and a missed fill is a
DIRECTED bias: miss one side of a pair and the relation degrades to an
exception (nobody dies, zombies stay in gold); miss both and cross-language
rules kill each other as a fake CONTRADICTS. I1/I2/I3/I7 are all blind to the
second failure. Explicit-or-error turns a silent bias into a diffable event.

Scope is FOUR dimensions (spec §4.4): app, task, code_lang, nat_lang.
`recipient`/`artifact` were cut — the product cannot represent them, so they
would only ever feed BEHAVIOUR observations, and they can return as authoring
metadata without touching the algebra. The product's single `lang` field is
overloaded (zh-CN vs python ride the same key); the bench keeps the two
dimensions separate and PROJECTS when talking to the product — that projection
is a recorded distortion, see derive.to_product_scope.
"""
from dataclasses import dataclass, field

ANY = "ANY"

BUCKETS = ("task_goal", "reasoning_policy", "deliverables",
           "output_contract", "communication_style", "execution_policy")

# Graph-authoring only (2026-08-12): polarity/binding feed relate() for
# DUPLICATES vs CONTRADICTS. The live product Requirement schema does not
# store them; Suite E1 scoring never reads them. Kept here so existing
# episode JSON and the relation algebra stay reproducible.
POLARITIES = ("require", "prefer", "avoid", "prohibit")
BINDINGS = ("hard", "soft", "default", "suggestion")

# polarity sign: require/prefer demand the object, avoid/prohibit ban it
_POSITIVE = ("require", "prefer")

SCOPE_DIMS = ("app", "task", "code_lang", "nat_lang")

SCOPE_VOCAB = {
    "app": ("editor", "ide", "terminal", "docs-site", "slack",
            "email-client", "notebook", "cli"),
    "task": ("code-write", "code-review", "commit-msg", "release-note",
             "reference-page", "tutorial", "email", "chat-reply", "report",
             "paper-analysis", "slide", "spec", "postmortem", "data-analysis"),
    "code_lang": ("python", "java", "shell", "sql", "ts"),
    "nat_lang": ("zh-CN", "en-US", "en-GB", "ja-JP", "fr-FR", "ko-KR"),
}

# Key registry: facet.attribute, ~90 entries, NOT partitioned by bucket
# (M2 decision #2). Partitioning by bucket would turn every bucket
# misjudgement into a key-partition error, and relate() line one
# (`a.key != b.key → INDEPENDENT`) would delete the edge — measured bucket
# ambiguity is 23%, so that coupling is a standing edge-shredder.
KEY_REGISTRY = (
    # email
    "email.length", "email.tone", "email.signoff", "email.greeting",
    "email.language", "email.structure", "email.subject",
    # code
    "code.comments", "code.comment_language", "code.line_length",
    "code.header", "code.explanation", "code.tests", "code.naming",
    "code.error_handling", "code.dependencies", "code.type_hints",
    "code.language",
    # doc / report
    "doc.toc", "doc.length", "doc.structure", "doc.headings",
    "report.format", "report.length", "report.numbers", "report.sections",
    "report.conclusion_position", "report.audience",
    # summary
    "summary.length", "summary.structure", "summary.opening",
    # citation / evidence
    "citation.style", "citation.count", "citation.presence",
    "evidence.grounding", "evidence.sources",
    # format / rendering
    "format.lists", "format.tables", "format.markdown", "format.headings",
    "format.code_blocks", "format.emphasis", "format.line_width",
    # tone / register
    "tone.register", "tone.directness", "tone.emoji", "tone.hedging",
    # language
    "language.output", "language.mixing", "language.terminology",
    # length
    "length.max", "length.min", "length.paragraphs",
    # meeting
    "meeting.notes_format", "meeting.notes_order", "meeting.action_items",
    # research / analysis
    "research.task_verb", "research.comparison", "research.tradeoff_axes",
    "research.recommendation", "analysis.units", "analysis.uncertainty",
    "analysis.assumptions",
    # explanation
    "explanation.depth", "explanation.analogies", "explanation.steps",
    # workflow / execution
    "workflow.confirmation", "workflow.fidelity", "workflow.channel",
    "workflow.scope_of_change", "workflow.tools", "workflow.verification",
    # commit / review
    "commit.style", "commit.length", "review.ordering", "review.severity",
    # slides
    "slide.density", "slide.structure",
    # chat
    "chat.length", "chat.structure", "chat.restating",
    # style (rewrite-facing)
    "style.voice", "style.person", "style.bullets",
)

VALUE_TYPES = ("numeric", "enum", "lang", "bool", "set", "ordering",
               "freeform")

# enum domains are closed too — comparing values from different domains is a
# category error the algebra must refuse, not fuzz over
ENUM_DOMAINS = {
    "case_style": ("snake", "camel", "pascal", "kebab"),
    "register": ("formal", "casual", "neutral", "firm"),
    "format": ("bullets", "prose", "table", "numbered", "json", "markdown",
               "plain"),
    "channel": ("email", "slack", "ticket", "doc"),
    "verb": ("compare", "evaluate", "summarise", "recommend", "diagnose",
             "generate", "revise", "explain"),
    "position": ("first", "last", "inline", "none"),
    "depth": ("brief", "standard", "deep"),
}


@dataclass(frozen=True)
class Value:
    type: str
    num: float | None = None
    unit: str = ""
    cmp: str = ""                       # max | min | exact
    domain: str = ""
    val: str = ""
    tag: str = ""
    bool_val: bool | None = None
    op: str = ""                        # include | exclude
    items: tuple = ()
    before: str = ""
    after: str = ""


@dataclass(frozen=True)
class Coords:
    bucket: str
    key: str
    polarity: str
    binding: str
    value: Value
    scope: dict                          # dim → vocab value or ANY, ALL dims


@dataclass
class Constraint:
    cid: str
    text: str
    coords: Coords
    atom: dict = field(default_factory=dict)     # provenance, never published verbatim
    distinctive: str = ""                        # contrast token family anchor
    clause: str = ""                             # short appendable form (diff moves)
    alt_clause: str = ""                         # synonymous rewording (reword move)


def positive(polarity: str) -> bool:
    return polarity in _POSITIVE


def validate_scope(scope: dict) -> None:
    missing = [d for d in SCOPE_DIMS if d not in scope]
    if missing:
        raise ValueError(f"scope dims missing (explicit ANY required): "
                         f"{missing}")
    extra = [d for d in scope if d not in SCOPE_DIMS]
    if extra:
        raise ValueError(f"unknown scope dims: {extra}")
    for d, v in scope.items():
        if v != ANY and v not in SCOPE_VOCAB[d]:
            raise ValueError(f"scope {d}={v!r} not in vocabulary")


def validate_value(v: Value) -> None:
    if v.type not in VALUE_TYPES:
        raise ValueError(f"unknown value type: {v.type}")
    if v.type == "numeric":
        if v.num is None or v.cmp not in ("max", "min", "exact"):
            raise ValueError("numeric value needs num and cmp")
    elif v.type == "enum":
        if v.domain not in ENUM_DOMAINS:
            raise ValueError(f"unknown enum domain: {v.domain}")
        if v.val not in ENUM_DOMAINS[v.domain]:
            raise ValueError(f"{v.val!r} not in domain {v.domain}")
    elif v.type == "lang":
        if not v.tag:
            raise ValueError("lang value needs tag")
    elif v.type == "bool":
        if v.bool_val is None:
            raise ValueError("bool value needs bool_val")
    elif v.type == "set":
        if v.op not in ("include", "exclude") or not v.items:
            raise ValueError("set value needs op and items")
    elif v.type == "ordering":
        if not v.before or not v.after:
            raise ValueError("ordering value needs before/after")


def validate(c: Constraint) -> None:
    co = c.coords
    if co.bucket not in BUCKETS:
        raise ValueError(f"{c.cid}: unknown bucket {co.bucket}")
    if co.key not in KEY_REGISTRY:
        raise ValueError(f"{c.cid}: key {co.key!r} not in registry")
    if co.polarity not in POLARITIES:
        raise ValueError(f"{c.cid}: unknown polarity {co.polarity}")
    if co.binding not in BINDINGS:
        raise ValueError(f"{c.cid}: unknown binding {co.binding}")
    validate_value(co.value)
    validate_scope(co.scope)
