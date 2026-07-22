# MemTranslator

An open-source translator between the user and their agents: it learns how the user wants tasks done (delivery requirements) and compiles them into the request itself, so downstream agents never read memory. All direction lives in `position_anchor.md`.

- `position_anchor.md` — 项目定位锚点（唯一方向依据）
- `docs/archive.md` — record of the 2026-07 first build (record only; every approach in it deviates from the anchor)
- `proto/` — working prototype (memory store, write/read paths, typeless-style demo UI, tests)

Rebuilding from zero per anchor §7.
