from pilot.analyze import bootstrap_ci, paired_delta_ci


def test_bootstrap_degenerate():
    mean, lo, hi = bootstrap_ci([1, 1, 1, 1])
    assert mean == lo == hi == 1.0


def test_bootstrap_range():
    mean, lo, hi = bootstrap_ci([0, 1] * 50)
    assert 0.35 < lo <= mean <= hi < 0.65


def test_paired_delta_sign():
    a = [1] * 80 + [0] * 20   # 80%
    b = [1] * 60 + [0] * 40   # 60%
    delta, lo, hi = paired_delta_ci(a, b)
    assert 0.15 < delta < 0.25 and lo > 0
