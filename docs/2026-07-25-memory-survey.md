# Memory 系统调研:值得借鉴的思路（v1 攻坚用）

> 2026-07-25。多智能体工作流产出（7 发现桶 → 逐候选 fail-closed 准入审计 → 分线综述），65 agent / 0 error / 2.1M tokens。**准入门槛**:ICML/ICLR/NeurIPS **主会**录用 **或** GitHub **≥2000 star**;每条声明用一手来源（OpenReview/官方 proceedings/GitHub API）独立核实,查不到一手证据即 fail-closed 剔除。

> **审计结果**:36 合格 / 12 剔除（去重后）。正文英文（agent 产出,含每条出处 URL）;下方复核账本与口径更正为我署名核对。

## 我的独立复核（在 agent 审计之上二次核验）

在 agent 的逐条审计之外,我对最吃重、最易出错的近年录用做了独立二次核实:

| 工作 | agent 判定 | 我独立复核 | 结论 |
|---|---|---|---|
| A-Mem (Agentic Memory) | NeurIPS 2025 | proceedings.neurips.cc + repo「NeurIPS 2025 paper」 | ✅ 确认 |
| G-Memory | NeurIPS 2025 Spotlight | neurips.cc/virtual/2025/poster/116187 + OpenReview mmIAp3cVS0 | ✅ 确认 |
| AWM (Agent Workflow Memory) | ICML 2025 | PMLR v267:63897 | ✅ 确认 |
| LongMemEval | ICLR 2025 Poster | iclr.cc/virtual/2025/poster/28290 + OpenReview pZiyCaVuti | ✅ 确认 |
| MemoryAgentBench | ICLR 2026 | repo「ICLR 2026 Paper」(McAuley 组, UCSD) | ✅ 确认 |
| **Mem0** | 标为「academic + opensource」 | 论文实为 **ECAI 2025**(非三会),arXiv 2504.19413;靠 mem0ai/mem0 **61.6k star** 达标 | ⚠️ **更正**:纯 star 准入,非顶会论文 |

## 关键口径:哪些是「顶会论文」、哪些只是「≥2k star」

准入通过 ≠ 顶会认证。以下工作**venue 不达三会门槛,仅靠 star 达标**,引用时不可当顶会成果背书:**Mem0**(ECAI 2025 + 61.6k★)、**MemGPT/Letta**(COLM 2024 + 23.9k★)、**Voyager**(TMLR 2024 + 7.1k★)、**Generative Agents**(UIST 2023 + 参考实现 repo)、以及全部开源线(cognee/Zep-Graphiti/SuperMemory/khoj/txtai/microsoft-graphrag/MemOS/MIRIX/Memobase/Memary)。评测线的 **LoCoMo**(ACL 2024)、**MSC**(ACL 2022)属 benchmark 例外纳入,非三会。**真正三会主会**的是学术线其余条目(Reflexion/AWM/Self-Refine/HippoRAG/A-Mem/RAPTOR/ReadAgent/Larimar/MemoryLLM/EM-LLM/Titans/RMT/Memorizing Transformers/LongMem/ROME/MEMIT/MEND/G-Memory)+ 评测线 LongMemEval(ICLR'25)/MemoryAgentBench(ICLR'26)。

## 剔除清单(fail-closed,不达门槛)

