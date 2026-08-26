"""M2 acceptance: relation-algebra properties, exhaustive scope projection
equivalence (with the lang-overload divergence MEASURED, not hidden), fold
semantics, and eight planted defects that the lints must all catch."""
import random
from itertools import product

import pytest

from memtranslator.recall import _scope_ok

from bench.graph.derive import (Effect, fold, scope_compatible,
                                to_product_context, to_product_scope,
                                valid_at)
from bench.graph.invariants import (check_i1, check_i3, check_i5, check_i8,
                                    check_i9, check_i10, check_i11,
                                    lint_episode)
from bench.graph.relate import (A_EXCEPTS_B, B_EXCEPTS_A, CONTRADICTS,
                                DUPLICATES, INDEPENDENT, PARTIAL_CONFLICT,
                                relate, scope_relate)
from bench.graph.schema import (ANY, Constraint, Coords, Value, validate)


def _scope(**kw):
    s = {"app": ANY, "task": ANY, "code_lang": ANY, "nat_lang": ANY}
    s.update(kw)
    return s


def _c(cid, text, key="code.line_length", polarity="require",
       value=None, scope=None, bucket="output_contract"):
    return Constraint(
        cid=cid, text=text,
        coords=Coords(bucket=bucket, key=key, polarity=polarity,
                      binding="hard",
                      value=value or Value(type="numeric", num=96,
                                           unit="col", cmp="max"),
                      scope=scope or _scope()))


# ---------------------------------------------------------------------------
# relate(): pointwise semantics
# ---------------------------------------------------------------------------

def test_numeric_supersede_pair_contradicts():
    a = _c("a", "96 列折行")
    b = _c("b", "80 列折行", value=Value(type="numeric", num=80,
                                        unit="col", cmp="max"))
    assert relate(a, b) == CONTRADICTS


def test_same_value_duplicates():
    a = _c("a", "96 列折行")
    b = _c("b", "代码折到 96 列")
    assert relate(a, b) == DUPLICATES


def test_different_key_always_independent():
    a = _c("a", "96 列折行")
    b = _c("b", "96 列折行", key="length.max")
    assert relate(a, b) == INDEPENDENT


def test_nested_scope_opposed_is_exception_not_conflict():
    a = _c("a", "python 折 96", scope=_scope(code_lang="python"))
    b = _c("b", "折 80", value=Value(type="numeric", num=80,
                                     unit="col", cmp="max"))
    assert relate(a, b) == A_EXCEPTS_B
    assert relate(b, a) == B_EXCEPTS_A


def test_overlapping_scopes_opposed_is_partial_conflict():
    a = _c("a", "python 折 96", scope=_scope(code_lang="python"))
    b = _c("b", "editor 里折 80", scope=_scope(app="editor"),
           value=Value(type="numeric", num=80, unit="col", cmp="max"))
    assert relate(a, b) == PARTIAL_CONFLICT


def test_disjoint_scopes_independent():
    a = _c("a", "python 折 96", scope=_scope(code_lang="python"))
    b = _c("b", "java 折 80", scope=_scope(code_lang="java"),
           value=Value(type="numeric", num=80, unit="col", cmp="max"))
    assert relate(a, b) == INDEPENDENT


def test_freeform_never_joins_a_chain():
    a = _c("a", "96 列折行")
    b = _c("b", "看着办吧", value=Value(type="freeform"))
    assert relate(a, b) == INDEPENDENT


def test_polarity_sign_flip_on_same_value_is_opposed():
    a = _c("a", "要用 bullets", key="format.lists",
           value=Value(type="enum", domain="format", val="bullets"))
    b = _c("b", "别用 bullets", key="format.lists", polarity="prohibit",
           value=Value(type="enum", domain="format", val="bullets"))
    assert relate(a, b) == CONTRADICTS


def test_include_exclude_set_clash():
    a = _c("a", "必须带环比", key="report.numbers",
           value=Value(type="set", op="include", items=("环比",)))
    b = _c("b", "别放环比", key="report.numbers",
           value=Value(type="set", op="exclude", items=("环比",)))
    assert relate(a, b) == CONTRADICTS


# ---------------------------------------------------------------------------
# relate(): algebraic properties, randomized over the closed vocab
# ---------------------------------------------------------------------------

_MIRROR = {A_EXCEPTS_B: B_EXCEPTS_A, B_EXCEPTS_A: A_EXCEPTS_B}


