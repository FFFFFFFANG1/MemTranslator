# Closed-Loop Plan：daemon 化 + Claude Code hook + 热键 spike

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 (raw, polished, final) 三元组的最小闭环：v0 server 演化为本地 daemon（接收 hook 的 submit 事件并与 translate 事件 join）、Claude Code 单家 `UserPromptSubmit` hook、macOS 菜单栏热键 app 的 pyobjc spike（AX 读写焦点输入框）。

**Architecture:** 两条通道汇成一个 join（2026-07-23 对话确认的技术线）：通道 1 = 热键改写（Typeless 路线，AX 写回，人在环编辑）产生 translate 事件；通道 2 = agent hook 静默采集最终提交文本，产生 submit 事件；daemon 内按时间窗 + 相似度 join 并分类（accepted_verbatim / edited_after_polish / reverted / natural）。一份数据喂两个消费方：改写机制的接受率信号 + v1 extraction 语料。**红线**：全本地（不出机器）；hook fail-open（daemon 不在也绝不拖慢 agent）；join 不埋文本标记；memory 不进下游上下文（anchor §2.2）。

**Tech Stack:** 现有 uv 项目扩展。热键 spike 用 pyobjc（同仓库同语言，免 Xcode；spike 验证形态成立后，产品化壳再决定是否 Swift 重写）。hook 用 shell + curl（零启动成本）。

**选型说明（非拍板点，spike 后可推翻）:** 热键默认 ⌥⌘E（避开常见冲突，配置在 config.py）；AX 写回失败时降级为剪贴板 + 模拟 ⌘V（Typeless 同款兜底，见 research 分支 typeless-analysis §4.1）。

**执行边界:** Cursor / Codex 的 hook、管理页大改、extraction 算法（v1 主线）均不在本 plan——只做到语料落盘。

---

## Task 0: join 逻辑（signals.py）

**Files:**
- Create: `src/memtranslator/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_signals.py
from memtranslator.signals import classify_submit


def _tr(tid, original, polished, at):
    return {"kind": "translate", "translate_id": tid, "at": at,
            "original": original, "polished": polished, "decision": "apply"}


def test_exact_match_is_accepted_verbatim():
    trs = [_tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("给房东写封不超过120词的邮件", 1100.0, trs)
    assert out["classification"] == "accepted_verbatim"
    assert out["matched_translate_id"] == "tr-1"


def test_edited_after_polish():
    trs = [_tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("给房东写封不超过120词的英文邮件，语气强硬点", 1100.0, trs)
    assert out["classification"] == "edited_after_polish"
    assert out["matched_translate_id"] == "tr-1"
    assert 0 < out["similarity"] < 1


def test_reverted_to_original():
    trs = [_tr("tr-1", "给房东写邮件催修暖气", "给房东写封不超过120词的邮件催修暖气", 1000.0)]
    out = classify_submit("给房东写邮件催修暖气", 1100.0, trs)
    assert out["classification"] == "reverted"
    assert out["matched_translate_id"] == "tr-1"


def test_unrelated_text_is_natural():
    trs = [_tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("看一下这个函数为什么panic", 1100.0, trs)
    assert out["classification"] == "natural"
    assert out["matched_translate_id"] is None


def test_out_of_window_is_natural():
    trs = [_tr("tr-1", "a", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("给房东写封不超过120词的邮件", 1000.0 + 3600, trs)
    assert out["classification"] == "natural"


def test_latest_matching_translate_wins():
    trs = [_tr("tr-1", "x", "版本一的润色结果", 1000.0),
           _tr("tr-2", "x", "版本二的润色结果", 1200.0)]
    out = classify_submit("版本二的润色结果", 1300.0, trs)
    assert out["matched_translate_id"] == "tr-2"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "/Users/siriux/Library/Mobile Documents/com~apple~CloudDocs/Documents/Codes/Projects/MemTranslator"
/opt/homebrew/bin/uv run pytest tests/test_signals.py -q
```
Expected: FAIL（ImportError: signals 不存在）。

