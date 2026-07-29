# 隔离探针

跑一小段产品路径 N 次，看它的**分布**而不是单次结果。suite 层的分（8 persona × 3 repeat）
在 persona 内极差能到 0.58，量不动单条 prompt 规则的改动；这些探针把变量收窄到一次调用，
用 20 次重复换一个能读的数。

全部走产品通道（`claude-haiku-4-5`），单次跑约 $0.05–0.15。跑之前要把 key 弄进环境：

```bash
eval "$(grep '^export ANTHROPIC_API_KEY=' ~/.zshrc)"
uv run python bench/gen/probes/<name>.py [N]
```

| 探针 | 问题 | 2026-07-27 的结论 |
|---|---|---|
| `scope_ab.py` | 六桶的 extraction prompt 是否把规则写窄了？A/B `da52a7d^` 与 HEAD | 是。写窄的 trial 从 0/20 涨到 19/20，规则文本变成「给房东的邮件不超过120词」 |
| `trim4c_probe.py` | 精简版 4c 是否保住效果、是否伤到全局规则的 persona | 保住一半（中招 8/20，长版是 1/20）；minimalist-zh 两个臂都不写窄 |
| `writer_probe.py` | writer-zh 崩到 0.444 时 store 里到底是什么 | store 没膨胀，稳定 3 条；偶数轮系统性漏「长文档带目录」 |
| `bucket_drop_probe.py` | `parse_ops` 的 bucket 白名单是否在静默丢 op | 否，0/20。这条假设被证伪 |
| `judge_stability.py` | T 掉的那 0.017 是判分噪声还是稳定判断 | 稳定。同一条标准旧输出 8/8 yes、新输出 0/8 yes |

**这些探针会骗人，用之前先读这条。** 2026-07-27 那天四次外推错了三次半：store 膨胀、bucket 掉 op、
「4c 不是 minimalist 的病因」——全都是从隔离探针推出来的，全都被端到端跑翻掉。
最后那条错得最典型：探针比的是「无 4c」对「精简 4c」（两个都好的臂），
而真正有害的「长版 4c」根本没进探针，于是得出「4c 无罪」。

探针能证伪，不能证实。看到想要的数字之后，仍然要跑一次 E 才能下结论。

`extraction_old.py` 由 `scope_ab.py` 按需从 git 取出，不入库。
