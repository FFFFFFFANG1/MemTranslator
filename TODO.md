# TODO

> 2026-07-21 起维护。原型能跑、测试全绿之后仍未做的事，按优先级。前端 demo 已冻结（不再优化 UI，功能演示够用）。

## 需要队内对齐（设计 ↔ 实现分歧）

- [x] ~~write path 调用次数约束~~：2026-07-21 采纳 (a)——设计放宽为分批 extract（5 user-turn/批，turn 压缩）+ 全局单次 consolidate；memory-design §0/§3.2/§5 已同步。

## 原型缺口（按优先级）

- [ ] **default profile fallback**（2026-07-21 产品决策，design §3.3）：MemoryEntry 加 `source: "default" | "learned"` 字段；出厂预置 default 条目参与正常 recall，个性化条目排序优先/可 SUPERSEDE 覆盖；demo memory 面板区分展示。内容集待产品定义。
- [ ] **编辑 diff 回流**：用户在 composer 里改动 polished 文本的 diff 是天然反馈信号（typeless 决策的后半截，见 memory-design §3.3），目前 demo 只记录最终发送文本，diff 没有进 write path。
- [ ] **wrong-case dump**（HMS 借鉴点）：translator 判错/漏应用的 case 全量落盘（query、召回 memory、patch、判定），pilot Task 10 实现时并入。
- [ ] **embedding 召回**：`store.recall()` 目前是 keyword+strength+新近度；design §3.3 的 embedding 混合召回未实现（当前条目量级下影响小）。
- [ ] **consolidation confidence 字段**（Mandol match-judge 协议）：Call 2 输出加 confidence + 阈值 + 向量兜底，缓解 design §6-2 的重复检测漏召。
- [ ] **`expires_hint` 语义**：extraction 输出的 `"this_session"` 提示未实现——当前直接塞进 `expires_at` 做字符串比较，非 ISO 值会因字典序恒判存活。要么在 to_entry 里解析（this_session → 不入库或立即过期），要么 prompt 里禁掉非 ISO 输出。
- [ ] **隐式 retire**：只有显式 retire；"strength=1 且 N session 未 applied → retired"（design §6-3）等 last_applied_at 数据积累后定。
- [ ] **并发写保护**：多 session 并行写同一 store 无锁（design §6-4）；v0 前提是单写者。
- [ ] tiktoken 是 OpenAI tokenizer，对 Claude 文本低估 ~15-20%——做压缩窗口预算够用（现状），若将来用于成本统计需换 `count_tokens` API。
- [ ] **两级生成**（typeless-analysis §5 启示，phase 2 设计讨论）：即时 patch（现状）+ 可选终稿深度重写；Typeless V2.0 的乱序重组/跨段撤销证明该分层在产品上成立。

## Pilot（未开始）

- [ ] 等待开跑指令：入口 [docs/2026-07-21-pilot-plan.md](docs/2026-07-21-pilot-plan.md) Task 0，go/no-go 判据 G1–G3 预注册在 §0。
- [ ] 两个人工闸门：Task 1（PrefEval 假设核验 V1–V5）、Task 9（judge 校准，需人工标 30 条）。
