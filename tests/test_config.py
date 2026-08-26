import os

from memtranslator.config import _load_project_env


def test_project_env_loads_values_without_overriding_shell(tmp_path,
                                                           monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "MT_TEST_NEW=from-file\n"
        "export MT_TEST_QUOTED='quoted value'\n"
        "MT_TEST_EXISTING=from-file\n"
        "not a key=ignored\n")
    monkeypatch.delenv("MT_TEST_NEW", raising=False)
    monkeypatch.delenv("MT_TEST_QUOTED", raising=False)
    monkeypatch.setenv("MT_TEST_EXISTING", "from-shell")

    _load_project_env(env_file)

    assert os.environ["MT_TEST_NEW"] == "from-file"
    assert os.environ["MT_TEST_QUOTED"] == "quoted value"
    assert os.environ["MT_TEST_EXISTING"] == "from-shell"
