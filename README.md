# MemTranslator

Memory-grounded user translator for personal agents: compile user memory into the request (a translation layer between user and agent) instead of injecting it into the agent's context.

- `docs/idea.md` — position draft
- `docs/diagnosis.md` — novelty / benchmark diagnosis (verdict: two-week pilot decides)
- `docs/2026-07-21-pilot-plan.md` — pilot implementation plan (4 arms x 2 downstream tiers on a PrefEval subset; pre-registered go/no-go criteria in §0)
- `docs/memory-design.md` — memory-layer design: schema + ≤2-call write path (v0 proposal)
- `docs/hms-mandol-notes.md` — code-level notes on HMS and Mandol with adoption decisions
- `proto/` — working prototype (memory store, write/read paths, typeless-style demo UI, tests)