- [ ] **Step 3: 写 `src/memtranslator/signals.py`**

```python
"""Join submit events (from agent hooks) with translate events.

No markers are ever embedded in text — the daemon holds both sides of the
join, so a time window plus text similarity is enough. Classification feeds
two consumers: acceptance metrics for the rewrite loop, and the v1
extraction corpus.
"""
from difflib import SequenceMatcher

JOIN_WINDOW_S = 15 * 60
EDIT_SIM_THRESHOLD = 0.55
REVERT_SIM_THRESHOLD = 0.85


def _norm(s: str) -> str:
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def classify_submit(text: str, at: float, translate_events: list[dict]) -> dict:
    """Returns {classification, matched_translate_id, similarity}.

    classification ∈ accepted_verbatim | edited_after_polish | reverted | natural
    """
    candidates = [e for e in translate_events
                  if e.get("kind") == "translate"
                  and e.get("decision") == "apply"
                  and e.get("polished")
                  and 0 <= at - e["at"] <= JOIN_WINDOW_S]
    best = None
    for e in reversed(candidates):  # newest first
        sim_polished = _sim(text, e["polished"])
        sim_original = _sim(text, e.get("original", ""))
        score = max(sim_polished, sim_original)
        if best is None or score > best[0] + 1e-9:
            best = (score, sim_polished, sim_original, e)
    if best is None:
        return {"classification": "natural",
                "matched_translate_id": None, "similarity": None}
    score, sim_polished, sim_original, event = best
    tid = event["translate_id"]
    if _norm(text) == _norm(event["polished"]):
        return {"classification": "accepted_verbatim",
                "matched_translate_id": tid, "similarity": 1.0}
    if sim_original >= REVERT_SIM_THRESHOLD and sim_original >= sim_polished:
        return {"classification": "reverted",
                "matched_translate_id": tid, "similarity": sim_original}
    if sim_polished >= EDIT_SIM_THRESHOLD:
        return {"classification": "edited_after_polish",
                "matched_translate_id": tid, "similarity": sim_polished}
    return {"classification": "natural",
            "matched_translate_id": None, "similarity": None}
```

- [ ] **Step 4: 测试通过**

```bash
/opt/homebrew/bin/uv run pytest tests/test_signals.py -q
```
Expected: 6 passed。

- [ ] **Step 5: Commit**

```bash
git add src/memtranslator/signals.py tests/test_signals.py
git commit -m "[daemon] Add submit-translate join with acceptance classification"
```

---

## Task 1: daemon 化——submit 事件端点

**Files:**
- Modify: `src/memtranslator/server.py`
- Test: `tests/test_server.py`（追加）

- [ ] **Step 1: 追加失败测试（tests/test_server.py 末尾）**

```python
def test_submit_event_joins_with_translate(tmp_path, monkeypatch):
    client, app = make_client(tmp_path)
    rid = client.post("/api/requirements", json={"text": "Short."}).json()["id"]
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (
        f'{{"decision": "apply", "applied_ids": ["{rid}"], '
        f'"polished": "polished text"}}'))
    tr = client.post("/api/translate", json={"text": "raw text"}).json()

    r = client.post("/api/events/submit", json={
        "text": "polished text", "source": "claude-code",
        "session_id": "s-1", "cwd": "/tmp/x"})
    body = r.json()
    assert body["classification"] == "accepted_verbatim"
    assert body["matched_translate_id"] == tr["translate_id"]

    sub = [e for e in app.state.events.read_all() if e["kind"] == "submit"][-1]
    assert sub["source"] == "claude-code"
    assert sub["classification"] == "accepted_verbatim"


def test_submit_event_natural_without_translate(tmp_path):
    client, app = make_client(tmp_path)
    r = client.post("/api/events/submit", json={
        "text": "不是让你总结，是要批判分析", "source": "claude-code"})
    assert r.json()["classification"] == "natural"


def test_events_endpoint_lists_newest_first(tmp_path):
    client, app = make_client(tmp_path)
    client.post("/api/events/submit", json={"text": "a", "source": "x"})
    client.post("/api/events/submit", json={"text": "b", "source": "x"})
    events = client.get("/api/events?limit=1").json()["events"]
    assert len(events) == 1 and events[0]["text"] == "b"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/opt/homebrew/bin/uv run pytest tests/test_server.py -q
```
Expected: 新增 3 个 FAIL（404），原有 4 个仍 pass。

