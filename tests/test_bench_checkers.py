from bench_archive.runner.checkers import run_check


def test_contains_all():
    ok, why = run_check("contains_all", {"keywords": ["房东", "暖气"]},
                        polished="给房东写封邮件催修暖气", case_input="x")
    assert ok
    bad, why = run_check("contains_all", {"keywords": ["水管"]},
                         polished="给房东写封邮件催修暖气", case_input="x")
    assert not bad and "水管" in why


def test_not_contains():
    ok, _ = run_check("not_contains", {"banned": ["120"]},
                      polished="写封求职信", case_input="x")
    assert ok
    bad, _ = run_check("not_contains", {"banned": ["120"]},
                       polished="写封不超过120词的求职信", case_input="x")
    assert not bad


def test_same_language_zh_en():
    ok, _ = run_check("same_language", {}, polished="给房东写封不超过120词的邮件",
                      case_input="帮我给房东写封邮件")
    assert ok
    bad, _ = run_check("same_language", {},
                       polished="Draft an email to my landlord",
                       case_input="帮我给房东写封邮件")
    assert not bad


def test_unknown_checker_raises():
    try:
        run_check("nope", {}, polished="x", case_input="y")
        raise AssertionError("should raise")
    except KeyError:
        pass
