# E1 舰队首跑记录（2026-07-28）

新 Suite E（生命周期回放，12 episode × 40 constraints × 5 臂）的头两次全量跑。
**无 gate**——按 spec §M6，本文只报数；阈值与权重是 §M7 的 owner 决定。

## 仪器谱系（一句话版）

四轮 pilot 各打掉一层仪器缺陷：跨语言锚（oracle CARRY 0.03 的不可能读数）→
定向 probe（考题必须对准规则的 facet，M1 的老课）→ CARRY 归 judge 频段
（E-mech 的机械主张从来只是 SUPPRESS 半边；语料 92% 定性、只有数字是
operative 锚）→ 死亡名单偏数字（trap 才咬得住）。全程 oracle 臂当仪器自检用：
它读数不合理时，先怀疑尺子，再怀疑产品。

## Run 1（12 episodes, 208 probes）

```
suite 0.594   95% CI [0.550, 0.633]（episode-cluster bootstrap，半宽 0.041）
episode_score = 0.25·CARRY(judge) + 0.45·SUPPRESS(mech) + 0.30·STATE(mech)   ← 权重临时
```

| arm | CARRY(judge) | SUPPRESS(mech) | mean chars | mean ms |
|---|---|---|---|---|
| null-generic（语料仪器） | — | 1.00 | 6 | 2097 |
| no_retire | — | **0.91** | 2277 | 2382 |
| real | 0.25 | **0.96** | **526** | 927 |
| oracle-arm | 0.54 | 0.98 | 961 | 2250 |
| full_context | — | 0.97 | **6839** | 2237 |

**能声称的**（每条对应一个臂差）：

1. **生命周期逻辑有可测价值**：real − no_retire 的 SUPPRESS 差 **+0.05**
   （0.96 vs 0.91）。一个从不失效的系统在同一套 case 上确实更差——headline
   那句话第一次有了数值形式。
2. **结构化记忆的成本论据**：full_context 需要 **13 倍的上下文**（6839 vs 526
   chars）才把 SUPPRESS 追到 0.97 vs 0.96。86 轮尺度本是 transcript 最占优的
   区间，它也没赢——且这个差距随历史长度只会单调扩大。
3. **检索+学习损失**：real CARRY 0.25 vs oracle 0.54——SUT 拿到的分数是完美
   检索天花板的一半。天花板本身只有 0.54，复现 M1 的 dilution：25+ 条活跃
   规则密度下，翻译器每次只织入一小部分（产品事实，非 bench 缺陷）。
4. **`CONSOLIDATE_ACTIVE` 分支史上首次触发**（e-12，SUT active 峰值 48）。
   全舰队触发器统计：adds 15 次、active 1 次——"active 分支实践中永不触发"
   这条产品发现在 11/12 的 episode 里仍然成立。

**产品侧新发现**：

- SUT 学习量的 persona 方差巨大：peak active 5（e-05）到 48（e-12）。
  en-persona 的三集（e-02/05/09）peak 5-11，学得最少、STATE 最低
  （0.15-0.27）——写路径对英文口语规则的抽取率低是一条未曾测到过的病。
- e-12（editor-zh）peak 48 是反向病：只囤不并（consolidation 后仍 48）。

## Run 2（run 间方差）

<!-- RUN2：跑完填 -->

## 已声明的限制

- CARRY 走 judge 频段（deepseek-v4-pro，窄 context 判据），numeric-mech
  （28 判定点/集）为零 judge 对照列；两者在 oracle 臂上一致（0.54 vs 0.32
  量级差来自 judge 接受语义等价、mech 要求逐字）。
- 9 对 I10 残余 key 劈裂（480 节点的 1.9%），报出不判。
- gold 的标注残差未测量（M3 只买了校准，没买上界——10 条的算术）。
- reword/style_rule 通道未计分（产品契约过滤，遗留 open question）。
- segment 模式未跑（chained + oracle-arm 已覆盖"学错"与"用错"的分离面）。