- [ ] **Step 3: 改 `server.py`**

imports 处加：

```python
from memtranslator.signals import classify_submit
```

Pydantic models 处加：

```python
class SubmitIn(BaseModel):
    text: str
    source: str
    session_id: str | None = None
    cwd: str | None = None
```

`create_app` 内（translate 端点之后）加两个端点：

```python
    @app.post("/api/events/submit")
    def submit_event(body: SubmitIn):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "empty text")
        translates = [e for e in events.read_all() if e["kind"] == "translate"]
        import time as _time
        verdict = classify_submit(text, _time.time(), translates)
        events.append("submit", {
            "text": text, "source": body.source,
            "session_id": body.session_id, "cwd": body.cwd,
            "classification": verdict["classification"],
            "matched_translate_id": verdict["matched_translate_id"],
            "similarity": verdict["similarity"],
        })
        return verdict

    @app.get("/api/events")
    def list_events(limit: int = 50):
        all_events = events.read_all()
        return {"events": list(reversed(all_events))[:limit]}
```

（`import time as _time` 放文件顶部 `import json` 旁，写成 `import time`，端点内用 `time.time()`——上面内联写法只为标明位置。）

- [ ] **Step 4: 全量测试通过**

```bash
/opt/homebrew/bin/uv run pytest -q
```
Expected: 29 passed（20 旧 + 6 signals + 3 新）。

- [ ] **Step 5: Commit**

```bash
git add src/memtranslator/server.py tests/test_server.py
git commit -m "[daemon] Accept hook submit events and expose the event feed"
```

---

## Task 2: Claude Code hook（shell + curl，fail-open）

**Files:**
- Create: `hooks/claude-code/user-prompt-submit.sh`
- Create: `hooks/claude-code/settings-fragment.json`

- [ ] **Step 1: 写 `hooks/claude-code/user-prompt-submit.sh`**

```bash
#!/bin/sh
# MemTranslator capture hook for Claude Code (UserPromptSubmit).
# Fail-open by design: if the daemon is down, exit 0 fast and let the
# prompt through untouched. Never blocks, never modifies, never prints.
INPUT=$(cat)
printf '%s' "$INPUT" | /usr/bin/python3 -c '
import json, sys, urllib.request
try:
    d = json.load(sys.stdin)
    payload = json.dumps({
        "text": d.get("prompt", ""),
        "source": "claude-code",
        "session_id": d.get("session_id"),
        "cwd": d.get("cwd"),
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8123/api/events/submit",
        data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=1)
except Exception:
    pass
' 2>/dev/null
exit 0
```

- [ ] **Step 2: 写 `hooks/claude-code/settings-fragment.json`（用户合并进 `~/.claude/settings.json` 的片段）**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/Codes/Projects/MemTranslator/hooks/claude-code/user-prompt-submit.sh\"",
            "timeout": 3
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: 本地验证（daemon 开着时事件落盘、关着时快速静默通过）**

```bash
chmod +x hooks/claude-code/user-prompt-submit.sh
# daemon 在跑（preview / uvicorn 8123）时：
echo '{"prompt":"测试捕获","session_id":"s-test","cwd":"/tmp"}' | hooks/claude-code/user-prompt-submit.sh; echo "exit=$?"
curl -s "http://127.0.0.1:8123/api/events?limit=1" | /usr/bin/python3 -m json.tool
# 停掉 daemon 再跑一次，验证 <1.5s 返回且 exit=0：
time (echo '{"prompt":"x"}' | hooks/claude-code/user-prompt-submit.sh)
```
Expected: 第一次 events 里出现 `kind=submit, source=claude-code, classification=natural`；第二次 exit=0 且耗时 ~1s 内。