| 工作 | 实际状态 | 剔除原因 |
|---|---|---|
| ExpeL | AAAI 2024 Oral (Proceedings of the AAAI Conference on AI, vol. 38 no.  | 非三会主会且 <2k star |
| Dynamic Cheatsheet | EACL 2026 main conference, long paper (ACL Anthology 2026.eacl-long.33 | 非三会主会且 <2k star |
| CLIN | Accepted at COLM 2024 (Conference on Language Modeling); arXiv 2310.10 | 非三会主会且 <2k star |
| MemWalker | arXiv preprint (arXiv:2310.05029, Oct 2023), "Walking Down the Memory  | 非三会主会且 <2k star |
| MemoryBank | Accepted at AAAI 2024 (Proceedings of the AAAI Conference on Artificia | 非三会主会且 <2k star |
| Sleep-time Compute | arXiv-only preprint (arXiv:2504.13171, Apr 2025); no ICML/ICLR/NeurIPS | 非三会主会且 <2k star |
| MemoryOS | EMNLP 2025 main conference (oral); GitHub 1519 stars (checked Jul 2026 | 非三会主会且 <2k star |
| Motorhead | GitHub 917 stars (github.com/getmetal/motorhead, via API on 2026-07-25 | 非三会主会且 <2k star |
| MemBench | ACL 2025 Findings (Findings of the ACL 2025, pp. 19336-19352); GitHub  | 非三会主会且 <2k star |
| PerLTQA | Workshop paper at SIGHAN-10 (10th SIGHAN Workshop on Chinese Language  | 非三会主会且 <2k star |
| The Coin Flip Judge? Reliability and Bias  | arXiv preprint 2606.13685, submitted 2026-04-23 (single author Abel Ya | 非三会主会且 <2k star |
| Nine Judges, Two Effective Votes | arXiv preprint (arXiv:2605.29800, posted May 2026), also on Apple Mach | 非三会主会且 <2k star |

---

# Memory Systems Survey - borrow-worthy ideas for MemTranslator v1

> Admission bar: accepted at ICML / ICLR / NeurIPS **main** conference, OR a GitHub repo with **>=2000 stars**. Every entry below was independently admission-audited (fail-closed); works whose claim could not be verified from a primary source are marked UNCERTAIN and excluded from the borrow ranking.

## 1. Cross-cutting synthesis and top-5 borrow list

### Synthesis

#### 1) Top-5 ideas most worth borrowing

**1. A single-call relation-judgement head (ADD / UPDATE / DELETE / NOOP over top-*s* neighbors).**
- *Idea:* one FLASH function-call decides, per incoming signal, whether it adds, augments, contradicts, or is redundant against a short list of retrieved candidates.
- *From:* Mem0 (academic + opensource); reinforced by HippoRAG's LLM "recognition memory" filter.
- *Pain points:* P2 (pairing) + P3 (repair).
- *Maps to us:* BM25 retrieves top-*s* existing rules for the extracted signal; one FLASH call classifies into our reinforce / contradict / merge / retire (+ noop) verbs. No training, no per-fact model, one generative call — exactly FLASH-tier. This is the closest published analogue to our relation head and should be the spine of the pipeline.

**2. Invalidate-never-delete with bi-temporal validity ("newest wins, keep history").**
- *Idea:* contradiction resolves by marking the old entry expired and writing the new one, preserving a full audit trail; time-bound rules carry an expiry.
- *From:* Zep/Graphiti (edge invalidation + validity windows), SuperMemory (newer supersedes + auto-expiry), Mem0 (logical invalidation, never hard-delete).
- *Pain points:* P3 (repair) + P4 (multi-round correctness).
- *Maps to us:* our append-only store already forbids destructive delete; add a `status ∈ {active, retired}` and `valid_from / valid_to` on each rule. Deterministic recall filters to `active`. Retire = write a tombstone edge, never remove rows. Pure KV/columnar, no dense index needed.

**3. Two-tier evidence-under-rule hierarchy (keep raw signals below the abstracted rule).**
- *Idea:* store distilled reusable rules at the top and the specific signals they were derived from at the bottom, so a rule can always be re-derived from retained evidence.
- *From:* G-Memory (insight / interaction tiers), Generative Agents (reflection tree), RAPTOR (cluster-then-summarize levels), AWM (strip instance specifics, keep the HOW).
- *Pain points:* P3 (the exact "too-narrow rule swallowing siblings via reinforce" failure) + P1 (abstraction).
- *Maps to us:* each `reinforce` appends a child evidence-note under the rule rather than mutating the rule's scope in place. A rule's wording only widens/narrows during a consolidation pass that reads its children — never as a side effect of a single reinforce. If a rule turns out over-narrow, its retained children let you split it without data loss.

**4. Write-time salience score + deterministic multi-signal recall.**
- *Idea:* the LLM assigns an importance score at write; recall ranks by a fixed weighted sum of relevance + recency + importance (+ frequency).
- *From:* Generative Agents (poignancy score; recency+importance+relevance formula), Memary (entity frequency + recency = "often + recent = important").
- *Pain points:* P1 (salience) + P4 (deterministic recall).
- *Maps to us:* FLASH emits an importance 1–10 at extraction. Recall score = `w1·BM25(query, rule) + w2·recency_decay + w3·importance + w4·hit_count`, all computable on CPU with no LLM at recall time — satisfies "deterministic recall" and stays cheap as the store grows.

**5. Candidate-generate then recognition-confirm pairing, with an explicit abstain.**
- *Idea:* use cheap lexical/graph recall to *propose* candidate entries, then an LLM confirms the right one — and is allowed to say "none matches."
- *From:* HippoRAG (seed-then-PPR + recognition filter), A-Mem (retrieve-neighbors-then-LLM-link), Graphiti / GraphRAG (entity resolution on insert), LongMemEval (abstention slice), LoCoMo (adversarial near-miss distractors).
- *Pain points:* P2 (mis-pair *and* miss-pair guard).
- *Maps to us:* BM25 top-*s* + optional KV entity/slot lookup generate candidates; the relation head must pick a candidate *or* return `NEW` when no candidate clears a confidence threshold. This is the guard against both forcing a wrong pairing and duplicating an entry that already exists. Reuse adversarial distractors and abstention questions as your pairing regression set.

#### 2) Traps / do NOT borrow

- **Dense-embedding-at-scale retrieval** — Voyager (skill-description embeddings), A-Mem/A-MEM (sentence-BERT cosine), RAPTOR (UMAP+GMM over embeddings), khoj (semantic search product), EM-LLM/LongMem/Memorizing Transformers (k-NN over dense keys). Do not copy their heavy indexing stacks wholesale. Lightweight local embeddings are allowed as one candidate-ranking signal when they run on CPU or an integrated GPU; keep BM25 + structured metadata as the other, inspectable signal.
- **Weight-editing / parametric memory** — ROME, MEMIT, MEND (closed-form or hypernetwork MLP edits), Titans (test-time gradient), Larimar/MemoryLLM/M+ (latent memory matrices/tokens), RMT (recurrent memory tokens). All require GPU training or an opaque non-auditable store; incompatible with an append-only, human-inspectable rule store and FLASH-only generation.
- **Blind statistical eviction** — MemoryLLM/M+ random-drop and Titans' decay gate. Explicitly cautioned in the corpus: random forgetting silently drops still-valid sibling evidence — the very P3 mislearning we must avoid. Always route removal through explicit relation judgement (retire), never probabilistic drop.
- **Static rebuild-to-update indexes** — RAPTOR and (largely) GraphRAG rebuild the whole index to ingest new data. Borrow their *structure* (abstraction levels / community summaries) but not the rebuild; our design is incremental append.
- **Non-deterministic self-edit as the conflict mechanism** — MemGPT/Letta let the agent ad-hoc rewrite its own core blocks. This is at odds with our deterministic-recall requirement and has "no principled new-signal-to-existing-entry matcher" (their own gap). Keep the judgement head structured, not free-form self-editing.
- **Recency-only recall / no persistence** — Reflexion (last 1–3 reflections, recency-only) and Self-Refine (no cross-task store at all). Reflexion's recency recall *is* the mis-pair risk we must beat; Self-Refine is a within-episode loop with nothing to persist. Use only as the reflect-then-distill salience template, not as a memory design.

#### 3) Concrete, buildable pipeline changes

1. **Fixed-schema single-call extractor.** [P1] [Memobase, AWM, A-Mem, SuperMemory] — One FLASH call per turn emits, against a fixed delivery-requirement schema: `{rule_text (instance-specifics stripped, HOW only), category_slot, keywords[], importance(1–10), temporary?+valid_to}`. Bounding extraction to named slots (Memobase) plus the strip-the-instance abstraction (AWM) is precisely our "delivery requirements, not content" filter; the TTL flag (SuperMemory) captures one-off constraints.

2. **BM25-candidate → FLASH relation head with forced abstain.** [P2+P3] [Mem0, HippoRAG, LongMemEval] — Retrieve top-*s* rules by BM25 (+ KV slot match), hand `signal + candidates` to one FLASH function-call returning `REINFORCE | CONTRADICT | MERGE | RETIRE | NEW | NOOP`, where `NEW` is mandatory when no candidate clears a similarity/confidence threshold. Closes both mis-pair (wrong candidate chosen) and miss-pair (duplicate created).

3. **Append-only store with status + bi-temporal validity.** [P3+P4] [Graphiti/Zep, SuperMemory, Mem0] — Add `status`, `valid_from`, `valid_to`, and a `superseded_by` pointer. `CONTRADICT`/`RETIRE` flip the old row to `retired` and write the new rule with `superseded_by`; recall filters to `active` and unexpired. Never hard-delete — preserves the audit trail and lets P3 repairs be undone.

4. **Evidence-under-rule two-tier write (anti-swallow).** [P3] [G-Memory, Generative Agents, RAPTOR] — `REINFORCE` appends a child evidence-note (raw signal + timestamp) under the rule and bumps its hit_count; it does **not** edit the rule's scope. Rule wording changes only in consolidation (below). This structurally prevents a too-narrow rule from swallowing sibling evidence, because the siblings survive as retrievable children.

5. **Threshold-triggered offline consolidation ("Auto-Dream").** [P3+P4] [MIRIX, Generative Agents, MEMIT] — When a category's accumulated importance (or child count) crosses a threshold, run one batched FLASH pass that: merges near-duplicate rules (BM25-clustered), **splits** an over-broad rule by reading its retained children, and retires rules with no active support. Batch the decisions in one constrained call (MEMIT's joint-update intuition) so edits don't drift against each other. Runs offline, off the hot recall path.

6. **Deterministic fused recall scorer.** [P4 + deterministic recall] [Generative Agents, Memary, Graphiti/txtai] — No LLM at recall: `score = w1·BM25 + w2·recency_decay + w3·importance + w4·hit_count`, over `active` rows only, hybrid BM25 + KV (FTS5-style). Reproducible, CPU-only, stable as the store grows.

*(Eval, if you want a seventh:* adopt MemoryAgentBench's incremental "learn-while-tested" protocol as the harness shape [P4], LongMemEval's knowledge-updates slice to verify contradict-supersedes-stale [P3], and LoCoMo's adversarial distractors as pairing negatives [P2].)*

## 2. Academic line

### Academic (ICML / ICLR / NeurIPS main conference)

> Scope note: several works below were admitted to this survey through the open-source bar (>=2000 GitHub stars) rather than the ICML/ICLR/NeurIPS main-conference bar; their header lines state the true status. Duplicate JSON entries for the same paper (HippoRAG, A-MEM, Larimar, EM-LLM) are consolidated into one subsection each.

#### Reflexion — NeurIPS 2023 main-conference poster; GitHub noahshinn/reflexion ~3,210 stars (Jul 2026) — https://neurips.cc/virtual/2023/poster/70114

**Mechanism.** Stores free-form natural-language self-reflections in an episodic buffer keyed to the task episode. After a trial the agent receives a feedback signal (scalar reward or a heuristic/self-evaluated success flag), reflects verbally on the failure, and appends the reflection text. No conflict resolution, merge, or dedup; memory is a sliding window (typically the last 1-3 reflections) so older ones are evicted purely by a size cap — its only forgetting mechanism. Retrieval is recency-only: the most recent reflections are prepended verbatim into the next attempt's prompt (no BM25, no embeddings). Designed for repeated attempts at the SAME task, so it never pairs a new signal against a library of prior entries.

**Numbers.** 91% pass@1 on HumanEval (vs 80% GPT-4 baseline); +22 absolute points over ReAct on ALFWorld.

**Borrow.**
- P1: the reflect-then-store loop is a concrete salience filter — distill lessons only from failed/low-reward trials.
- P4: sliding-window eviction is a minimal staleness control.
- P2/P3: none direct — no pairing, no merge/repair; recency-only recall is exactly the mis-pair risk we must beat.

#### Voyager — TMLR 2024 (admitted via open-source bar: GitHub MineDojo/Voyager 7,082 stars, Jul 2026); NOT an ICML/ICLR/NeurIPS venue — https://api.github.com/repos/MineDojo/Voyager

**Mechanism.** Stores an ever-growing skill library of executable code: each entry is a verified action program plus a natural-language description. A skill is added only after self-verification confirms it achieves its goal; the description is embedded and the code stored in a key-value dict. Append-only and never overwritten — a refined/composed skill becomes a new entry, so there is no conflict resolution, dedup, or forgetting (the library only grows). Retrieval is dense-embedding similarity over skill descriptions (NOT BM25/keyword). An automatic curriculum proposes the next task.

**Numbers.** 3.3x more unique items, 2.3x longer traversal distance, tech-tree milestones up to 15.3x faster than prior SOTA.

**Borrow.**
- P1: self-verification as the admission gate — store an artifact only once it is proven to work (analog to a validity check on a rule).
- P4: verified-only, composable skills degrade gracefully over long horizons.
- P2/P3: weak — append-only with no merge means near-duplicate siblings accumulate (our P3 problem); its dense retrieval is usable only as a lightweight candidate generator, not as our conflict mechanism.

#### Agent Workflow Memory (AWM) — ICML 2025 main-conference poster (PMLR v267, pp. 63897-63911) — https://proceedings.mlr.press/v267/wang25bx.html

**Mechanism.** Stores reusable workflows: named, generalized sub-routines abstracted from past trajectories (instance-specific context stripped), as natural-language step templates. An LLM induces workflows offline from ground-truth trajectories or online from the agent's own successes; induced workflows are appended and can themselves be built from earlier ones (hierarchical reuse). No explicit contradiction/merge operator — consolidation happens implicitly through the abstraction step that collapses similar trajectories into one canonical workflow, and the online variant biases toward frequently reused routines. Retrieval selects relevant workflows into context by prompting/similarity over the compact set, not a heavy dense index.

**Numbers.** +24.6% relative success on Mind2Web; +51.1% relative success on WebArena over baselines.

**Borrow.**
- P1: abstraction (strip instance-specifics, keep the reusable HOW) is precisely our "store delivery requirements, not content" distinction.
- P3: the induction/abstraction step folds duplicate trajectories into one workflow — a model for merging duplicate rules.
- P4: online induction shows accumulation staying useful across a task stream.
- P2: pairing is implicit (abstraction), not an explicit relation judgement.

#### Self-Refine — NeurIPS 2023 main-conference poster (NeurIPS vol. 36, pp. 46534-46594) — https://neurips.cc/virtual/2023/poster/71632

**Mechanism.** No persistent cross-task store: one LLM generates an output, produces natural-language feedback on it, then refines, looping to a stop condition. "Memory" is only the within-episode history of drafts plus feedback held in-context; nothing is written externally, no cross-task retrieval, no conflict/merge, no decay beyond the loop ending.

**Numbers.** Up to 49.2% absolute improvement over one-step generation; ~20% average gain across 7 tasks (GPT-3.5/GPT-4).

**Borrow.**
- P1 (weak): the generate-feedback-refine pattern is a template for a self-critique step when distilling a rule from a raw signal.
- P2/P3/P4: none direct — no persistent memory, pairing, or maintenance; included as the reflection-family baseline our system must surpass by actually persisting state.

#### MemGPT / Letta — COLM 2024 (does NOT meet the academic bar); admitted via open-source: GitHub letta-ai/letta 23,943 stars — https://api.github.com/repos/letta-ai/letta

**Mechanism.** OS-inspired two-tier hierarchy: a fixed-size main context (prompt window with editable core-memory blocks plus a FIFO message queue) and unbounded external context split into recall storage (full history) and archival storage (arbitrary text objects). The LLM writes/updates memory by emitting function calls (`core_memory_append/replace`, `archival_insert`); no automatic dedup or merge — consistency is whatever the model self-edits, so conflict handling is LLM-driven rewriting of core blocks, not a formal reconcile. Retrieval is by function call: `archival_search` uses embedding similarity, while recall/conversation search supports text and date filters (BM25/keyword-style). Eviction is "memory pressure": near the token limit a warning triggers a flush of older messages into recall storage — forgetting is displacement to external tiers, never hard deletion.

**Numbers.** On the Deep Memory Retrieval (DMR) conversational task and multi-session chat, substantially raises LLM-judge answer accuracy over fixed-context GPT-4 baselines; also handles document QA beyond the context window (arXiv:2310.08560).

**Borrow.**
- P3: tiered main-vs-external store with self-editing core blocks models keeping a small hot rule set while archiving the rest; "memory pressure" flush is an eviction pattern.
- P4: paging + recall/archival split is built for correctness across unbounded sessions.
- P1: weak — salience is implicit in what the LLM promotes to core memory.
- P2: none direct — no principled new-signal-to-existing-entry matcher; pairing is ad hoc LLM edits, the gap our P2 must close.

#### HippoRAG (and HippoRAG 2) — NeurIPS 2024 main-conference poster; HippoRAG 2 ("From RAG to Memory") ICML 2025 main-conference poster (PMLR v267:21497-21515) — https://neurips.cc/virtual/2024/poster/94043

**Mechanism.** Stores a schemaless open knowledge graph built offline: an LLM runs OpenIE over each passage to extract (subject, relation, object) triples; nodes are entity phrases, edges are relations, plus synonymy edges joining embedding-similar phrase nodes — the only dedup/merge mechanism (near-duplicate entities are linked, not collapsed). Indexing is purely additive: no conflict resolution, retirement, or decay. Retrieval is graph traversal, not dense-over-passages: query entities are linked to KG nodes, then Personalized PageRank runs with probability mass seeded on those nodes, and passages are ranked by accumulated PageRank mass on their entity nodes (IDF-weighted). This single-shot graph spread emulates hippocampal pattern completion across multi-hop associations that dense chunk retrieval misses.

**Numbers.** Up to ~20% improvement on multi-hop QA (MuSiQue, 2WikiMultiHopQA) over strong RAG baselines; single-step HippoRAG matches/beats iterative IRCoT while being 10-30x cheaper and 6-13x faster (arXiv:2405.14831).

**Borrow.**
- P2: dense-seed-then-PPR plus an LLM recognition-memory filter — cheap lexical/dense recall proposes candidates, an LLM judge confirms the right existing entry before writing (mis-pair guard); graph traversal + PPR run on CPU, fitting our no-vector-API constraint.
- P4: stable offline-built index gives consistent recall as it grows; framed as non-parametric continual learning.
- P3: partial — read-time triple filtering helps but there is no active merge/retire, so long-term dedup remains our problem.
- P1: OpenIE + recognition filter as a two-stage extract/salience pipeline.

#### A-MEM (Agentic Memory) — NeurIPS 2025 main-conference poster (GitHub WujiangXu/A-mem ~925 stars, below the star bar, but academic bar met) — https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html

**Mechanism.** Stores structured Zettelkasten "notes": raw content + LLM-generated contextual description, keywords, tags, timestamp, and bidirectional links, embedded with sentence-BERT. On write it embeds the new note, retrieves top-k nearest existing notes by cosine similarity, and prompts the LLM to decide meaningful bidirectional links. Its distinctive step is "memory evolution": for each linked neighbor the LLM may rewrite that neighbor's context and tags in light of the new note, so old entries are enriched by later evidence rather than frozen (its answer to duplication — evolve rather than blindly append). Retrieval is dense-embedding cosine over note descriptors, augmented by following learned links; no explicit decay, eviction, or contradiction/delete — updates are additive enrichment.

**Numbers.** LoCoMo multi-hop F1 45.85 vs MemGPT 25.52 (GPT-4o-mini); ~1,300 tokens vs ~16,900 for baselines (~13x reduction); reports gains over prior long-term-memory baselines across six foundation models (arXiv:2502.12110).

**Borrow.**
- P2: retrieve-top-k-then-LLM-judges-links is a concrete pairing recipe for attaching a new signal to the right existing entries.
- P3: "memory evolution" is the closest published analogue to our reinforce/merge repair — but its failure mode maps onto our P3 worry: additive enrichment with no retire/split can let a rewrite over-generalize an entry.
- P1: the note schema (context + keywords + tags) is a ready extraction template.
- P4: network refinement aims to stay coherent over accumulation, though unbounded growth/no forgetting is a caution.

#### RAPTOR — ICLR 2024 main-conference poster — https://iclr.cc/virtual/2024/poster/19034

**Mechanism.** Stores a multi-level tree built bottom-up: leaf nodes are text chunks, soft-clustered (GMM over UMAP-reduced embeddings) and each cluster LLM-summarized into a parent, recursively to a root — retrieval units at several abstraction levels. The index is built offline and static: no incremental write, conflict resolution, dedup, merge, or decay (adding data means rebuilding). Retrieval is dense: tree traversal (descend by cosine similarity) or the usually-better collapsed tree (flatten all nodes, take top-k by embedding similarity). No graph traversal, no BM25.

**Numbers.** RAPTOR + GPT-4 improves best QuALITY accuracy by 20% absolute (SOTA); consistent gains on NarrativeQA and multi-step QA (arXiv:2401.18059).

**Borrow.**
- P1: recursive cluster-then-summarize is a template for building higher-altitude rules from many specific signals (specific rule -> sibling family -> general policy).
- P3: the multi-level view suggests representing a too-narrow rule alongside a broader summary node so sibling evidence is not swallowed.
- P2: none direct — static, no incremental pairing.
- P4: weak — static index must be rebuilt, the maintenance cost our append-only design wants to avoid; more a structuring idea than an online-update model.

#### ReadAgent — ICML 2024 main-conference poster (PMLR v235, pp. 26396-26415) — https://proceedings.mlr.press/v235/lee24c.html

**Mechanism.** Targets a single long document, not a persistent cross-session store. Three LLM-driven steps: (1) episode pagination — the LLM chooses breakpoints to group text into "pages"; (2) memory gisting — each page is compressed into a short gist, and concatenated gists form a compact episodic memory; (3) interactive look-up — given a query, the LLM reads the gists and decides which original pages to re-expand and re-read. Write is one-pass compression; no conflict handling, dedup, merge, or decay — gists are not reconciled. Retrieval is LLM-driven page selection over the gist index (agentic, index/keyword-style), explicitly not dense embeddings.

**Numbers.** Extends effective context window 3.5-20x; outperforms retrieval/long-context baselines on QuALITY, NarrativeQA, QMSum (arXiv:2402.09727).

**Borrow.**
- P1: gisting = lossy compression of raw content into a compact recallable summary — a template for turning verbose delivery instructions into short storable rules while keeping a pointer to re-expand.
- P4: two-tier gist-plus-lookup keeps recall cheap as volume grows — maps to our small hot store + deterministic recall.
- P2/P3: none direct — single-document, no cross-item pairing, merge, or repair.

#### Larimar — ICML 2024 main-conference poster (PMLR v235, pp. 10109-10126) — https://proceedings.mlr.press/v235/das24a.html

**Mechanism.** Couples a frozen LLM with a distributed episodic memory implemented as a fixed-size real-valued matrix (K slots), à la the Kanerva Machine. To write, an encoder maps input episodes to addressing weights and the memory is updated one-shot via a closed-form least-squares (pseudo-inverse) solve — no gradient training — enabling fast sequential edits (re-solving the addressing). Conflict/repair is at the vector level: overwriting a fact re-solves the same address, and it exposes an explicit selective-forgetting operation that subtracts a fact's contribution (used for retraction and leakage prevention). Retrieval is content-based addressing (dense/associative attention over slots in latent space), not BM25/keyword. Bounded capacity gives implicit eviction pressure.

**Numbers.** 4-10x (reported also as 8-10x) speedup on sequential fact editing vs baselines at comparable accuracy, including sequential editing; strong generalization to long contexts (arXiv:2403.11901).

**Borrow.**
- P3: one-shot write plus an explicit selective-forget operator is a clean model for repairing mislearned rules and retiring stale ones without retraining; edit + selective-forget as paired operations is the borrow.
- P4: fixed-capacity latent memory robust across many sequential edits — the "stay correct over many rounds" property.
- P2: content-addressed slot read is analogous to pairing a new signal to an existing entry, but in dense latent space rather than our lexical store.
- P1: none direct.

#### MemoryLLM / M+ — ICML 2025 main-conference poster (PMLR v267, pp. 63308-63323); extends MemoryLLM (ICML 2024) — https://proceedings.mlr.press/v267/wang25au.html

**Mechanism.** MemoryLLM injects a large pool of fixed-size latent memory tokens into every transformer layer as a self-updatable knowledge store. To write/update, new context is compressed into memory tokens and merged by dropping a random subset of old tokens and inserting the new ones — an implicit exponential-decay forgetting schedule rather than explicit conflict detection; no duplicate-merge, staleness handled statistically by random eviction. M+ adds a CPU-offloaded long-term memory plus a co-trained retriever operating in hidden-state space to pull back relevant old tokens. Retrieval is dense (learned latent similarity), not BM25/keyword. Eviction/decay is central: random-drop update and retriever-gated recall.

**Numbers.** M+ extends effective knowledge retention from under 20k tokens to over 160k tokens at similar GPU overhead (arXiv:2502.00592).

**Borrow.**
- P3: random-drop is a cautionary contrast — statistical forgetting risks silently dropping still-valid sibling evidence, exactly the mislearning we must avoid; argues for explicit relation judgement over blind eviction.
- P4: designed for retention across very long horizons.
- P1/P2: none direct — no explicit salience scoring or entry pairing; both learned/implicit.

#### EM-LLM — ICLR 2025 main-conference poster (ID 30579) — https://iclr.cc/virtual/2025/poster/30579

**Mechanism.** Segments the incoming token stream into episodic events online using Bayesian surprise (a spike in negative log-likelihood marks a boundary), then refines boundaries with graph-theoretic community detection/modularity over the attention-similarity graph so each event is internally coherent. Each event's KV cache is stored as a memory unit; append-only per event, no rewriting, merge, decay, or training. Retrieval is two-stage: (1) similarity-based k-NN selection of relevant events (dense) plus (2) a temporally-contiguous buffer pulling neighboring-in-time events, mimicking human free recall. No explicit eviction beyond a bounded retrieval budget.

**Numbers.** Outperforms InfLLM on LongBench/∞-Bench; performs retrieval across 10M tokens; often beats full-context baselines (arXiv:2407.09450).

**Borrow.**
- P1: Bayesian-surprise boundary detection is a concrete, generative-model-free salience signal for WHEN a new requirement-worthy segment starts — directly transferable to "what to extract."
- P2: the two-stage (similarity + temporal-contiguity) recall is a pairing template, to which we would add lexical/BM25.
- P4: event-structured store aids long-horizon recall.
- P3: none direct — append-only, no repair.

#### Titans — NeurIPS 2025 main-conference poster — https://neurips.cc/virtual/2025/poster/119639

**Mechanism.** A neural long-term memory module whose parameters are updated at TEST TIME by gradient-descent-like steps, storing knowledge in the weights of a small MLP memory rather than explicit slots. Write uses a surprise metric (gradient of the loss on the incoming token) modulated by data-dependent momentum and an adaptive forgetting/weight-decay gate — surprising inputs are memorized more strongly, the forget gate decays old memory (a learned continuous conflict/decay mechanism, not discrete edits). Retrieval is a forward pass through the memory MLP (associative, parametric), not BM25/keyword. Three variants combine it with attention as short-term memory.

**Numbers.** Scales to 2M+ token context; beats Transformer/linear-recurrent baselines on long-context and needle tasks (arXiv:2501.00663).

**Borrow.**
- P1: surprise = gradient-magnitude salience echoes EM-LLM, reinforcing surprise as a principled "what to store" criterion.
- P3: the adaptive forget gate is a conceptual model for controlled decay/retirement.
- P2/P4: mostly none direct — architectural/parametric, does not map onto our discrete append-only lexical store.

#### Recurrent Memory Transformer (RMT) — NeurIPS 2022 main-conference poster (NeurIPS vol. 35) — https://proceedings.neurips.cc/paper_files/paper/2022/hash/47e288629a6996a17ce50b90a056a0e1-Abstract-Conference.html

**Mechanism.** Adds special read/write memory tokens to the input and output of a segment-level recurrent Transformer. Storage is the small set of memory-token vectors carried between segments; writing happens implicitly as the transformer processes each segment and emits updated memory tokens for the next. No explicit conflict detection, duplicate merging, or salience scoring — a learned continuous state overwritten each step, so old information decays implicitly if not re-encoded. Retrieval is self-attention over memory tokens (dense), not keyword/BM25. No explicit eviction beyond the fixed token budget.

**Numbers.** Matches Transformer-XL on language modeling; outperforms it on tasks needing longer effective context (arXiv:2207.06881).

**Borrow.**
- P4: demonstrates carrying compressed state across many segments/rounds, but the state is opaque and learned.
- P1/P2/P3: none direct — architectural backbone work; no auditable explicit store.

#### Memorizing Transformers — ICLR 2022 Spotlight (main conference) — https://iclr.cc/virtual/2022/spotlight/6065

**Mechanism.** Adds a non-differentiable external memory of past (key, value) pairs from one layer and augments attention with a k-NN lookup into it. Writing is append-only: internal key/value representations are pushed into the bank at inference, with no gradient update and no merge/conflict resolution of duplicates. When capacity is exceeded, simple FIFO eviction drops the oldest entries. Retrieval is approximate k-NN over stored keys — dense vector similarity, not BM25/keyword — and retrieved values are blended with local attention via a learned gate.

**Numbers.** Enables memory up to 262k tokens with gains matching a much larger dense model (arXiv:2203.08913).

**Borrow.**
- P4: append-only external memory + gated read scales to large stores over long runs, supporting our append-only + deterministic-recall design.
- P2: k-NN pairing is the dense analog of our BM25 pairing — same problem, different index.
- P1/P3: none direct — no salience, no repair/merge.

#### LongMem — NeurIPS 2023 main-conference poster — https://neurips.cc/virtual/2023/poster/72461

**Mechanism.** Decouples memory from the backbone: a frozen LLM is the memory encoder producing key-value pairs cached in an external bank, and a trainable residual SideNet is the memory reader/retriever. Writing is append into the cached KV bank; no explicit conflict detection or duplicate merge, and the bounded bank uses token-level FIFO-style eviction (decoupling avoids the memory staleness of joint training). Retrieval is chunk-level k-NN attention over cached keys — dense similarity, not BM25/keyword — fused by the SideNet.

**Numbers.** Enlarges memory to 65k tokens; improves over strong long-context baselines on ChapterBreak and many-shot ICL (arXiv:2306.07174).

**Borrow.**
- P4: decoupled frozen-encoder + separate reader mirrors our separation of an append-only store from recall, and its explicit anti-staleness motivation is relevant to long-term maintenance.
- P2: chunk-level retrieval is a dense pairing analog.
- P1/P3: none direct.

#### ROME (Rank-One Model Editing) — NeurIPS 2022 main-conference poster (NeurIPS vol. 35) — https://proceedings.neurips.cc/paper_files/paper/2022/hash/6f1d43d5a82a37e89b0665b33bf3a182-Abstract-Conference.html

**Mechanism.** Edits factual knowledge in MLP weights, treating a mid-layer MLP as a linear key-value associative store (key = subject representation, value = fact). Causal tracing locates the decisive layer, then a single fact is written via a closed-form rank-one update mapping the subject key to a new value while minimally perturbing others — a targeted overwrite that IS the conflict-resolution mechanism (new value replaces old for that key). One fact at a time; no duplicate-merge, no decay. Retrieval is the ordinary forward pass (parametric), not BM25/keyword. No eviction — edits are permanent weight changes.

**Numbers.** Maintains both specificity and generalization on counterfactual edits (CounterFact) where prior editors trade one for the other (arXiv:2202.05262).

**Borrow.**
- P3: a precise, localized overwrite that corrects one fact without disturbing neighbors is directly the "repair a mislearned rule without swallowing siblings" problem — argues for surgical, scoped edits.
- P2: key-value locate-then-write is a pairing operation (find the right slot before writing).
- P1/P4: none direct — single-edit, parametric.

#### MEMIT (Mass-Editing Memory in a Transformer) — ICLR 2023 main-conference poster (top-25%) — https://iclr.cc/virtual/2023/poster/11880

**Mechanism.** Generalizes ROME to write MANY facts at once by spreading closed-form updates across a range of critical mid MLP layers. Storage is again MLP-as-key-value weights; writing solves a single least-squares objective inserting thousands of key-value associations simultaneously while preserving unrelated ones, so batch conflicts resolve jointly. No explicit duplicate-merge or decay — edits are permanent weight deltas. Retrieval is the standard forward pass (parametric), not BM25/keyword. No eviction.

**Numbers.** Scales to thousands of edits on GPT-J (6B) and GPT-NeoX (20B), orders of magnitude beyond prior editors (arXiv:2210.07229).

**Borrow.**
- P3/P4: directly about maintaining correctness while accumulating MANY edits — its batched, mutually-constrained update models consolidating many requirements at once without the drift sequential edits cause (relevant to duplicate consolidation and multi-round stability).
- P2: the joint solve implicitly pairs each new fact to its slot.
- P1: none direct.

#### MEND (Model Editor Networks with Gradient Decomposition) — ICLR 2022 poster (main conference) — https://iclr.cc/virtual/2022/poster/6846

**Mechanism.** Trains small auxiliary hypernetworks that take the fine-tuning gradient for a single desired edit and transform it (via a low-rank gradient decomposition) into a localized weight update to the base model. Storage is parametric (edits go into base weights); writing is a learned gradient transform applied per edit, localizing the change to reduce collateral damage — the transform is what keeps one edit from corrupting others, but there is no explicit conflict/duplicate detection and no decay/eviction. Retrieval is the ordinary forward pass, not keyword/BM25. Edits are permanent.

**Numbers.** First editor (at publication) to effectively edit 10B+ parameter models; editor trainable in under a day on one GPU (arXiv:2110.11309).

**Borrow.**
- P3: learning a corrective transform that applies a targeted edit while minimizing collateral is conceptually the "repair without side effects" goal — but gradient/parametric, not our FLASH-tier, non-training, append-only store.
- P1/P2/P4: mostly none direct.

#### Mem0 — arXiv 2504.19413; admitted via open-source: GitHub mem0ai/mem0 61,615 stars (secondary sources cite ECAI 2025, which would not qualify anyway) — https://api.github.com/repos/mem0ai/mem0

**Mechanism.** Two-phase pipeline. Extraction pulls salient candidate facts from the latest turns + a rolling summary. The Update phase is the core: for each candidate fact it retrieves the top-s semantically similar existing memories (dense vector search) and hands fact+neighbors to the LLM via a tool/function-calling interface that must choose exactly one of ADD (novel), UPDATE (augment an existing memory), DELETE (new info contradicts an old memory), or NOOP (redundant). Conflicts resolve by recency (newest wins); it avoids physical deletion, marking obsolete edges invalid to preserve temporal reasoning. Retrieval is dense embeddings; the Mem0^g graph variant adds entity-node lookup plus embedding-ranked relationship triplets. No time-decay; eviction is logical (invalidation), not scored forgetting.

**Numbers.** LOCOMO overall LLM-as-Judge J = 66.88 (Mem0) / 68.44 (Mem0^g); 91% lower p95 latency (1.44s vs 17.1s); ~7k vs 26k tokens per conversation (arXiv 2504.19413v1).

**Borrow.**
- P2+P3 (highest-value in this bucket): the ADD/UPDATE/DELETE/NOOP tool schema over top-s retrieved neighbors is almost exactly our relation-judgement head (reinforce/contradict/merge/retire) and is FLASH-tier-friendly (one function call, no training).
- P3: "newest wins + mark-invalid, never hard-delete" is a directly reusable append-only maintenance policy that keeps an audit trail.
- P4: recency-prioritized conflict resolution keeps them correct as memories accumulate.

#### Generative Agents — UIST 2023 (excluded venue); admitted via open-source: GitHub joonspk-research/generative_agents 21,799 stars — https://api.github.com/repos/joonspk-research/generative_agents

**Mechanism.** Stores an append-only "memory stream" of timestamped natural-language records (observations, generated reflections, plans). Write is pure append; no dedup/merge/delete. Maintenance via two derived mechanisms: (1) each memory gets an LLM-assigned importance/poignancy score at write time; (2) "reflection" fires when summed recent importance crosses a threshold, prompting the LLM to synthesize higher-level abstractions from retrieved memories and write them back as new nodes — bottom-up consolidation into a tree of increasingly abstract memories. Retrieval scores every memory by a weighted sum of recency (exponential decay), importance, and relevance (embedding similarity), then feeds the top-scored into context. No eviction — decay only reweights ranking.

**Numbers.** Ablation: the full model (recency+importance+relevance+reflection) is rated most believable; removing all three drops believability sharply (human eval, arXiv:2304.03442). No single leaderboard metric.

**Borrow.**
- P1: the LLM importance/poignancy score at write time is a concrete salience-scoring recipe; recency+importance+relevance is a deterministic recall ranking formula.
- P3: threshold-triggered reflection models periodic offline consolidation that distills scattered signals into a higher-level rule (maps to our merge/consolidate).
- P2: weak — no explicit pairing, no conflict resolution.

#### G-Memory — NeurIPS 2025 main-conference Spotlight Poster — https://neurips.cc/virtual/2025/poster/116187

**Mechanism.** Stores a three-tier graph hierarchy (organizational-memory inspired): an insight graph (generalizable distilled lessons), a query graph (task/query nodes), and an interaction graph (fine-grained agent collaboration trajectories). After each task, new interaction traces are appended to the interaction graph and distilled generalizable insights are promoted upward into the insight tier, so the hierarchy evolves cross-trial. Retrieval traverses the hierarchy — matching the query, walking down to relevant past interactions and up to applicable insights — i.e. graph traversal rather than flat dense lookup. Maintenance is additive/promotion-based; no explicit contradiction/delete or decay.

**Numbers.** Improvements up to ~20% on embodied/knowledge/general reasoning benchmarks over prior multi-agent-system memory baselines across five benchmarks (OpenReview mmIAp3cVS0).

**Borrow.**
- P3+P4: the promote-specifics-into-general-insights hierarchy is a consolidation pattern that keeps evidence (interaction tier) separate from the abstracted rule (insight tier) — so a rule can be re-derived from retained evidence during repair.
- P2: hierarchical graph traversal as a pairing route from query to the right insight.
- Multi-agent framing is extra to our single-user setting, but the tiering transfers.

---

#### Rejected / Uncertain works

| Work | Actual status | Why excluded |
|---|---|---|
| ExpeL: LLM Agents Are Experiential Learners | AAAI 2024 Oral; GitHub LeapLabTHU/ExpeL 227 stars | AAAI is not ICML/ICLR/NeurIPS main; 227 stars is below the 2,000-star open-source bar. (High relevance regardless: ADD/UPVOTE/DOWNVOTE/EDIT is a proven reinforce/contradict/retire scheme for P3.) — https://ojs.aaai.org/index.php/AAAI/article/view/29936 |
| Dynamic Cheatsheet | EACL 2026 long paper; GitHub suzgunmirac/dynamic-cheatsheet ~275 stars | EACL is not ICML/ICLR/NeurIPS main; ~275 stars below the star bar. (Relevant for P3: curator self-curation/rewrite-and-prune.) — https://aclanthology.org/2026.eacl-long.333/ |
| CLIN | COLM 2024; GitHub allenai/clin 89 stars | COLM does not meet the academic bar; 89 stars below the star bar. (Relevant: necessary/helpful/unhelpful + confidence belief-revision for P2/P3.) — https://colmweb.org/2024/AcceptedPapers.html |
| MemWalker ("Walking Down the Memory Maze") | arXiv:2310.05029; submitted to ICLR 2024 but NOT accepted (PDF still bears "Under review" header, absent from proceedings); no qualifying repo | Unrefereed / arXiv-only; fails the academic bar and has no >=2,000-star repo; not a benchmark, so no exception applies. — https://openreview.net/forum?id=H5XZLeXWPS |
| MemoryBank | AAAI 2024; GitHub zhongwanjun/MemoryBank-SiliconFriend 441 stars | AAAI is not ICML/ICLR/NeurIPS main; 441 stars below the star bar. (Relevant for P3/P4: Ebbinghaus forgetting-curve reinforce-on-recall + time-decay, computable with no LLM call.) — https://ojs.aaai.org/index.php/AAAI/article/view/29946 |
| Sleep-time Compute | arXiv:2504.13171, no ICML/ICLR/NeurIPS acceptance; GitHub letta-ai/sleep-time-compute 136 stars | arXiv-only preprint; fails the academic bar; 136 stars below the star bar. (Relevant for P3/P4: run consolidation/repair as an offline batch pass off the critical path.) — https://api.github.com/repos/letta-ai/sleep-time-compute |

Note: JSON entries for ExpeL, Dynamic Cheatsheet, CLIN, MemoryBank, and Sleep-time Compute carry rich mechanism/borrow notes despite the REJECTED verdict; those P-mappings are summarized parenthetically above but the works remain outside the admitted set on the stated bar.

## 3. Open-source line

### Open-source (GitHub ≥ 2k stars)

#### mem0 (mem0ai/mem0) — 61,615 stars ([source](https://api.github.com/repos/mem0ai/mem0))

**Mechanism.** Stores extracted natural-language "memories" (facts/preferences) with multi-level scoping (user/session/agent) as vector-embedded records plus a keyword index. The April 2026 algorithm moved to an ADD-only extraction model (one LLM call, no explicit UPDATE/DELETE): entities are extracted, embedded, and linked across memories so semantically related items connect rather than duplicate. Earlier versions used an LLM to choose ADD/UPDATE/DELETE/NOOP against retrieved similar memories as the primary conflict-resolution step. Retrieval fuses three parallel-scored signals — dense vector similarity, **BM25 lexical match**, and entity matching — with temporal ranking over current/past/future state. No hard decay or eviction; stale facts are superseded by newer ones rather than aged out.

**Numbers.** README benchmark table: LoCoMo 92.5, LongMemEval 94.4, BEAM(1M) 64.1, ~0.9–1.1s latency. The original mem0 paper additionally claimed ~26% relative gain over OpenAI memory with ~90% token savings.

**Borrow.**
- P1: single-LLM-call extraction prompt and salience-by-extraction is a directly reusable template for our FLASH-tier extractor.
- P2: entity linking (embed + link extracted entities) is exactly a pairing mechanism to attach a new signal to related entries without a dense-only match; adaptable to our BM25/KV constraint.
- P3: weaker now that UPDATE/DELETE were removed, but the old ADD/UPDATE/DELETE/NOOP decision is a repair template.
- P4: multi-round is explicitly stress-tested via LongMemEval.

#### Letta / MemGPT (letta-ai/letta) — 23,943 stars ([source](https://api.github.com/repos/letta-ai/letta))

**Mechanism.** Descendant of the MemGPT paper (LLM-as-OS). Memory is tiered: bounded in-context "core memory" blocks (persona + human facts) plus out-of-context archival and recall memory backed by a DB with vector/text search. The agent self-edits its own memory via tool calls (`core_memory_append/replace`, `archival_insert/search`), using "heartbeat" continuations to page data in and out when the context window fills; eviction is the OS-paging analogy. Conflict/duplicate handling is not a fixed rule — it is delegated to the agent's own reasoning when it rewrites blocks. Retrieval is agent-invoked search over archival/recall stores rather than an always-on fused ranker.

**Numbers.** None reported in the data.

**Borrow.**
- P3: self-editing memory (agent rewrites/replaces its own blocks) is a concrete repair loop for a mislearned, too-narrow rule.
- P1: bounded core memory forces an explicit salience decision about what stays in-context vs. archival — salience budgeting.
- P4: OS-style paging is designed for correctness across long horizons.
- Caveat: self-edit conflict handling is non-deterministic, at odds with our deterministic-recall requirement.

#### Zep / Graphiti (getzep/graphiti) — 29,154 stars, not archived ([source](https://api.github.com/repos/getzep/graphiti))

**Mechanism.** Stores a **bi-temporal temporal knowledge graph**: entity nodes with evolving summaries, fact/relationship edges each carrying validity windows (when a fact became true and when superseded), and episode nodes preserving raw-source provenance. On write, new episodes are extracted into nodes/edges incrementally; when new information contradicts an existing edge, the old edge is INVALIDATED (marked expired) rather than deleted, preserving full history — its core conflict-resolution mechanism — with entity resolution to merge references to the same node. Retrieval is hybrid and notably includes **BM25 keyword search and graph traversal** alongside semantic embeddings, returning results without an LLM summarization step. No aging decay; lifecycle is governed by temporal validity windows.

**Numbers.** The README omits numbers; the Zep paper (arXiv 2501.13956) reports 94.8% on DMR and ~18.5% accuracy improvement plus large latency reduction on LongMemEval vs. a full-context baseline (second-hand from the paper abstract, not re-verified).

**Borrow.**
- P3: edge invalidation instead of destructive delete is essentially our append-only store with a "retire" status — a clean template for repairing a contradicted rule while keeping history.
- P2: entity-resolution-on-insert is a direct pairing mechanism (attach new edge to the right existing node).
- P4: bi-temporal validity keeps recall correct as facts change over many rounds.
- Bonus: BM25 + graph traversal remain useful inspectable signals and can be fused with a lightweight local embedding ranker.

#### cognee (topoteretes/cognee) — 29,260 stars, not archived ([source](https://api.github.com/repos/topoteretes/cognee))

**Mechanism.** Stores a dual layer: a knowledge graph (entities + relationships) plus vector embeddings, over pluggable backends (Neo4j, pgvector, Redis, or unified Postgres). Writes run an ECL-style pipeline: `add` (ingest raw data) → `cognify` (LLM extracts entities/relations, builds graph + embeddings) → optional `improve/refine`; the `remember()` op bundles add + cognify + improve. Deduplication and consolidation happen at the graph level by connecting extracted entities into existing structure rather than by an explicit overwrite rule. Retrieval is multi-modal (graph traversal, vector similarity, keyword) with an auto-router selecting a strategy per query. No explicit decay/eviction described.

**Numbers.** README BEAM long-context: 0.79 at 100K tokens (vs 0.735 prior SOTA) and 0.67 at 10M tokens (vs 0.641), framed by the authors as "directional signals."

**Borrow.**
- P1: the `cognify` extraction stage is a reusable extract-and-structure pass.
- P3: graph-level consolidation (new entities merge into existing structure) is a maintenance pattern for de-duplication.
- P4: auto-router over multiple retrieval strategies.
- Weaker on explicit conflict-resolution rules than Graphiti/SuperMemory.

#### SuperMemory (supermemoryai/supermemory) — 28,589 stars, not archived ([source](https://api.github.com/repos/supermemoryai/supermemory))

**Mechanism.** Stores extracted facts from conversations plus user profiles (static long-term facts + dynamic recent activity) and knowledge-base documents in a unified store. On write it performs automatic CONTRADICTION RESOLUTION: when a newer fact conflicts with an older one (e.g. moved NYC→SF), the newer supersedes the older. It also implements automatic FORGETTING: temporary/time-bound facts ("exam tomorrow") expire once the date passes. Retrieval is a single hybrid query combining vector semantic search, **keyword/lexical retrieval** over docs, and a memory-specific personalized-context lookup — RAG + memory returned together.

**Numbers.** README claims LongMemEval 95% Recall@15 with 99.4% context reduction (~720 tokens), and #1 on LoCoMo and ConvoMem (vendor self-report).

**Borrow.**
- P3: explicit automatic contradiction resolution (newer supersedes older) + time-based expiry is the closest off-the-shelf model of our "contradict → retire" and forgetting flows.
- P2: detecting that a new fact contradicts a specific old one is a pairing + judgement step we can mirror.
- P1: separating stable vs. temporary facts is a salience/TTL signal worth copying.
- Retrieval mixes keyword search — compatible with our BM25/KV constraint.

#### MIRIX (Mirix-AI/MIRIX) — 3,558 stars ([source](https://api.github.com/repos/Mirix-AI/MIRIX))

**Mechanism.** Stores six typed memory components — Core (persona/human blocks), Episodic, Semantic, Procedural, Resource, and a Knowledge Vault — each managed by a dedicated agent under a meta memory-manager. On write, incoming signals are routed to the appropriate memory type; an "Auto-Dream" consolidation pass periodically reviews existing entries, MERGES DUPLICATES, and resolves stale or conflicting data before writing back through memory tools — its explicit maintenance/repair mechanism. Retrieval uses **Postgres-native BM25 full-text search** combined with vector similarity, scoped by user and conversation context.

**Numbers.** The README gives no numbers; the MIRIX paper (arXiv 2507.07957) is cited and reportedly claims a large accuracy gain on ScreenshotVQA and strong LoCoMo results (second-hand, not re-verified).

**Borrow.**
- P3: "Auto-Dream" (offline pass that merges duplicates and resolves stale/conflicting entries) is almost a direct blueprint for our P3 consolidation-and-repair job.
- P2: routing a new signal to the correct one of six memory types is a coarse pairing/classification we can reuse to choose which rule family a signal belongs to.
- P1: the typed taxonomy is a structured extraction schema.
- Uses BM25 — fits our tooling.

#### Memobase (memodb-io/memobase) — 2,789 stars ([source](https://api.github.com/repos/memodb-io/memobase))

**Mechanism.** Stores a customizable structured USER PROFILE (categories like basic_info, demographics, education, interests, psychological traits, work) plus a time-aware event timeline. Writes are buffered: chat/data "blobs" accumulate and flush to permanent memory when the buffer hits ~1024 tokens or ~1h idle (or on manual flush); the LLM updates profile slots against the fixed schema, and raw blobs are discarded after processing. The schema constrains what gets learned, so conflicts resolve as slot updates within predefined categories. Retrieval: `context()` assembles relevant profile + events into a prompt string; profile access is plain SQL (sub-100ms), event search ~500–1000ms.

**Numbers.** README claims top-tier / SOTA LoCoMo search performance vs mem0, langmem, and zep, especially on temporal questions; no single headline figure exposed in the fetched content.

**Borrow.**
- P1: the fixed profile schema is a clean way to bound WHAT to extract — directly analogous to our "only delivery requirements" scoping, so slots become rule categories.
- P3: buffered flush = batched consolidation rather than per-message writes, reducing churn.
- P4: profile stored as SQL slots gives deterministic, low-latency recall, matching our KV/deterministic-recall design.
- P2: slot-based updating is a lightweight pairing (new signal → named slot).

#### MemOS / Memory-OS (MemTensor/MemOS) — 10,363 stars ([source](https://api.github.com/repos/MemTensor/MemOS))

**Mechanism.** Frames memory as an OS with composable "MemCube" knowledge bases spanning plaintext and (per the vision) activation and parameter memory; multiple cubes are managed together. Writes go through an asynchronous MemScheduler (millisecond-latency ingest) exposing a unified add/edit/delete interface, with natural-language feedback so users can correct or refine memories over time — its editable repair path. Retrieval is hybrid, combining **full-text search (SQLite FTS5)** with vector methods across the multi-modal cubes. Cube governance/versioning is emphasized for long-term correctness.

**Numbers.** README: LoCoMo 88.83, LongMemEval 89.20, and ~35.24% token savings (vendor self-report).

**Borrow.**
- P3: explicit edit/delete plus natural-language-feedback correction is a usable repair interface for mislearned rules.
- P4: cube governance/versioning targets long-horizon correctness.
- Retrieval uses FTS5 (lexical) — compatible with our BM25/KV constraint.
- P1/P2: less differentiated; scheduling is infra, not extraction/pairing logic.

#### Memary (kingjulio8238/Memary) — 2,634 stars, not archived but inactive (last push 2024-10-22) ([source](https://api.github.com/repos/kingjulio8238/Memary))

**Mechanism.** Agent memory layer storing a knowledge graph (Neo4j/FalkorDB) plus two side stores: a Memory Stream capturing entities + timestamps (breadth) and an Entity Knowledge Store tracking frequency and recency of references to each entity (depth). Write/update injects final agent responses back into the KG and appends newly encountered entities; there is no explicit contradiction/merge/retire resolution — it accumulates. Retrieval is **graph traversal**: it extracts key entities from a query, builds a subgraph up to depth 2, and does multi-hop reasoning joining subgraphs (not BM25 or dense-only). Decay/eviction exists: when the context window fills it summarizes older context and applies an "eviction rate," keeping recent messages and compressing the rest.

**Numbers.** None reported in the data.

**Borrow.**
- P1: the entity knowledge store's frequency + recency scoring is a ready-made salience signal ("often mentioned + recently referenced = important"), directly transferable to scoring rule salience.
- P2: entity-centric writeback (attach new mentions to existing graph entities) is a pairing mechanism.
- Retrieval is pure graph traversal (no dense reliance), fitting the inspectable half of our allowed hybrid toolset.
- P3/P4: weaker — no explicit conflict resolution or forgetting.

#### khoj (khoj-ai/khoj) — 35,967 stars ([source](https://api.github.com/repos/khoj-ai/khoj))

**Mechanism.** Personal-AI / second-brain app that ingests user documents (PDFs, Markdown, Notion, Word, org-mode) and chat history, indexing them for retrieval. It stores document chunks and embeddings and writes by re-indexing on sync; there is no explicit conflict-resolution, merge, or reinforce/retire logic — new content is added and stale docs are re-indexed rather than reconciled. Retrieval is **dense semantic search** over embeddings (not BM25/keyword or graph), optionally with a cross-encoder rerank. No decay/eviction of memories; it is closer to a personal RAG/search assistant than a structured agent-memory store.

**Numbers.** None reported in the data.

**Borrow.**
- None direct — mostly a RAG search product. Weak P1 only: its ingest/chunking pipeline shows document-level salience but no explicit salience scoring; no P2/P3/P4 mechanism (no pairing, no repair, no multi-round reconciliation).

#### txtai (neuml/txtai) — ~12,750 stars ([source](https://api.github.com/repos/neuml/txtai))

**Mechanism.** General-purpose "embeddings database" framework, not a memory system per se. It stores an embeddings index that unions sparse (**BM25/keyword**) and dense vector indexes, a graph network, and a relational (SQL) store over text/docs/audio/images. Writes are index/upsert operations; it exposes SQL-style updates but has no built-in conflict/merge/reinforce/retire semantics — dedup and reconciliation are left to the application. Retrieval supports hybrid search: sparse BM25 keyword search AND dense vectors, plus graph traversal and topic modeling — directly relevant to our BM25 + lightweight-local-embedding candidate retrieval. No decay/eviction.

**Numbers.** None reported in the data.

**Borrow.**
- P1/P2 tooling substrate: its hybrid sparse+dense design supports our RRF direction, provided the dense side stays local and light enough for CPU/integrated-GPU execution.
- No native P3 repair or P4 multi-round correctness logic.

#### microsoft/graphrag — 34,812 stars ([source](https://api.github.com/repos/microsoft/graphrag))

**Mechanism.** LLM-driven pipeline that stores a knowledge graph: it slices the corpus into TextUnits, extracts entities, relationships, and key claims, then runs hierarchical Leiden community detection and generates bottom-up community summaries. Write/update is batch re-indexing; entity resolution/deduplication (merging duplicate entities) happens during graph construction, but the docs do not expose an incremental conflict/reinforce/retire policy — updates rebuild or extend the graph. Retrieval is explicitly **graph-based**, not dense-only: Local Search fans out from an entity to its neighbors, Global Search reasons over community summaries in a map-reduce, and DRIFT blends both. No decay/eviction.

**Numbers.** The paper (arXiv:2404.16130) reports "substantial improvement" over conventional RAG on comprehensiveness and diversity for global sensemaking questions on ~1M-token datasets; exact head-to-head win-rates are in the full PDF, not the abstract.

**Borrow.**
- P2: entity-resolution/dedup during graph build is a template for matching a new signal to the right existing entry.
- P1: claim/entity extraction from raw text maps to our "what to extract."
- P3: community summarization = consolidation of duplicates into a canonical summary, a model for merging sibling rules.
- Retrieval is graph-traversal, transferable to graph/KV recall without dense embeddings.

#### Rejected / uncertain works

| Name | Actual status | Why excluded |
|---|---|---|
| MemoryOS (BAI-LAB/MemoryOS) | EMNLP 2025 main (claimed oral); GitHub 1,519 stars ([source](https://api.github.com/repos/BAI-LAB/MemoryOS)) | Below the 2k-star open-source bar (1,519). Venue-backed, but the "EMNLP 2025 oral" claim is sourced only from the repo README and unverified against the official accepted-papers list. |
| Motorhead (getmetal/motorhead) | GitHub 917 stars; `archived:false` but README states no longer maintained, last push 2025-07-22 ([source](https://api.github.com/repos/getmetal/motorhead)) | Below the 2k-star threshold (917) and effectively abandoned; retrieval is dense-only VSS with lossy summarization roll-up (no conflict/merge/reinforce/retire), so low transfer value. |

## 4. Evaluation-methodology line

### Evaluation methodology

Evaluating a memory layer means testing not the fluency of any single answer but whether stored requirements stay correct as interactions accumulate, whether new signals attach to the right prior state, and whether stale or mislearned entries can be repaired. The benchmarks below supply the task shapes and dependency structures we adopt; the judge-reliability studies (excluded from the admitted set on venue grounds but noted in the table) inform how we score them. Each admitted work is mapped to our four pain points — P1 (what to extract / salience), P2 (pairing a new signal to the right entry), P3 (repairing mislearning / long-term maintenance), P4 (correctness across many rounds).

#### LoCoMo — ACL 2024 main (Long Papers), GitHub snap-research/locomo ~1043 stars; admitted via benchmark-exception
Evidence: https://aclanthology.org/2024.acl-long.747/

- **Mechanism.** Stores 50 machine-human-generated very-long-term conversations (avg ~300 turns, ~9K tokens, up to 35 sessions) grounded on personas plus temporal event graphs, each with ~200 QA pairs and additional event-summary and multimodal-generation tasks. It is a static benchmark, not an updating memory system: it holds only the gold dialogue history and gold answers, so any write/merge/forget policy belongs to the system under test. Retrieval is likewise a property of the tested system — LoCoMo evaluates both long-context readers and RAG (dense-retrieval) readers over the frozen history rather than fixing a retriever. Multi-turn dependency is induced by question type: single-hop, multi-hop, temporal, commonsense/world-knowledge, and adversarial labels force a multi-hop or temporal question to chain facts scattered across many sessions. Scoring is primarily deterministic token-level F1/EM against gold spans (low variance, no LLM-judge); summarization uses overlap metrics. No single-point-failure mitigation is built in — no multi-seed averaging or per-round replay — though per-question independent scoring limits cross-question error propagation.
- **Numbers.** 50 conversations, avg ~300 turns / ~9K tokens, up to 35 sessions, ~200 QA per conversation; LLMs show large gaps versus humans on the multi-hop and temporal splits.
- **Borrow.**
  - P4: the five reasoning types (esp. multi-hop + temporal + adversarial) are a ready template for stress-testing recall correctness across accumulated rounds.
  - P2: adversarial questions (deliberate near-miss distractors) map to our mis-pair / miss-pair risk — reuse as negatives for pairing a new signal to the right entry.
  - P1: temporal / event-graph grounding suggests tying salience to events.
  - P3: none direct (static benchmark, no repair mechanism).

#### LongMemEval — ICLR 2025 poster (main conference)
Evidence: https://iclr.cc/virtual/2025/poster/28290

- **Mechanism.** Stores 500 curated questions embedded in freely scalable synthetic user-assistant chat histories, targeting five abilities: information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention. The knowledge-updates and abstention slices are load-bearing for us: knowledge-updates directly tests whether a later message overrides an earlier fact (conflict/contradiction handling), and abstention tests refusing when memory lacks the answer. As a benchmark it does not itself write or merge, but the paper additionally proposes a reference memory framework (indexing → retrieval → reading) with session decomposition for value granularity, fact-augmented key expansion for indexing, and time-aware query expansion; the reference system retrieves over expanded keys/facts and supports both long-context reading and RAG. Dependency is built by scattering one question's evidence across many sessions and by knowledge-update questions that require honoring the most recent contradicting fact. Scoring uses a GPT-based LLM-judge against gold with a fixed rubric; headline metric is answer accuracy. No explicit single-point-failure mitigation (no multi-seed averaging or per-round replay); per-question independent scoring.
- **Numbers.** 500 questions; commercial assistants / long-context LLMs show ~30% accuracy drop on sustained-interaction memorization.
- **Borrow.**
  - P3 (strongest): the knowledge-updates slice is a direct analog of our reinforce-vs-contradict repair — reuse its update questions to check a new rule supersedes a stale one rather than being swallowed.
  - P2: the abstention slice maps to miss-pair — do not force a wrong pairing when nothing matches.
  - P4: multi-session and temporal reasoning across scalable histories.
  - P1: the information-extraction ability plus fact-augmented key expansion informs what to extract and how to index salient facts.

#### Multi-Session Chat / MSC — ACL 2022 long paper, main conference; admitted via benchmark-exception
Evidence: https://aclanthology.org/2022.acl-long.356/

- **Mechanism.** Stores human-human crowdworker chats spanning multiple sessions (re-engagement over hours-to-days), annotated with per-session summaries of the key personal points each speaker revealed; those summaries act as a gold "memory write" target — a compressed persona fact set carried forward between sessions. The paper's models are retrieval-augmented and summarize-and-recall memory models that read prior-session summaries or retrieve prior turns before generating, establishing that retrieval / summarize-recall beats a plain encoder-decoder with truncated context. There is no explicit conflict resolution: new sessions simply append new summarized persona points. Multi-turn dependency is inherent — a later session's correct response requires recalling something disclosed earlier. Evaluated with perplexity, F1 / next-utterance metrics, and human evaluation of engagingness and consistency (pre-LLM-judge era). No single-point-failure mitigation.
- **Numbers.** Retrieval + summarize/recall memory models outperform standard SOTA encoder-decoder baselines on long-term consistency; dataset spans up to 5 sessions per conversation.
- **Borrow.**
  - P1: the per-session gold summaries are a concrete model for extracting compact carried-forward requirements from a session — our store is exactly compressed carried-forward rules.
  - P4: multi-session recall is the original cumulative-dialogue setup.
  - P3: its absence of any conflict/update handling is a cautionary gap that motivates our contradict/retire relations.
  - P2: none direct.

#### MemoryAgentBench — ICLR 2026 main conference (arXiv 2507.05257); GitHub HUST-AI-HYZ/MemoryAgentBench ~407 stars, admission rests on the ICLR 2026 acceptance
Evidence: https://hust-ai-hyz.github.io/

- **Mechanism.** Reformats existing long-context datasets plus new datasets into a multi-turn incremental format so information arrives chunk-by-chunk and the agent must commit it to memory as it goes — explicitly simulating an agent that learns while being tested rather than reading a static context. It tests four competencies: accurate retrieval, test-time learning, long-range understanding, and selective forgetting. Selective forgetting is the differentiator: it scores whether the agent can discard or override outdated information, grading exactly the forget/retire behavior our store needs. Writes/updates are performed by the agent under test; the benchmark feeds information incrementally and probes after accumulation. Retrieval is system-dependent (long-context, RAG, and memory agents all evaluated). Dependency is the strongest of the bucket — the incremental feed itself is the dependency, with earlier turns writing state that later probes require. Scoring uses per-competency task accuracy (retrieval EM/accuracy; forgetting measured by whether stale info is correctly dropped). The incremental design means errors can compound across turns, which the paper treats as the phenomenon of interest; no multi-seed averaging is reported, but per-competency decomposition isolates where failure originates.
- **Numbers.** Four competencies; no current method masters all four, with test-time learning and selective forgetting the weakest.
- **Borrow.**
  - P4 (strongest): the incremental "learn while tested" protocol is the closest existing eval to our multi-round accumulation setting — adopt it as our evaluation shape.
  - P3: the selective-forgetting competency is a direct benchmark for our retire relation and mislearning repair.
  - P1: the test-time-learning slice tests what to commit.
  - P2: none direct, but the retrieval-accuracy slice can be repurposed to measure pairing.

#### Excluded works (REJECTED / UNCERTAIN)

| Name | Actual status | Why excluded |
|---|---|---|
| MemBench | ACL 2025 Findings; GitHub import-myself/Membench ~55 stars | ACL Findings does not meet the academic bar and no benchmark-exception was granted; star count far below the 2000 threshold. (https://aclanthology.org/2025.findings-acl.989/) |
| PerLTQA | SIGHAN-10 workshop paper (co-located with ACL 2024); GitHub Elvin-Yiming-Du/PerLTQA 5 stars | Workshop venue below the academic bar; 5 stars far below threshold; no benchmark-exception. (https://aclanthology.org/2024.sighan-1.18/) |
| The Coin Flip Judge? Reliability and Bias in LLM-as-a-Judge Evaluation | arXiv preprint 2606.13685 (Apr 2026, single author); GitHub Abelo9996/llm-judge-consistency 0 stars | Unrefereed preprint with no ICML/ICLR/NeurIPS acceptance; 0 stars; a judging-methodology study, not a memory system. (https://arxiv.org/abs/2606.13685) |
| Nine Judges, Two Effective Votes: Correlated Errors Undermine LLM Evaluation Panels | arXiv preprint 2605.29800 (May 2026); no GitHub repo | Unrefereed preprint with no ICML/ICLR/NeurIPS acceptance and no repo; a judge-panel methodology study, not a memory system. (https://arxiv.org/abs/2605.29800) |

Note on the two excluded judge-reliability preprints: although neither clears the admission bar, both bear directly on how the admitted LLM-judged benchmark (LongMemEval) and our own reinforce/contradict/merge/retire relation calls should be scored — single-trial LLM judging is noisy and correlated across models — so their prescriptions (multi-trial majority vote, position randomization, deliberately decorrelated judges, human spot-checks on low-agreement or high-impact merges/retires) are worth carrying into our P2/P3/P4 evaluation protocol even though the works themselves are not surveyed as memory systems.