def _random_constraint(rng, n):
    keys = ("code.line_length", "format.lists", "email.length")
    vals = [Value(type="numeric", num=rng.choice((80, 96, 120)),
                  unit="col", cmp="max"),
            Value(type="enum", domain="format",
                  val=rng.choice(("bullets", "prose"))),
            Value(type="freeform")]
    dims = {}
    for d, choices in (("app", ("editor", "cli")),
                       ("task", ("email", "report")),
                       ("code_lang", ("python", "java")),
                       ("nat_lang", ("zh-CN", "en-US"))):
        dims[d] = rng.choice((ANY, ANY) + choices)
    return _c(f"r{n}", f"rule {n}", key=rng.choice(keys),
              polarity=rng.choice(("require", "prohibit")),
              value=rng.choice(vals), scope=dims)


def test_relate_is_mirror_symmetric():
    rng = random.Random(42)
    cs = [_random_constraint(rng, i) for i in range(60)]
    for a in cs:
        for b in cs:
            ab, ba = relate(a, b), relate(b, a)
            assert ba == _MIRROR.get(ab, ab), (a.coords, b.coords)


def test_scope_relate_identity_and_any_box():
    s = _scope(task="email")
    assert scope_relate(s, s) == "EQUAL"
    assert scope_relate(s, _scope()) == "A_WITHIN_B"
    assert scope_relate(_scope(), s) == "B_WITHIN_A"


# ---------------------------------------------------------------------------
# schema validation: explicit-ANY discipline
# ---------------------------------------------------------------------------

def test_missing_scope_dim_is_an_error_not_a_default():
    c = _c("a", "x")
    object.__setattr__(c.coords, "scope", {"app": ANY, "task": ANY,
                                           "code_lang": ANY})   # nat_lang gone
    with pytest.raises(ValueError, match="nat_lang"):
        validate(c)


def test_unregistered_key_rejected():
    c = _c("a", "x")
    object.__setattr__(c.coords, "key", "code.linelength")      # typo
    with pytest.raises(ValueError, match="registry"):
        validate(c)


# ---------------------------------------------------------------------------
# scope projection ↔ product _scope_ok: exhaustive, divergence measured
# ---------------------------------------------------------------------------

def test_scope_projection_equivalence_exhaustive():
    """Over a reduced cartesian product (3 options/dim on both sides,
    6561 pairs): the bench semantics and the projected product semantics
    must agree EXCEPT exactly where the product's single overloaded `lang`
    field cannot represent the pair — scope and context carrying concrete
    lang values of DIFFERENT types. Those divergences are the recorded
    distortion of spec §4.4; anything outside that set is a bug."""
    scope_opts = {"app": (ANY, "editor", "cli"),
                  "task": (ANY, "email", "report"),
                  "code_lang": (ANY, "python", "java"),
                  "nat_lang": (ANY, "zh-CN", "en-US")}
    ctx_opts = {"app": (None, "editor", "cli"),
                "task": (None, "email", "report"),
                "code_lang": (None, "python", "java"),
                "nat_lang": (None, "zh-CN", "en-US")}

    dims = ("app", "task", "code_lang", "nat_lang")
    divergent = 0
    total = 0
    for sv in product(*(scope_opts[d] for d in dims)):
        scope = dict(zip(dims, sv))
        for cv in product(*(ctx_opts[d] for d in dims)):
            ctx = dict(zip(dims, cv))
            total += 1
            bench = scope_compatible(scope, ctx)
            prod = _scope_ok(to_product_scope(scope),
                             to_product_context(ctx))
            if bench == prod:
                continue
            divergent += 1
            # legal divergence 1: lang overload (product's single lang field)
            s_code, s_nat = scope["code_lang"] != ANY, scope["nat_lang"] != ANY
            c_code, c_nat = ctx["code_lang"] is not None, \
                ctx["nat_lang"] is not None
            crossed = (s_code and not c_code and c_nat) \
                or (not s_code and s_nat and c_code) \
                or (s_code and s_nat) or (c_code and c_nat)
            # legal divergence 2: bench task genre no longer projects into
            # product soft-scope (it lives in kinds instead)
            task_genre = (
                scope["task"] != ANY and ctx.get("task") is not None
                and scope["task"] != ctx["task"]
                and bench is False and prod is True)
            assert crossed or task_genre, (
                f"unexplained divergence: scope={scope} ctx={ctx} "
                f"bench={bench} product={prod}")
    # the distortion exists (the overload is real) and is bounded
    assert divergent > 0
    assert divergent / total < 0.25, f"{divergent}/{total} diverge"


# ---------------------------------------------------------------------------
# fold semantics
# ---------------------------------------------------------------------------