- [ ] **Step 4: Commit**

```bash
git add hooks/
git commit -m "[hooks] Add fail-open Claude Code UserPromptSubmit capture hook"
```

---

## Task 3: 热键菜单栏 app spike（pyobjc）

**Files:**
- Create: `src/memtranslator/hotkey/__init__.py`（空）
- Create: `src/memtranslator/hotkey/__main__.py`
- Create: `src/memtranslator/hotkey/axtext.py`
- Modify: `pyproject.toml`（hotkey 依赖组）
- Test: `tests/test_hotkey_flow.py`（AX mock 掉，只测 polish 流程函数）

- [ ] **Step 1: pyproject.toml 加依赖组**

`[dependency-groups]` 段改为：

```toml
[dependency-groups]
dev = ["pytest>=8", "httpx>=0.27"]
hotkey = [
    "pyobjc-framework-Cocoa>=10",
    "pyobjc-framework-Quartz>=10",
    "pyobjc-framework-ApplicationServices>=10",
]
```

- [ ] **Step 2: 写 `src/memtranslator/hotkey/axtext.py`（AX 读写 + 剪贴板兜底）**

```python
"""Read and write the focused text field via the Accessibility API.

Primary path: AXValue get/set on the system-wide focused element.
Fallback (Chromium/Electron fields that reject AXValue set): put the text
on the pasteboard, select-all, and synthesize Cmd+V — the Typeless-style
bottom line. Requires the Accessibility permission (System Settings →
Privacy & Security → Accessibility)."""
import time

from ApplicationServices import (
    AXIsProcessTrustedWithOptions,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateSystemWide,
    AXUIElementSetAttributeValue,
    kAXFocusedUIElementAttribute,
    kAXTrustedCheckOptionPrompt,
    kAXValueAttribute,
)
from AppKit import NSPasteboard, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

KEY_A, KEY_V = 0, 9


def ensure_trusted() -> bool:
    return AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})


def _focused_element():
    err, el = AXUIElementCopyAttributeValue(
        AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute, None)
    return el if err == 0 else None


def read_focused_text() -> str | None:
    el = _focused_element()
    if el is None:
        return None
    err, value = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
    if err != 0 or not isinstance(value, str):
        return None
    return value


def _tap_key(keycode: int, cmd: bool = False) -> None:
    for down in (True, False):
        ev = CGEventCreateKeyboardEvent(None, keycode, down)
        if cmd:
            CGEventSetFlags(ev, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, ev)


def write_focused_text(text: str) -> bool:
    el = _focused_element()
    if el is not None:
        err = AXUIElementSetAttributeValue(el, kAXValueAttribute, text)
        if err == 0 and read_focused_text() == text:
            return True
    # fallback: pasteboard + select-all + paste
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    _tap_key(KEY_A, cmd=True)
    time.sleep(0.05)
    _tap_key(KEY_V, cmd=True)
    return True
```

- [ ] **Step 3: 写 `src/memtranslator/hotkey/__main__.py`（菜单栏 + 全局热键 + polish 流程）**

