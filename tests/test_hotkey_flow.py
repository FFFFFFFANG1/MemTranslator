import importlib.util

import pytest

if importlib.util.find_spec("Quartz") is None:
    pytest.skip("pyobjc not installed (hotkey group)", allow_module_level=True)

from memtranslator.hotkey.__main__ import polish_flow


def test_applied_writes_back():
    wrote = {}
    out = polish_flow(
        read=lambda: "raw",
        write=lambda t: wrote.setdefault("t", t) or True,
        post=lambda t: {"decision": "apply", "polished": "POLISHED"})
    assert out == "applied" and wrote["t"] == "POLISHED"


def test_noop_leaves_field_alone():
    out = polish_flow(read=lambda: "raw", write=lambda t: (_ for _ in ()).throw(
        AssertionError("must not write")), post=lambda t: {"decision": "noop"})
    assert out == "noop"


def test_empty_and_daemon_down():
    assert polish_flow(read=lambda: "  ", write=None, post=None) == "empty"

    def boom(t):
        raise OSError("down")

    assert polish_flow(read=lambda: "raw", write=None, post=boom) == "daemon_down"