def test_fold_prefix_and_reasons():
    effects = [
        Effect(seq=1, kind="assert", cid="c1"),
        Effect(seq=3, kind="assert", cid="c2"),
        Effect(seq=5, kind="contradict", cid="c3", target="c1"),
        Effect(seq=7, kind="retire", target="c2"),
        Effect(seq=8, kind="assert", cid="c4"),
        Effect(seq=8, kind="assert", cid="c5"),
        Effect(seq=9, kind="merge", cid="c6", targets=("c4", "c5")),
    ]
    assert valid_at(effects, 4) == {"c1", "c2"}
    assert valid_at(effects, 6) == {"c2", "c3"}
    st = fold(effects)
    assert st["c1"].status == "superseded" and st["c1"].superseded_by == "c3"
    assert st["c2"].status == "withdrawn"
    assert st["c4"].status == "merged" and st["c4"].superseded_by == "c6"
    assert valid_at(effects, 99) == {"c3", "c6"}


def test_fold_auto_retire_via_bumps():
    effects = [Effect(seq=1, kind="assert", cid="c1"),
               Effect(seq=2, kind="bump", target="c1", delta=-1),
               Effect(seq=3, kind="bump", target="c1", delta=-2)]
    assert fold(effects)["c1"].status == "auto_retired"


# ---------------------------------------------------------------------------
# eight planted defects, each caught by its lint
# ---------------------------------------------------------------------------

def _episode_base():
    a = _c("a", "代码折到 96 列")
    b = _c("b", "代码折到 80 列",
           value=Value(type="numeric", num=80, unit="col", cmp="max"))
    effects = [Effect(seq=1, kind="assert", cid="a"),
               Effect(seq=4, kind="contradict", cid="b", target="a")]
    return [a, b], effects


def test_defect_1_contradicts_both_active():
    cs, _ = _episode_base()
    effects = [Effect(seq=1, kind="assert", cid="a"),
               Effect(seq=2, kind="assert", cid="b")]   # no supersede!
    assert any("I1" in e for e in check_i1(cs, effects, checkpoints=[3]))


def test_defect_2_partial_conflict_rejected():
    a = _c("a", "python 折 96", scope=_scope(code_lang="python"))
    b = _c("b", "editor 折 80", scope=_scope(app="editor"),
           value=Value(type="numeric", num=80, unit="col", cmp="max"))
    assert any("I3" in e for e in check_i3([a, b]))


def test_defect_3_revival_flagged():
    effects = [Effect(seq=1, kind="assert", cid="a"),
               Effect(seq=2, kind="retire", target="a"),
               Effect(seq=3, kind="assert", cid="a")]   # zombie revival
    assert any("I5" in e for e in check_i5(effects)) \
        or any("I8" in e for e in check_i8([], effects))


def test_defect_4_unknown_target():
    cs, effects = _episode_base()
    effects.append(Effect(seq=5, kind="retire", target="ghost"))
    assert any("I8" in e and "ghost" in e for e in check_i8(cs, effects))


def test_defect_5_target_introduced_later():
    cs, _ = _episode_base()
    effects = [Effect(seq=1, kind="retire", target="a"),
               Effect(seq=2, kind="assert", cid="a"),
               Effect(seq=3, kind="assert", cid="b")]
    assert any("I8" in e for e in check_i8(cs, effects))


def test_defect_6_catalogue_orphan():
    cs, effects = _episode_base()
    cs.append(_c("orphan", "从未被引入的规则", key="email.length"))
    assert any("orphan" in e for e in check_i8(cs, effects))


def test_defect_7_key_split_near_duplicate():
    a = _c("a", "所有邮件不超过 120 词")
    # same rule, key split to a different registry entry → edge deleted
    b = _c("b", "所有邮件不超过 120 词", key="email.length")
    object.__setattr__(a.coords, "key", "length.max")
    assert any("I10" in e for e in check_i10([a, b]))


def test_defect_8_unreachable_trap():
    cs, effects = _episode_base()
    # trap scoped to java, probe context python → no arm would inject it
    trap = _c("trap", "java 注释写中文", key="code.comment_language",
              scope=_scope(code_lang="java"),
              value=Value(type="lang", tag="zh"))
    cs.append(trap)
    effects.append(Effect(seq=2, kind="assert", cid="trap"))
    probes = [{"seq": 6, "query": "写个 python 脚本",
               "context": {"code_lang": "python"},
               "must_not_fire": ["trap"]}]
    assert any("I11" in e and "trap" in e for e in check_i11(cs, effects,
                                                             probes))


def test_authored_roles_rejected():
    assert any("I9" in e for e in check_i9([], {"roles": {"a": "chain"}}))


def test_clean_episode_lints_green():
    cs, effects = _episode_base()
    probes = [{"seq": 6, "query": "把这段代码折一下行",
               "context": {}, "must_not_fire": ["a"]}]
    errs = lint_episode(cs, effects, probes, checkpoints=[2, 6])
    assert errs == [], errs
