from memtranslator.source_policy import (DEFAULT_SOURCE_ENTRIES,
                                         SourceAllowlist,
                                         route_a_source_allowed)


def test_known_ai_clients_are_allowed():
    assert route_a_source_allowed({"app_bundle_id": "com.openai.codex"})
    assert route_a_source_allowed({
        "app_bundle_id": "com.todesktop.230313mzl4w4u92"})
    assert route_a_source_allowed({"app_name": "Claude Code"})


def test_unlisted_native_apps_fail_closed():
    assert not route_a_source_allowed({
        "app_bundle_id": "com.apple.TextEdit", "app_name": "TextEdit"})
    assert not route_a_source_allowed({})
    assert not route_a_source_allowed(None)


def test_browser_requires_an_allowed_page_domain():
    chrome = "com.google.Chrome"
    assert route_a_source_allowed({
        "app_bundle_id": chrome, "web_domain": "gemini.google.com"})
    assert route_a_source_allowed({
        "app_bundle_id": chrome, "web_domain": "www.doubao.com"})
    assert not route_a_source_allowed({"app_bundle_id": chrome})
    assert not route_a_source_allowed({
        "app_bundle_id": chrome, "web_domain": "mail.google.com"})


def test_source_allowlist_can_be_extended_with_environment(monkeypatch):
    monkeypatch.setenv("MT_CAPTURE_APP_BUNDLES", "com.example.agent")
    monkeypatch.setenv("MT_CAPTURE_WEB_DOMAINS", "assistant.example")
    assert route_a_source_allowed({"app_bundle_id": "com.example.agent"})
    assert route_a_source_allowed({
        "app_bundle_id": "com.apple.Safari",
        "web_domain": "chat.assistant.example",
    })


def test_persistent_allowlist_seeds_once_and_preserves_deletion(tmp_path):
    path = tmp_path / "source_allowlist.json"
    allowlist = SourceAllowlist(path)
    assert len(allowlist.list()) == len(DEFAULT_SOURCE_ENTRIES)

    allowlist.delete("source-app-codex")
    reloaded = SourceAllowlist(path)

    assert len(reloaded.list()) == len(DEFAULT_SOURCE_ENTRIES) - 1
    assert not route_a_source_allowed(
        {"app_bundle_id": "com.openai.codex"}, reloaded.list())


def test_user_managed_entries_drive_app_and_web_matching(tmp_path):
    allowlist = SourceAllowlist(tmp_path / "source_allowlist.json")
    app = allowlist.add(
        label="My Agent", kind="app",
        patterns=["com.example.agent", "My Agent"])
    web = allowlist.add(
        label="My Assistant", kind="web",
        patterns=["https://www.assistant.example/chat"])

    assert route_a_source_allowed(
        {"app_bundle_id": "com.example.agent"}, allowlist.list())
    assert route_a_source_allowed({
        "app_bundle_id": "com.google.Chrome",
        "web_domain": "chat.assistant.example",
    }, allowlist.list())

    allowlist.update(app["id"], patterns=["com.example.renamed"])
    allowlist.delete(web["id"])
    assert not route_a_source_allowed(
        {"app_bundle_id": "com.example.agent"}, allowlist.list())
    assert not route_a_source_allowed({
        "app_bundle_id": "com.google.Chrome",
        "web_domain": "chat.assistant.example",
    }, allowlist.list())