```python
"""MemTranslator hotkey shell (spike): menu bar item + global ⌥⌘E.

On hotkey: read the focused text field, ask the daemon to polish, write the
result back — editable in place, human in the loop (anchor §2.2). The
daemon records the translate event; the agent-side hook records the final
submit; the join happens server-side."""
import json
import threading
import urllib.request

from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSMenu,
    NSMenuItem, NSStatusBar, NSVariableStatusItemLength,
)
from PyObjCTools import AppHelper
from Quartz import (
    CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopGetCurrent,
    CGEventGetFlags, CGEventGetIntegerValueField, CGEventMaskBit,
    CGEventTapCreate, CGEventTapEnable, kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate, kCGEventFlagMaskCommand, kCGEventKeyDown,
    kCGHeadInsertEventTap, kCGKeyboardEventKeycode, kCGSessionEventTap,
    kCGEventTapOptionDefault,
)

from memtranslator.hotkey import axtext

DAEMON = "http://127.0.0.1:8123"
KEY_E = 14  # ANSI 'e'


def polish_flow(read=axtext.read_focused_text,
                write=axtext.write_focused_text,
                post=None) -> str:
    """Returns a status string; separated from AX for testability."""
    if post is None:
        def post(text):
            req = urllib.request.Request(
                f"{DAEMON}/api/translate",
                data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
    raw = read()
    if not raw or not raw.strip():
        return "empty"
    try:
        out = post(raw)
    except Exception:
        return "daemon_down"
    if out.get("decision") != "apply":
        return "noop"
    return "applied" if write(out["polished"]) else "write_failed"


class App:
    def __init__(self):
        self.status_item = NSStatusBar.systemStatusBar() \
            .statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("⇄")
        menu = NSMenu.alloc().init()
        menu.addItemWithTitle_action_keyEquivalent_(
            "MemTranslator · ⌥⌘E 润色", None, "")
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItemWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        self.status_item.setMenu_(menu)

    def flash(self, text):
        def set_title(t):
            self.status_item.button().setTitle_(t)
        AppHelper.callAfter(set_title, text)
        threading.Timer(1.6, lambda: AppHelper.callAfter(set_title, "⇄")).start()

    def on_hotkey(self):
        def run():
            status = polish_flow()
            self.flash({"applied": "✓", "noop": "·", "empty": "·",
                        "daemon_down": "!", "write_failed": "!"}[status])
        threading.Thread(target=run, daemon=True).start()


def main():
    if not axtext.ensure_trusted():
        print("Grant Accessibility permission, then relaunch.")
    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app = App()

    def tap_callback(proxy, etype, event, refcon):
        if etype == kCGEventKeyDown:
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            flags = CGEventGetFlags(event)
            if (keycode == KEY_E
                    and flags & kCGEventFlagMaskCommand
                    and flags & kCGEventFlagMaskAlternate):
                app.on_hotkey()
                return None  # swallow the keystroke
        return event

    tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                           kCGEventTapOptionDefault,
                           CGEventMaskBit(kCGEventKeyDown), tap_callback, None)
    if tap is None:
        raise SystemExit("Event tap failed — check Accessibility permission.")
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 写 `tests/test_hotkey_flow.py`（不 import AX——注入 fake，测流程分支）**

```python
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
    def boom(t): raise OSError("down")
    assert polish_flow(read=lambda: "raw", write=None, post=boom) == "daemon_down"
```

- [ ] **Step 5: 安装依赖 + 全量测试**

```bash
/opt/homebrew/bin/uv sync --group hotkey
/opt/homebrew/bin/uv run pytest -q
```
Expected: 32 passed（pyobjc 未装的环境里 hotkey 测试 skip）。

- [ ] **Step 6:（人工闸门，siriux ~2 分钟）真机 spike 验证**

```bash
/opt/homebrew/bin/uv run --group hotkey python -m memtranslator.hotkey
```
首次运行按提示授予 Accessibility 权限后重启 app。验收清单：
1. 菜单栏出现 ⇄；
2. 在任意 app（先试备忘录，再试 Claude Code 输入框）输入一句该触发 requirement 的话；
3. ⌥⌘E → 文本被替换为 polished 版（图标闪 ✓）；Chromium 系输入框若走了剪贴板兜底，光标/选区行为如有异常记下来；
4. 手动改两个词后回车发送（Claude Code 里）→ `curl -s "http://127.0.0.1:8123/api/events?limit=3"` 应看到 submit 事件 `classification=edited_after_polish` 且 `matched_translate_id` 非空——**这一条通过即三元组闭环成立**。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/memtranslator/hotkey tests/test_hotkey_flow.py
git commit -m "[hotkey] Add menu bar spike: global hotkey, AX read/write, daemon polish flow"
```

---

## Task 4: 管理页小补——requirement 双击改文本

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: `.req .text` 双击进入编辑**

`renderRequirements` 里 active 条目的绑定处（`querySelectorAll(".retire")` 之前）加：

```javascript
  reqListEl.querySelectorAll(".req:not(.retired) .text").forEach(el => {
    el.ondblclick = () => {
      const box = el.closest(".req");
      const id = box.dataset.id;
      const old = el.textContent;
      el.contentEditable = "true";
      el.focus();
      document.getSelection().selectAllChildren(el);
      const finish = async (save) => {
        el.contentEditable = "false";
        const text = el.textContent.trim();
        if (!save || !text || text === old) { el.textContent = old; return; }
        await fetch(`/api/requirements/${id}`, {
          method: "PATCH",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({text}),
        });
        await loadRequirements();
      };
      el.onblur = () => finish(true);
      el.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); el.blur(); }
        if (e.key === "Escape") { el.onblur = null; finish(false); }
      };
    };
  });
```

并在 CSS `.req .text` 规则后加一行提示样式：

```css
.req .text[contenteditable="true"]{outline:1px solid var(--gold);outline-offset:3px;border-radius:3px}
```

- [ ] **Step 2: 浏览器验证**

daemon 起着，双击一条 requirement → 改文字 → Enter 保存（面板刷新为新文本）、Esc 放弃。PATCH 请求 200。

- [ ] **Step 3: Commit**

```bash
git add web/index.html
git commit -m "[web] Edit requirement text in place with double-click"
```

---

## Task 5: 文档 + 收尾

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README 的 Run 段后追加**

```markdown
## The closed loop (v0.5)

Two channels join inside the daemon — no markers ever embedded in text:

    hotkey app ──(raw, polished)──▶ daemon ◀──(final text)── agent hook
                            join → accepted / edited / reverted / natural

- **Hotkey shell** (`uv run --group hotkey python -m memtranslator.hotkey`):
  menu bar ⇄, global ⌥⌘E polishes the focused text field via Accessibility
  (grant permission on first run). AX write-back with a clipboard fallback.
- **Claude Code hook**: merge `hooks/claude-code/settings-fragment.json`
  into `~/.claude/settings.json`. Fail-open: if the daemon is down the
  prompt passes through untouched. Cursor / Codex hooks: not yet.
- Everything stays on your machine: capture, storage (`data/`), and the
  flash extraction planned for v1.
```

- [ ] **Step 2: 全量测试 + push（dev → main 同步）**

```bash
/opt/homebrew/bin/uv run pytest -q
git add README.md && git commit -m "[docs] Document the closed loop and hook install"
git push origin dev && git checkout main && git merge dev && git push origin main && git checkout dev
```

---

## 后续（不在本 plan）

1. Cursor（`beforeSubmitPrompt` + `afterAgentResponse`，后者带 agent 回复，纠正类语料的上下文）与 Codex（`UserPromptSubmit`）hook——照 Task 2 模板各一个脚本。
2. 管理前端大改：events 时间线视图（三元组浏览）、接受率仪表。
3. v1 extraction：从 edited diff + natural 纠正消息提取 requirement（anchor §4 主线，≤2 flash call），spike 数据攒够后立项。
4. 壳产品化拍板：pyobjc spike 若成立但体感/分发不够，再评估 Swift 菜单栏 app 重写。

## Self-review 记录

- 技术线覆盖：通道 1（Task 3）、通道 2（Task 2）、join（Task 0/1）、"自由控制 memory"（Task 4 + 既有 CRUD）——对话确认的四件事齐。
- 红线落实：hook fail-open（exit 0 + timeout 1s + 2>/dev/null）；join 无文本标记（signals.py 纯相似度）；全本地（无外部上报）；memory 不进下游（未动 chat 端点）。
- pyobjc API 名称按 ApplicationServices/Quartz 常用绑定书写；spike 性质，Step 6 真机验证时如遇绑定差异（如 `kAXTrustedCheckOptionPrompt` 的字典 key 形态）允许现场修，属预期内迭代。
- 测试计数：20（现有）+6+3+3 = 32；pyobjc 缺席环境 skip 3。
- 无占位符；Task 1 Step 3 中对 `import time` 的位置说明已明示。
