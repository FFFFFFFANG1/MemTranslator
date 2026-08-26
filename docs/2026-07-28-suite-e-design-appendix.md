# Suite E 生命周期化：设计与对抗复核原文（2026-07-28）

> 合成方案见 `2026-07-28-suite-e-lifecycle-spec.md`。本文是它的上游材料：四条并行设计的原文，
> 以及三个对抗视角的复核。合成体在有冲突处做了取舍并说明了理由；实现时以合成体为准，
> 但图代数、scope 词表、episode 结构这些**细节只在本文里有**。


---

## 设计 1：Suite E 图验证机制：坐标由 LLM 填，关系由图算，冲突用来分配那 10 个人工标注名额

## 0. 先回答 owner 的两个前置问题

**语料在哪一级？** 12 个源给的全部是 **L0 原子规范句**（第三人称规范语气，"Use sentence case for headings"）。零条已写。owner 的判断成立且更严重：不只缺 episode，连 **L1 坐标**和 **L2 用户口吻话语**都缺。四级阶梯：

| 级 | 是什么 | 谁产出 | 今天有多少 |
|---|---|---|---|
| L0 atom | 源里的规范句 | 抓取脚本 | 0（预算表 ~770） |
| L1 constraint node | L0 + 坐标（bucket/key/scope/stance/value）+ 变异 + provenance | 廉价 LLM，**本设计的唯一 LLM 信任面** | 0 |
| L2 utterance | 实现图上一条**转移**的用户口吻消息（"别用 80 列了，以后 Python 都按 96 折行"） | 由边**生成**，不是在找到的文本上标注 | 0 |
| L3 episode | 一段可信的工作会话：若干 utterance + 任务请求 + distractor + `{app,task,lang}` 上下文，末尾一个 request | 图上一条路径的渲染 | 0 |

**方向翻转是整套设计的支点。** spec 的做法是「先写日志文本 → 人来判断每句的 effect」，那是 *推断*，不可核。改成「先建图 → 从边生成实现它的文本」，effect 就不是推断而是 **生成种子**。生成函数 `G: 意图 → 文本` 的产物可以被一个**没看见意图**的读回函数 `R: 文本 → 意图` 检验：`R(G(x)) == x` 是一条能跑的等式。跑不通时，要么文本歧义（这本身就是 spec 想保留的 ambiguous band），要么边错了。两种都是有用的信号，都不需要预先的人工判断。

---

## 1. 每条 constraint 的标注 schema

文件：`bench/graph/schema.py`（词表）、`bench/gen/annotate.py`（标注 pass）。

```json
{
  "cid": "c-0417",
  "text": "Python 代码按 96 列折行",
  "atom": {"raw": "Maximum line length is 80 characters",
           "source": "google/styleguide pyguide 3.2",
           "license": "CC-BY-3.0", "use": "mutated",
           "mutation": "80 -> 96 columns"},

  "coords": {                          // ← LLM 唯一负责的东西
    "bucket": "output_contract",
    "key":    "code.line_length",
    "polarity": "require",
    "binding":  "hard",
    "value": {"type": "numeric", "num": 96, "unit": "col", "cmp": "max"},
    "scope": {"app": "editor", "task": null, "nat_lang": null,
              "code_lang": "python", "recipient": null, "artifact": "code"}
  },

  "votes": {"key": ["code.line_length","code.line_length","code.line_length","code.width"],
            "value.num": [96,96,96,96], "scope.code_lang": ["python","python",null,"python"]},
  "conf":  {"key": 0.75, "value": 1.0, "scope": 0.75, "bucket": 1.0},

  "lifecycle_hint": {                  // ← 咨询性质，只作 D_text 的答案格式，永不建图
    "introduced_by": "u-0412",
    "expected_end": {"reason": "superseded", "by": "c-0301"}
  },

  "role": "chain",                     // ← 由图的度数导出，不由作者写
  "reachable_in": ["e-03/cp-04", "e-03/cp-05", ...],
  "defect": null
}
```

### 1.1 封闭词表（不封闭 = 关系检测失效）

`key` **必须来自注册表**，不能自由文本。两条讲同一件事的规则拿到不同 key，它们永远不会冲突，supersede 链就静默丢失——这是本设计最脆的一处，所以 key 是选择题不是填空题。注册表按 bucket 分区，每 bucket ~15 个 key，总量 ~90，直接沿用 `signals._KEY_LEXICON` 的 facet 词根扩写。

`scope` 六维，各自封闭：

| dim | 词表 | 产品能表示吗 |
|---|---|---|
| `app` | editor, ide, terminal, docs-site, slack, email-client, notebook, cli, null | ✅ |
| `task` | code-write, code-review, commit-msg, release-note, reference-page, tutorial, email, chat-reply, report, paper-analysis, slide, spec, postmortem, data-analysis, null | ✅ |
| `nat_lang` | zh-CN, en-US, en-GB, ja-JP, fr-FR, ko-KR, null | ⚠️ 见下 |
| `code_lang` | python, java, shell, sql, ts, null | ⚠️ 见下 |
| `recipient` | self, teammate, manager, customer, public, reviewer, null | ❌ bench-only |
| `artifact` | code, commit, doc, email, message, report, slide, test, config, null | ❌ bench-only |

产品的 `Requirement.scope` 只有 `{app, task, lang}`，`recall._scope_ok` 是逐维字符串相等。两个后果必须写死，否则 bench 会去断言产品结构上表达不了的东西：

1. **`lang` 是一个被重载的维度。** spec §2.1 的示例 `{"lang": "python"}` 与 `same_language` checker 里的 zh/en 是同一个字段的两种用法。一个说中文写 Python 的用户，`context.lang` 填什么都会误伤。bench 侧拆成 `nat_lang` / `code_lang`，投影回产品时按固定规则合并（`code_lang` 非空取 `code_lang`，否则取 `nat_lang`），**并把这次投影记为一条已知失真**。
2. **`recipient` / `artifact` 标 `bench_only`。** 它们参与 episode 构造与 activation gold，但**只做 BEHAVIOUR 断言**（改写里带没带），绝不做 STATE 断言（产品记录的 scope 字段对不对）。

### 1.2 `value` 的类型槽——关系代数的全部载荷

| type | 形状 | 主要来自哪个 bucket |
|---|---|---|
| `numeric` | `{num, unit, cmp: max\|min\|exact}` | output_contract（长度、列宽、条数） |
| `enum` | `{domain, val}`，domain 来自注册表（`case_style`, `register`, `format`, `channel`, `verb`…） | output_contract / communication_style / execution_policy / **task_goal**（`verb` domain: compare, evaluate, summarise, recommend, diagnose, generate, revise, explain） |
| `lang` | `{tag}` | output_contract |
| `bool` | `{val}` | execution_policy（ask-first、保真输入）、reasoning_policy（核实事实） |
| `set` | `{op: include\|exclude, items:[…]}` | **deliverables**（必须出现的信息块）、**reasoning_policy**（权衡轴：latency/cost/配置难度） |
| `ordering` | `{before, after}` | output_contract（结论先行） |
| `freeform` | `{}` | 兜底 |

这张表同时回答「哪个 bucket 能承载生命周期关系」：**六个桶全部可以**，包括 sourcing 文档担心的两个薄桶——`task_goal` 的动词是真封闭集，`reasoning_policy` 的权衡轴是真集合，两者都能算 supersede/widen。这是把它们纳入 chain 配额的结构依据。

`freeform` 是**保持诚实的逃生口**：LLM 塞不进类型槽的条目，拿不到任何链式边，只能当 `independent`。代价是 chain 配额里少几条；收益是图上每一条边都是算出来的。

---

## 2. 图

`bench/graph/relate.py` + `derive.py`。

**节点**：`Constraint`（672 条）、`Utterance`（生成的用户消息，子类型 `assert | restate | amend | withdraw | scope_shift | distractor`）、`Request`（探针，带 `context` 与 `touched_keys`）。

**边分两层，这个分层就是整个设计**：

- **导出边（零 LLM，`coords` 的纯函数）**：`CONTRADICTS`、`DUPLICATES`、`A_EXCEPTS_B` / `B_EXCEPTS_A`、`A_WIDENS_B` / `B_WIDENS_A`、`A_REDUNDANT` / `B_REDUNDANT`、`PARTIAL_CONFLICT`、`UNDECIDABLE`、`INDEPENDENT`。
- **构造边（生成计划的产物，构造性为真）**：`INTRODUCES` (u→c)、`RESTATES`、`AMENDS` (u: c_old→c_new)、`WITHDRAWS`、`SCOPE_KILLS`、`MERGES` (u: {c…}→c')。

意见被压缩到两处，各自可核：坐标（LLM，靠投票一致性 + 孤儿统计核）、话语的实现质量（靠盲读回核）。**没有任何一条边是「作者认为 A 压过 B」。**

```python
SCOPE_DIMS = ("app","task","nat_lang","code_lang","recipient","artifact")

def dim_rel(a, b):                       # None = 未指定 = 全集
    if a == b:    return "EQ"
    if a is None: return "B_SUB_A"
    if b is None: return "A_SUB_B"
    return "DISJOINT"

def scope_relate(sa, sb):
    r = [dim_rel(sa.get(d), sb.get(d)) for d in SCOPE_DIMS]
    if "DISJOINT" in r:                        return "DISJOINT"
    if all(x == "EQ" for x in r):              return "EQ"
    if all(x in ("EQ","A_SUB_B") for x in r):  return "A_SUB_B"
    if all(x in ("EQ","B_SUB_A") for x in r):  return "B_SUB_A"
    return "OVERLAP"

def stance_relate(a, b):                 # a,b = (polarity, value)
    va, vb = a.value, b.value
    if va.type != vb.type or "freeform" in (va.type, vb.type):
        return "UNDECIDABLE"
    eq = VALUE_EQ[va.type](va, vb)       # 单位不可换算 → None
    if eq is None: return "UNDECIDABLE"
    pos = lambda p: p in ("require","prefer")
    if eq:
        return "SAME" if pos(a.polarity) == pos(b.polarity) else "OPPOSED"
    if va.type == "set" and va.op == vb.op:
        A, B = set(va.items), set(vb.items)
        if A < B: return "B_WIDENS_A"
        if B < A: return "A_WIDENS_B"
        return "UNDECIDABLE"             # 部分重叠不给链式边
    return "DIFFERENT" if pos(a.polarity) and pos(b.polarity) else "UNDECIDABLE"

def relate(a, b):
    if a.key != b.key:  return "INDEPENDENT"
    s = scope_relate(a.scope, b.scope)
    if s == "DISJOINT": return "INDEPENDENT"
    v = stance_relate(a.stance, b.stance)
    if v == "UNDECIDABLE": return "UNDECIDABLE"
    if v == "SAME":
        return {"EQ":"DUPLICATES","A_SUB_B":"A_REDUNDANT",
                "B_SUB_A":"B_REDUNDANT","OVERLAP":"UNDECIDABLE"}[s]
    if v in ("DIFFERENT","OPPOSED"):
        return {"EQ":"CONTRADICTS","A_SUB_B":"A_EXCEPTS_B",
                "B_SUB_A":"B_EXCEPTS_A","OVERLAP":"PARTIAL_CONFLICT"}[s]
    return v                              # *_WIDENS_*
```

四类失效在图上的表示：

- **supersede 链**：`CONTRADICTS` 边 + `AMENDS` 构造边。三级链 A→B→C 就是两条相邻 `CONTRADICTS`；lint 断言链上任意两点的 `relate` 也是 `CONTRADICTS`（传递性检查，能抓出中间那条 key 打错）。
- **merge**：`DUPLICATES` / `*_REDUNDANT` 边 + `MERGES` 构造边。
- **revoke**：`WITHDRAWS` 构造边指向一个 **(key, scope) 区域**而不是一个 cid——真实用户说的是"以后不用管行宽了"，不是"退役 c-0417"。命中该区域的所有活条目一起死。这一条把 spec 里 L suite 卡在 0.50 的 retire/contradict 歧义变成了**结构差异**：有替代值 → CONTRADICTS，无替代值 → WITHDRAWS。
- **scope-death**：`scope_shift` utterance 声明某维度的某个值退场（"韩语本地化砍了"），`SCOPE_KILLS(u,c) iff c.scope[dim] == u.dead[dim]`。纯算术，不是判断。
- **revival**：新条目与一个已死条目 `DUPLICATES`。机械可测，按 spec 的口径两种产品行为都记为通过、分开统计。

---

## 3. 导出规则

### (a) 有效/活跃集

```python
def d_plan(plan, k):                     # 前向 fold，输入=构造边
    st = {c: ("not_yet", None) for c in plan.catalogue}
    for u in plan.utterances_upto(k):    # seq 序
        for e in u.edges:
            if   e.type == "INTRODUCES":  st[e.tgt] = ("active", u.seq)
            elif e.type == "RESTATES":    pass                    # 只加 strength
            elif e.type == "AMENDS":      st[e.old] = ("superseded", u.seq); \
                                          st[e.new] = ("active", u.seq)
            elif e.type == "WITHDRAWS":   st[e.tgt] = ("revoked", u.seq)
            elif e.type == "SCOPE_KILLS": st[e.tgt] = ("scope_dead", u.seq)
            elif e.type == "MERGES":
                for c in e.srcs: st[c] = ("merged", u.seq)
                st[e.new] = ("active", u.seq)
    return st
```

```python
def d_coords(catalogue, bindings, k):    # 类型化重放，输入=coords + (utterance→它陈述哪条)
    st  = {c: ("not_yet", None) for c in catalogue}
    live = []
    for u in bindings.upto(k):
        if u.kind == "scope_shift":
            for c in list(live):
                if any(c.scope.get(d) == v for d, v in u.dead.items()):
                    st[c] = ("scope_dead", u.seq); live.remove(c)
            continue
        if u.kind == "withdraw":
            for c in list(live):
                if c.key == u.key and \
                   scope_relate(c.scope, u.scope) in ("EQ","A_SUB_B"):
                    st[c] = ("revoked", u.seq); live.remove(c)
            continue
        cn = u.asserts
        for c in list(live):
            r = relate(cn, c)
            if   r == "PARTIAL_CONFLICT": raise BuildError(u.seq, cn, c)   # I3
            elif r == "CONTRADICTS":  st[c] = ("superseded", u.seq); live.remove(c)
            elif r in ("DUPLICATES","B_REDUNDANT"):
                                      st[c] = ("merged", u.seq);     live.remove(c)
        st[cn] = ("revived" if st[cn][0] in DEAD else "active", u.seq)
        live.append(cn)
    return st
```

`d_coords` 是关键：**"seq 12 杀死 c-line-79" 不是作者的声明，是 96 ≠ 80 在同一 key 同一 scope 下的算术后果。**

`d_text` 是第三条，只吃渲染后的 episode 文本前缀 + 打乱顺序的 catalogue 文本，输出封闭集选项（见 §4）。

### (b) activation

```python
MUST_FIRE_CAP = 12                        # 远低于 RECALL_CAP=32

def activation(state_k, req, catalogue):
    ctx  = req.context                    # {app,task,nat_lang,code_lang,...}
    live = [c for c in catalogue if state_k[c][0] in ("active","revived")]
    ok   = [c for c in live if scope_compatible(c.scope, ctx)]
    must_fire = [c for c in ok  if c.key in req.touched_keys]
    may_fire  = [c for c in ok  if c.key not in req.touched_keys]
    must_not  = ([c for c in catalogue                       # 死条目陷阱
                  if state_k[c][0] in DEAD and c.key in req.touched_keys]
               + [c for c in live                            # 活但越界陷阱
                  if not scope_compatible(c.scope, ctx)
                  and c.key in req.touched_keys])
    assert len(must_fire) <= MUST_FIRE_CAP
    return must_fire, may_fire, must_not
```

三处刻意的选择：

1. **gold 绝不复刻 `recall()` 的 cap 与排序策略。** 若 gold = `recall()` 会返回什么，bench 在读路径上永远不可能失败——那是同义反复。所以 `must_fire` 由「相关性」定义并硬性压在 12 以下，cap 变成**压力变量**而不是被打分的对象：episode 构造成 `|active ∧ scope-ok|` 越过 32 和 48，逼 recall 必须取舍，但正确答案始终装得下。测的是"cap 生效时丢对了没有"，不是"cap 的策略对不对"。
2. **`touched_keys` 是请求模板的生成输入，不是事后标注。** 请求由 `{task: release-note, touched: [doc.structure, doc.case, lex.*]}` 生成，所以相关性和别处一样：生成，不标注。
3. **`must_not_fire` 新增了「活但越界」一支。** spec 的 `must_not_carry` 只有死条目。一条**仍然有效但 scope 不匹配却被注入**的规则是真实的产品失败，spec 测不到。

---

## 4. 什么让它可核，而不只是被断言

### 4.1 三条独立导出，输入互不重叠

| | 输入 | 看不见什么 | 抓什么 |
|---|---|---|---|
| **D_plan** | 构造边（生成计划） | 文本、语义 | 无（构造性为真的基准） |
| **D_coords** | coords + (utterance→陈述了哪条) 绑定 | 计划里的**关系标签** | 「计划声称的 supersede 在数值上不成立」；「计划当成 independent 的两条其实是 DUPLICATES」 |
| **D_text** | 渲染后的文本前缀 + 打乱的 catalogue | 计划、coords | 「图对，但文本没这么说」 |

**D_coords 的独立性有一个必须守住的边界**：它可以知道"u-0412 陈述了 c-0417"（这一条机械可验——话语就是为陈述该条目而生成的，可用 distinctive token 串匹配回验），但**不能**知道"并且这压过 c-0301"。关系必须由 `relate()` 算。这个边界一旦破，就是拿一个数跟它自己比，整层验证归零——这是最容易被静默搞砸的地方，实现时要有单测钉死 `d_coords` 的输入结构里没有关系字段。

**D_text 的 prompt 形状**（沿用 2026-07-24 已落地的窄 context 结论）：一次一个 bucket、一次一个 checkpoint，给渲染文本 + 该 bucket 的条目文本（打乱、无 id、无顺序线索），答案是封闭集：

```
每条回答其一：not_yet_mentioned | in_force | superseded_by:<n>
             | withdrawn | merged_into:<n> | no_longer_applies_scope
```

**模型族必须与 judge 分开。** judge 是 deepseek-v4-pro，D_text 就不能也是 deepseek——否则 gold 和判分器共享同一套关于"什么叫压过"的偏见，两边一起错而没人发现。D_text 用另一族的 flash 档。成本可以忽略。

分歧模式即诊断：

| 模式 | 含义 | 去向 |
|---|---|---|
| 三者一致 | 接受 | 无人工 |
| `plan ≠ coords`，`coords == text` | coords 或计划的构造 bug | **自动修复队列，不消耗人工名额** |
| `plan == coords ≠ text` | 文本没有传达图所声称的意思 | **人工**（这正是双人签字原本要抓的类） |
| `plan == text ≠ coords` | coords 错 | 机械修复候选 |
| 三者互异 | 最高优先级 | **人工** |
| `relate()` 返回 `UNDECIDABLE` 但计划把它当 chain | 类型槽塞错 | 是 chain 才上人工，否则降级 independent |

### 4.2 机械不变量（零 LLM、零意见，进 CI）

`bench/graph/invariants.py`：

- **I1** 任何前缀上，`CONTRADICTS` 的两端不同时 active。（替代 spec 手写的 `conflicts_with`。）
- **I2** 每个 `superseded` 节点的后继与它同 key 且 `relate == CONTRADICTS`；三级链传递闭包成立。
- **I3** `PARTIAL_CONFLICT` 对不得同时存活——构建期直接拒绝。
- **I4** `DUPLICATES` 对必须在某个 seq 被 merge，或其中一条从未被引入。**这条抓的是一个 spec 结构上抓不到的坑**：产品在 `CONSOLIDATE_ACTIVE=48` 之上会自己合并近重复，语料里若有未声明的重复对，产品做对了反而被记成 state 错误。手写 `conflicts_with` 算不出这个，`relate()` 算得出。
- **I5** 单调性：每条 constraint 的状态是至多一次死亡的阶跃函数；复活只允许出现在声明的 revival 点。
- **I6** 每个 `must_not_fire` 陷阱与同 probe 内某个 `must_fire` 共享 key 前缀（spec lint 3，现在是导出的）。
- **I7** 孤儿检查：计划标 `chain` 但全 scenario 内没有任何非 `INDEPENDENT` 伙伴的条目 = key 分配错；反之计划标 `independent` 却有 `CONTRADICTS` 伙伴的 = 误 key 或真实的意外冲突。
- **I8** 可达性：每条 constraint 至少出现在一个 probe 的 `must_fire` 或 `must_not_fire` 里，否则它在 bench 里没有任何作用，拒绝入库。
- **I9** `role` 由图的度数导出（有实现过的非 `INDEPENDENT` 边 = chain），使 spec 的「chain ≥ 20 / filler ≤ 40%」配额变成不可粉饰的机械量。

### 4.3 检验器本身的负对照——这一条替代双人签字的**保证**部分

不可能证明 672 条每条都对。能证明的是**检测器抓得住种下的错**，并把残余错误率报出来。

- **变异 canary**：往标注批里注入 40 条人为损坏（换 value、放宽 scope、翻 polarity、替换 key、把 withdraw 写成 amend），每类 8 条。交叉检验必须命中 ≥ 0.90。**命中率不达标就不发布分数**——那说明这一层什么都没在报告。
- **残余错误率估计**：canary 测得灵敏度 s，真实语料上的 flag 率 f，估计真实错误率 ≈ f/s，逐失效原因分层报，**与 E 的分数并排公布**。这是取代"我们全看过了"的那个数字。
- **打乱对照**：把 coords 在 constraint 之间随机置换，分歧率必须暴涨。不涨说明 `d_coords` 没在做功。
- 数值一律 **regex 优先**：从 L0 原子里正则抽数，LLM 只在正则空手时才被问；LLM 报的数与正则不符 → 直接 flag，不采信 LLM。
- **类型槽必须过序列化回环**：`{numeric,96,col,max}` 渲染成 "at most 96 columns"，机械比对回 L0 原子；对不上就降级 `freeform`。这一条杀掉绝大部分捏造。

诚实地说清能力边界：本设计给的是 **(i)** 图在机械不变量下自洽、**(ii)** 一个灵敏度已测的检测器、**(iii)** 一个公布出来的残余错误率估计。这严格弱于 100% 人工复核，严格强于"LLM 标了"。owner 需要接受的就是这一句。

### 4.4 廉价 LLM 错了会怎样

| 错误 | 对图的影响 | 谁抓到 | 怎么活下来 |
|---|---|---|---|
| key 错（劈开了真冲突） | supersede 边丢失，条目永不死 | I7 + `plan ≠ coords` | 桶内聚类重 key；**要紧的是"这一对"，不是绝对 key 名** |
| key 错（并了两条不同规则） | 伪 CONTRADICTS，gold 杀掉活规则 | I1 构建期就炸 + D_text 反对 | flag |
| value 数值读错 | supersede 方向反了 | regex 优先，根本不问 LLM | 机械 |
| scope 太窄 | 条目永不激活，probe 不可打分 | I8 可达性 | 机械拒绝 |
| scope 太宽 | 过度激活，gold 要求带无关规则 | D_text 读回 | flag |
| bucket 错 | 对关系无影响（关系只看 key+scope+stance），但 per-bucket 子分错 | 投票不一致 | 报 bucket 级一致率；一致率不达标的桶**不出子分** |
| freeform 误判成 typed | 凭空的关系 | §4.3 序列化回环 | 降级 freeform |

投票必须来自**表示差异**，不是温度：DeepSeek 在 temperature 0 上重复三次给同一答案，那种"自洽"是零信息。用 2 个廉价模型 × 2 种呈现（单条独立标 / 放在同 bucket 兄弟条目中标），共 4 票。

---

## 5. 怎么排那 10 个

**中心押注：owner 的标注是一条规则，不是一个条目的标签。** 10 个标签只有传播到簇上才够 672 条用。

```python
def voi(f):
    return (f.cluster_size          # 该决策能传播到多少条
            * blast(f.cid)          # 依赖这条真值的断言数：
                                    #   Σ_cp [state 断言] + Σ_probe [must_fire/must_not 断言]
                                    #   早死的条目 blast ≈ 20，末尾的 ≈ 1
            * p_wrong(f)            # canary 标定的分歧类→错误率查表 × coords 投票熵
            * W[f.cls])             # TEXT_DISSENT 1.0 / THREE_WAY 1.0
                                    # PLAN_VS_COORDS 0.1（机械可修，不该烧人工）
                                    # COORDS_VS_TEXT 0.3
```

选择：按 `voi` 降序贪心，`cluster_key = (bucket, key_family, disagreement_class, value_type)` 每簇至多取 1，取满 10。理由：3 个标签花在同一个近重复簇上买不到 3 份信息。

**owner 看到的是决策卡，不是条目**：

```
[卡 3/10]  影响 43 条 · 12 个 checkpoint · 89 条断言
用户说：  "行宽那条以后不用管了"
读法 A（supersede）：存在替代值，退旧立新       ← 计划与 coords 的读法
读法 B（revoke）：    无替代值，纯撤回           ← D_text 的读法
选 B 会改变：43 条同型话语的 op，L suite 的 revoke 类别口径随之统一
```

答案落成一条规则（"以后 X 就不用了 且未陈述替代值 → revoke"），传播到全簇，重跑。

三条护栏：

- **传播回验**：传播后对该簇重跑 D_text；若传播标签与 D_text 在簇内 >20% 不合，说明簇是假的——回滚，整簇打进 `E-amb` band，**不再花第二个名额**。
- **10 个名额的分配建议**：**6 个前置 + 4 个留作升级**，而不是二选一。事后花掉的 10 个修不了一个系统性跑偏的检测器；前置花掉的 10 个覆盖不了没预料到的类别。若必须二选一 → **全部前置**，因为标偏的检测器会浪费掉全部 672 条。前置那 6 个不随机取，取在三条已知的决策边界上：retire vs contradict（2）、widen vs new（2）、merge vs independent（2）。
- **预注册的停止规则**：owner 与流水线在这 10 个上的一致率 < 8/10 → 流水线未标定，**E 不进 gate**，不发布分数。

---

## 6. 落地顺序与成本

| 里程碑 | 产出 | 验收 |
|---|---|---|
| G0 | `bench/graph/{schema,relate,derive,invariants}.py`，零 LLM 零语料 | `relate()` 的 property test；`d_plan` 与 `Store.apply_ops` 的 10k fuzz 等价（spec N0，保留）；`scope_compatible` 与 `recall._scope_ok` 的投影等价测试 |
| G1 | `bench/gen/annotate.py`（4 票）+ 40 条 canary | canary 检出率 ≥ 0.90；否则停 |
| G2 | 1 个 scenario 的 L1→L3 全链，`d_text` 接上 | 三路一致率落盘；歧义率落在目标带内（见风险 3） |
| G3 | owner 6 个前置标签 → 规则 → 传播 → 重跑 | 一致率 ≥ 8/10 才继续 |
| G4 | 672 条全量 + 4 个升级名额 | 残余错误率 f/s 与 E 分数并排 |

**成本与并行**（owner 第 4 点）：标注 672 × 4 票 ≈ 2,688 次调用（~1k in / 300 out）；D_text 12 scenario × 8 cp × 6 bucket ≈ 576 次（~2k in）。合计 ~3,300 次、< $10。复用 `bench/runner/parallel.py::run_items`——它已经带 checkpoint，这在一次 2,700 调用的 pass 上是刚需，中断不用重跑。`DEFAULT_WORKERS = 4` 是按 judge 通道 429 的历史定的；标注是另一种调用形状，起 8–10，重试梯 5/15/45/120s 不动。annotation 走 `.env` 里的 DeepSeek 通道（`bench/runner/config.py` 已经读），不碰 `ANTHROPIC_API_KEY`。

## 7. 相对 spec 的明确改动

- P7 双人签字、lint 规则 9 删除，替换为 §4.1 三路交叉 + §4.3 canary 灵敏度 + 公布的残余错误率。
- `conflicts_with` 字段删除（由 `relate()` 导出）；`role` 字段改为导出（I9）；`effect.op` 从作者声明降级为**生成计划的构造边**。
- `must_carry` / `must_not_carry` 改名 `must_fire` / `must_not_fire` 并新增「活但越界」陷阱一支。
- 新增 `MUST_FIRE_CAP = 12`，把 `RECALL_CAP` 从被打分对象改回压力变量。
- 「Suite R」全部改称 Suite E；分数需按 bucket × 失效原因出矩阵（作为可营销数字的可分解形式），headline 仍用 scenario 聚类 bootstrap CI。

### 自报风险

- **[high]** D_coords 与 D_text 都是廉价 LLM，可能共享同一套关于「什么叫压过 / 什么叫撤回」的偏见，两条导出一起错且互相印证——这会把一个错误的 gold 洗成「三路一致」，是本设计最致命的失败模式
  - 缓解：三条硬隔离：(1) D_coords 根本不问 LLM 关系，只做 coords 上的算术，LLM 只填坐标；(2) D_text 必须与 judge（deepseek-v4-pro）不同模型族，且输入表示完全不同（D_coords 看结构不看顺序，D_text 看散文不看结构）；(3) 数值 regex 优先、enum 封闭集、类型槽过序列化回环，把机械可判的部分从 LLM 手里全部拿走。残余风险靠 canary 灵敏度量化并公布，不声称消除
- **[high]** 「生成而非标注」买到了可核性，代价是生成的用户话语比真实用户干净——语料太好判，E 分数虚高，而这正是 owner 要拿来对外说「可以用了」的那个数
  - 缓解：不把歧义率最小化，而是设**目标带**：真实用户在 retire/contradict 之间本就模糊（L suite 的 revoke 今天 0.50 就是测量证据）。amend/withdraw 类话语的 D_text 分歧率若低于 8%，判定语料过净、退回重写；目标带 8–15%，每次 run 公布实测值。话语的表层措辞从 PRISM open_feedback（CC BY 4.0，许可干净）取真实用户语句改写，不让模型自由发挥
- **[high]** owner 的 1 个标签传播到 40+ 条的簇上，若簇不成立就是用一个决定污染几百条，比不标还糟
  - 缓解：传播后对全簇重跑 D_text；不合率 > 20% 即判定簇为假，回滚并把整簇打进 E-amb band，不追加名额。簇键必须四维全同 (bucket, key_family, disagreement_class, value_type)，宁可簇小也不放宽
- **[high]** `relate()` 与 `scope_relate()` 事实上重新实现了一份产品也必须做对的语义；两个状态机一旦漂移，suite 里每个数字都错而任何 judge 都发现不了
  - 缓解：沿用 spec N0 的 fuzz 等价测试并扩两条：d_plan ↔ Store.apply_ops（10k 随机 op 流）、scope_compatible 投影 ↔ recall._scope_ok（穷举六维封闭词表的笛卡尔积，规模够小可以全跑）。两条测试进 CI，不是可选项
- **[medium]** 产品 `scope` 只有 {app, task, lang}，且 lang 一个字段同时被自然语言与编程语言重载；bench 的六维 scope 投影下去必然失真，recipient / artifact 两维产品根本表达不了
  - 缓解：投影规则写死并记为已知失真：code_lang 非空取 code_lang，否则取 nat_lang。recipient / artifact 标 bench_only，只参与 BEHAVIOUR 断言（改写里带没带），绝不参与 STATE 断言（产品记录的 scope 对不对）。lang 重载本身作为产品 issue 单独提，不在 bench 里绕
- **[medium]** canary 只能测「检测器抓不抓得住我想得到的错」；LLM 真实犯的错可能是我没想到的那类，灵敏度 0.90 会被误读成「90% 的错都被抓住了」
  - 缓解：canary 分五类各 8 条并**逐类报灵敏度**，不报总数；残余错误率 f/s 明写为「对已建模错误类的估计」。前置 6 个人工标签里留 2 个给 D_text 报告的、canary 类别覆盖不到的分歧模式，作为「未建模错误」的抽样窗口
- **[medium]** 新 E 与旧 E（0.667）量纲不同，但 gate 公式 0.4T+0.3L+0.3E 与 GATE_PER_SUITE=0.70 是按旧 E 语义定的；直接沿用会读出一个没有意义的通过/不通过
  - 缓解：新 E 前两次全量跑不设 gate，只出水位与 scenario 聚类 CI，与 spec 对 R 的处理一致。8 个 legacy persona 作为 E 内一个子集保留并单独出 E-legacy 数，提供唯一一条与 0.667 可比的线
- **[medium]** 生成 utterance 的模型若与 SUT translator 同族（claude-haiku-4-5），SUT 可能对这批文本异常擅长，分数不可外推
  - 缓解：用 DeepSeek 生成、Claude 上测；并在 1 个 scenario 上跑交叉族对照（同一批边用另一族模型重新生成话语），把两者的 E 分差如实报出，差值 > 0.05 即说明存在生成族耦合
- **[medium]** key 注册表封闭是关系检测成立的前提，但 ~90 个 key 在 672 条真实语料上可能覆盖不足，逼着 LLM 硬塞，制造伪冲突或伪独立
  - 缓解：注册表在 G2（首个 scenario）后按孤儿率回填一轮：I7 报出的孤儿若集中在某个语义区，是缺 key 不是标错。回填只在 G2/G3 两个窗口允许，G4 全量开始后冻结，避免边标边改词表导致前后不可比
- **[low]** freeform 逃生口用得太多会把 chain 配额掏空——spec 要求每 scenario chain ≥ 20，若一半条目落进 freeform 就凑不出来，诱使实现者放松类型判定
  - 缓解：把 freeform 比例做成构建期的硬指标而不是软目标：freeform > 35% 即判定类型槽设计不足，回去加 value type 或 enum domain，禁止靠放松序列化回环来达标。首个 scenario 就测这个比例，早失败便宜

### 未决问题

- 那 10 个名额按 6 前置 + 4 升级分，还是全部前置？我倾向 6+4，但若 owner 只想看一次，全部前置更安全——事后名额修不了一个系统性跑偏的检测器。
- 产品的 `scope.lang` 重载（自然语言 vs 编程语言，`{"lang":"python"}` 与 `same_language` checker 共用一个字段）：修产品 schema 拆成两维，还是 bench 侧投影并接受失真？spec §9 明说「不因 bench 而改产品 schema」，但这一条看起来是产品自身的缺陷而不是 bench 的需求。
- `recipient` / `artifact` 两个 scope 维度：进产品 schema，还是永久 bench-only 只做 BEHAVIOUR 断言？影响到 communication_style 桶能不能出 STATE 子分。
- 新 E 是否保留 8 个 legacy persona 作为子集以维持与 0.667 的可比性，还是彻底重置、承认这是一个新测量？
- revival（撤回 20 个 event 后重述同一规则）：owner 现在要不要给产品定一个立场（新建 vs 翻活墓碑）？定了 bench 就能打分，不定就只能两种都记通过、分开统计。
- 歧义率的目标带（我提的 8–15%）该从 L suite 的 revoke 实测（0.50）推导，还是独立设定？前者更有依据但 0.50 是单类别小样本。
- D_text 用哪一族模型？只要求「非 deepseek」，具体选 Claude flash 档还是 Qwen，取决于 owner 手上哪条通道最稳——本机 Anthropic 代理一天抖 5 次以上，3,300 次调用会撞上。
- chain 配额 ≥ 20 是按 spec 的手写 role 定的；改成由图度数导出后，实际可达数量要等 G2 才知道。若首个 scenario 只导出 14 条 chain，是补语料还是下调配额并记录？

---

## 设计 2：Episode Construction: 从 licence-clean 原子 constraint 到 translator 真正消费的 user history

## 0. 先回答「它们在什么 level」——盘点结果比 spec 说的更低

我在盘上逐个查过（`bench/`、`docs/`、`data/` 全树），结论：

| level | 定义 | 现况 |
|---|---|---|
| L0 | 许可裁定表 + 预算 | ✅ 有。`docs/2026-07-26-bench-scaleup-spec.md` §1（~770 条预算）+ `docs/2026-07-26-thin-bucket-sourcing.md` §1（两个薄桶的源表） |
| L1 | 原子 constraint 语句已落盘 | ❌ **没有**。thin-bucket 文档声称「已提取 189 条」，但全树 `grep -rl "openssf\|scope_hint\|checkable"` 只命中那份 md 自己；`bench/gen/harvest/` 目录不存在。盘上真实存在的原子句是该文档 §3.1 的 12 条好例 + §3.2 的 5 条坏例，**共 17 句，在一个 markdown 表格里** |
| L2 | catalogue 条目（key/scope/bucket/salience/判据） | ❌ 0 |
| L3 | utterance（真人会说的那句话） | ❌ 0 |
| L4 | episode（穿插进工作请求的有序历史） | ❌ 0 |

所以 owner 的判断成立且比他想的更严重：不只是「只有原子信息、需要建 episode」，而是**连原子信息本身都还没落盘**。以下设计因此把 L1→L4 当成一条流水线一起设计，而不是假设 L1 已经在手。

一个直接后果：既然 L1 还没写，就没有「已有语料的措辞要不要保」的沉没成本——可以从第一步就把 clean-room 边界画在正确的位置（§1.1）。

---

## 1. 原子 constraint → 一句真人会说的话

### 1.1 核心机制：generator 永远看不到源句

流程是两跳，中间隔一道硬墙：

```
源句（第三方文本，licence 受约束）
   │  hop-1  SKELETONISE（cheap LLM，DeepSeek，temp 0）
   ▼
skeleton（结构化命题，无表达）           ← 唯一跨墙的东西
   │  hop-2  UTTER（cheap LLM + persona card + incident hook）
   ▼
utterance（进 repo 的那句话）
```

skeleton 的形状（这是整套设计的承重件）：

```json
{
  "trigger":   "when I ask you to write a postmortem",
  "act":       "start",                       // require|forbid 的动词
  "object":    "the timeline",                // 具名对象
  "against":   "background recap",            // 被排除/对照的对象
  "threshold": {"kind": "count", "value": 96, "unit": "columns"} | null,
  "order":     ["verdict", "evidence"] | null,
  "polarity":  "require|prefer|avoid|prohibit",
  "subject":   "you"                          // 只能是 me / you
}
```

为什么这道墙同时解决三个问题：

1. **licence**。版权保护表达不保护命题。skeleton 是事实与思想，utterance 是我们自己的表达，generator 物理上没见过源句所以抄不了。发布件里**一个字的第三方原文都不进 repo**——`provenance` 只带 `{source_id, url, licence, use: "skeleton-derived"}`，源文本留在 build 机的 `bench/gen/harvest/`（gitignore）。这把 spec lint 第 7 条那张 `use: verbatim` 白名单几乎整个废掉，也顺带把 thin-bucket §5.3 的 copyleft 问题（Wikipedia 占已提取的 23%）从「要不要单独分片发 BY-SA」降级成一条 provenance 注记。**这条需要 owner 签字，不是我能替他认定的法律结论**（列进 open questions）。
2. **反 backbone 记忆**。变异发生在 skeleton 的字段上，不在句子上：`threshold.value: 79 → 96`。因为变异先于生成，生成出来的句子天然带变异值，不存在「改了数但句子还是原句」的残留。
3. **GRADED 性质不丢**。判据不是人写的，是**从 skeleton 推导的**：

| skeleton 字段 | 自动生成的判据 |
|---|---|
| `threshold.value = 96` | `contains_all:["96"]` + `not_contains:["79","80"]`（同族源值全部入负表） |
| `object` / `against` | `regex_present(object 的同义扩展)` / `regex_absent(against)` |
| `order = [A,B]` | `first_index(A) < first_index(B)`（新增 checker，纯词法） |
| `polarity = prohibit` + `object` | `not_contains(object)` |
| 四者皆无 | **丢弃该原子**（这就是 thin-bucket §5.2 的 G1 抓手闸，从人工过滤器升级成自动准入） |

`distinctive`（反 overfit 锚）= 变异后的 token 或自造对象名，也是自动的。这意味着 spec P5「逐条人工写判据」这一步整个消失，而它原本是 672 条里最贵的人时项。

变异策略按 skeleton 类型分派（全自动）：
- 数值：换成非圆整、非源值的两位数（避开 80/100/120/4/2 这类 backbone 熟值）。
- 具名对象：换成同族但不同表面词的对象；换不动就 `polarity` 取反。
- 顺序：交换 A/B，前提是两个顺序都说得通（LLM 一次二元判断）。
- 都变不动且命题是 backbone 默认行为（G2 反事实闸写不出「违反了它但任务仍完成」的输出）→ 丢。

### 1.2 声音来自 persona，不来自源

hop-2 的输入是三样东西，源句不在其中：

- **skeleton**（命题）
- **persona card**：身份、语言（zh / en / 混）、语域（话痨/极简）、输入习惯（语音输入错别字、全小写、不加句号）、领域词汇，以及 `grievance_style`——真人的规则几乎都是被某次糟糕经历打出来的，thin-bucket §3.2 结尾已经把这条总结成「五条不像真人的句子的共同信号」。
- **incident hook**：这一轮之前那条工作请求的文本。规则要挂在刚发生的事情上。

### 1.3 三种表面，配额强制

| surface | 样子 | 配额 |
|---|---|---|
| `complaint` | 对上一轮产出的抱怨里长出规则：「这个又给我从头解释了一遍，postmortem 直接从时间线开始就行」 | 40% |
| `aside` | 夹在正常工作请求中间，顺口一提：「顺手写个脚本，注释还是英文啊」 | 35% |
| `standing_order` | 明确的「以后都…」 | **≤25%（硬顶）** |

`standing_order` 必须限额，理由是可测量的：产品的 `signals.py::_RULE_PAT` 正则里就写着 `以后|一律|从现在起|from now on|always`。一个 100% 由 standing order 组成的 suite 测的是那条正则，不是系统。今天的 8 个 persona 文件的 `natural_correction` 字段**全部**是 standing/complaint 明述式，这是 E 是玩具的原因之一。

### 1.4 四道自动验收，替代人工过目

| 闸 | 做法 | 成本 |
|---|---|---|
| **回读闸**（最重要） | 用同一个 cheap LLM **盲**地从生成的 utterance 反推 skeleton（它看不到原 skeleton），逐字段比对。`threshold` / `object` / `polarity` 必须精确相等，`trigger` 必须映到同一个 scope tag。不一致 → 重生成一次 → 再不一致就丢 | 1 次 LLM |
| **licence 闸** | 生成句 vs 源句：内容词 5-gram 交集必须为空；LCS ≤ 12 字符（en）/ 6 字符（zh），具名对象与数字除外 | 0 token |
| **风格闸** | self-instruct 175 条种子（Apache-2.0，thin-bucket §2.3.5 已裁可用）做 few-shot 锚，「像不像真人随口说的」1–5 分，<4 退回重写，两次不过就丢 | 1 次 LLM |
| **污染闸** | `distinctive` 哈希后 grep `src/`；反向查产品 prompt 固定短语不得出现在 case 里。接进已有的 `tests/test_no_bench_contamination.py` | 0 token |

回读闸是「人读一遍确认这句话还是那条规则」的机械替身。它能成立的原因是 skeleton 是结构化的——比对的是字段相等，不是语义相似度。

---

## 2. Episode 结构

### 2.1 规模

| 量 | 值 | 与 spec 的差 |
|---|---|---|
| episode 数 | **12** | 同（CI 聚类分析照旧：SD 0.10 → ±0.057；12→20 只收到 ±0.044，不值） |
| gold 节点 / episode | **60** = 51 primary + 9 successor | spec 是 56 |
| 需要采购的原子 | **12 × 51 = 612** | spec 是 672；successor 是前驱的变异体，不消耗语料 |
| 轮次 / episode | **86** | spec 是 112 event |
| 总轮次 | 1,032 | 今天：128 |
| 终态 | 41 active / 19 invalidated | |

612 条对 ~770 的采购预算留 ~25% 过闸损耗，和 thin-bucket §2.4 估的 1.4× 余量对得上。

一条反直觉的建议：thin-bucket §2.1 建议把语料内的同义重复去掉（「commit to a pick」/「comparison 必须选一个」/「commit to one」三条同义）。**不要全去。** 这些天然近重复正是 merge 的免费素材，去掉了就得人工造。保留成对/成组，标 `duplicate_of` 边。

### 2.2 密度日程——必须真的越过两条阈值

| cp | 到第几轮 | 累计引入 | 累计失效 | active | 意图 |
|---|---|---|---|---|---|
| cp-00 | 6 | 6 | 0 | 6 | 与今天 E 的 3 规则区间可比，做 harness 正确性回归 |
| cp-01 | 14 | 15 | 1 | 14 | 远低于 cap |
| cp-02 | 26 | 28 | 3 | 25 | |
| cp-03 | 36 | 36 | 4 | **32** | 恰好等于 `RECALL_CAP` |
| cp-04 | 46 | 45 | 5 | 40 | cap 开始咬 |
| cp-05 | 58 | 54 | 7 | 47 | 贴着 `CONSOLIDATE_ACTIVE` 下沿 |
| cp-06 | 66 | 60 | 8 | **52** | 越过 48，consolidation 首次在密集 store 上触发 |
| cp-07 | 76 | 60 | 14 | 46 | contradict + merge 密集簇 |
| cp-08 | 86 | 60 | 19 | 41 | 终态 |

**scope 过滤会偷走密度，spec 没算这一笔。** `recall()` 的 cap 作用在 `_scope_ok` **过滤之后**的池上。若 52 条 active 里一半被 scope 挡掉，`RECALL_CAP=32` 根本不会触发。处置不是提高 global 比例（那样 scope 就不测了），而是**故意让 probe 的 context 精度不同**——`_scope_ok` 在 context 不知道某维度时保留条目：

| probe 类型 | context | 兼容池（peak 52 时） | 测什么 |
|---|---|---|---|
| `narrow` | `{app, task, lang}` 全给 | ~34 | `_scope_ok`：`must_not_carry` 放同族但 scope 是兄弟 task 的条目 |
| `wide` | 只给 `{app}` 或空 | ~46 | `RECALL_CAP`：14 条被 cap 淘汰，测选择逻辑 |

节点 scope 分布：55% global `{}`，30% 单维 `{task:…}`（散在 4 个 task 上），15% 双维。每 episode 定义 3 app × 4 task × 1–2 lang。

顺带指出今天 E 完全没测 scope：`run_e2e.py:86` 是 `_polish(rd["task"], [...])`，第三个参数 `context` 根本没传。

**关于 cap 的一条纪律**：`recall()` 是确定性的 15 行代码，老条目只有 `key` 词法命中 query 才能从 recency 尾巴里活下来。所以 `must_carry` **不允许**包含会被模拟 recall 淘汰的条目，否则断言不可满足（就是 spec §4.5 说的 `oracle-ceiling < 0.9 = case 文件有 bug`）。lint 直接调用产品的 `recall()` 模拟一遍来推导。被 cap 淘汰的 gold-active 条目单独出一个 `recall-loss` 诊断数，**只报不判**——cap 是产品决策，bench 的活是量化它的代价。

### 2.3 轮次构成

86 轮：

| 类型 | 数量 | 是什么 |
|---|---|---|
| `R` plain request | 32 | 纯工作请求，无规则内容。进 translate，是 probe |
| `C` carrier | 26 | **工作请求里夹着规则**。同一个字符串既进 translate 也进写路径。是 probe（见 §5） |
| `S` standalone | 9 | 只有规则、没有任务的裸消息 |
| `D` edited_diff | 11 | 用户改了我们的改写（见 §3） |
| `N` distractor | 8 | 必须产生零 op |

46 个带信号的轮（C+S+D）承载 68 个 effect：51 primary 引入 + 7 contradict + 6 retire + 1 scope_dead + 3 reinforce。平均 1.5 effect/轮——复合话语正是 extraction prompt 4a「ATOMISE」要测的东西。

**merge 不是用户事件。** merge 是 consolidation 路径的产物，由密度触发，不由用户话语触发。所以 gold 里 merge 的断言写成**按 checkpoint 而非按轮次**：「cp-06 及之后，`{cid-a, cid-b}` 至多一条 active，且幸存者覆盖两个命题」。近重复在日志里相隔 15–25 轮埋入。

**harness 必须自己驱动 consolidation。** 产品的 `Pipeline.maybe_flush` 不调 consolidation，`should_consolidate()` 只是个 helper。bench 要在每次 extraction flush 之后按 daemon 的方式调一次 `should_consolidate` + `run_consolidation`，并分开记录是哪个触发器命中（`CONSOLIDATE_ADDS=16` 会在稀疏 store 上频繁触发，`CONSOLIDATE_ACTIVE=48` 只在 cp-06 附近触发一次，两者难度完全不同）。今天两者都没被跑过。

### 2.4 8 个 distractor，每 episode 至少各一

1. content preference（口味/事实）——PRISM 里 ~64% 的价值/安全表述天然是这个（spec §1 已裁）
2. one-off（「这次写详细点，季度 review 要用」）
3. task step（任务的一个步骤，不是交付规则）
4. **粘贴材料里含规则形状的文本**——把一条 licence 干净的 style-guide 原文当作「用户粘进来的材料」贴进去。测 `signals.py::_material_mask` 的材料/discourse 切分。今天全 suite 无此项，而这是真实使用中最高频的假阳来源
5. 第三方义务（「我老板要求他们组周报用 bullet」）——G4 主语闸的反面
6. agent 说过的话被引用回来
7. **带 `_RULE_PAT` 词汇但无规则的抱怨**（「又来了，这 API 每次都超时」）。`又来了` 就在那条正则里。一个从不误触正则的 suite 没在测 precision
8. 已知规则的同义复述但明确标为一次性

外加一条结构性要求：**必须存在至少一个连续 8 轮的窗口全是 distractor + plain request**，用来验证 `signals.py` 自述的「whole-batch-silent → 0-call」性质——整批静默时应该一次 LLM 都不调。

---

## 3. edited_diff 三元组：不写一个 final 字符串

关键认识：`polished` 不是作者写的，是 **SUT 当场产出的**。所以 episode 文件里**不能存 `final`**（今天的 persona 文件存了，那是把 SUT 的输出当成了常量）。存的是 `diff_plan`。

```json
{"round": 41, "type": "D",
 "raw": "<该轮的用户请求文本>",
 "diff_plan": {"move": "tighten", "cid": "e07-c31", "arg": "72"}}
```

运行时：`polished = translate(raw, recalled, context)["polished"]`（no-op 时回落到 `raw` 并标 `diff_degenerate`，单独计数不静默计分），然后一个纯字符串编辑器按 move 造出 `final`：

| move | 怎么造 `final` | gold 期望 | 占比 |
|---|---|---|---|
| `add_constraint(cid)` | 把该 cid 的 `clause`（utterance generator 顺带产出的短句形式）追加到 `polished` 末尾 | `new(cid)`。`attribute_diff` 的 `user_added` 恰好等于 clause，正对 extraction 规则 3「op 只能来自 final 相对 polished 新增的文本」 | 35% |
| `revert_injection(cid)` | 用 `_spans(raw, polished, ("insert","replace"), side="b")` 定位注入片段，删掉含该 cid `distinctive` 的那一段 | **零 op**（产品明确把删掉的注入当一次性信号），但 `strength_delta = -1` | 25% |
| `tighten(cid)` | 把注入片段里的参数值换掉（96 → 72） | `contradict(cid)`，后继节点的 `distinctive` 就是新数字，判据自动生成 | 25% |
| `reword(cid)` | 把注入 clause 换成同义的 `alt_clause` | `style_rule` op | 15% |

四个 move 全是纯字符串操作，零 LLM 零人工，而且**与 gold effect 天然一致——因为是 gold effect 选择了 move，不是人事后标注一个 diff 的意图**。spec 里最贵、最不可靠的那类标注（「这次编辑到底是 retire 还是 contradict」）整个消失。

诚实的代价，明说：这让 diff 通道比现实容易。真实用户的编辑更脏、意图本就模糊——L 的 `revoke` 卡在 0.50 就是证据。两条缓解：
- `messy` 变体：`add_constraint` 用一个**同时隐含推翻某条已存规则**的 clause，gold 的 `accept` 集合写 `{new, contradict}`，进单独的 `E-amb` band，不进 headline。owner「不删歧义 case」的立场保住了，但歧义现在是**构造并标注出来的**，不是靠两个标注员发现的——这正是 ≤10 人工上限能成立的那笔交换。
- `reword` 那一档现在**无法计分**：`bench/runner/providers.py:107` 的 `V1Provider.extract` 显式 `if o.get("rkind") == "style_rule": continue`，把 style_rule 从 bench 契约里滤掉了。要么放宽契约，要么这一档只做 report-only。列进 open questions。

---

## 4. episode 判什么，以及怎么映到今天的 rounds / applicable / second-half

### 4.1 四个数，两个进 gate

| 指标 | 定义 | 对应今天的什么 |
|---|---|---|
| **CARRY** | 每个 probe：命中的 `must_carry` / \|must_carry\|，partial credit | 就是今天的 `carried / applicable`，`applicable` 换成推导出来的 `must_carry` |
| **SUPPRESS** | 1 − (命中的 `must_not_carry` / \|must_not_carry\|) | 今天完全没有。~90% 机械可判（前驱的 `distinctive` 不出现 = `not_contains`），几乎零 LLM 成本 |
| **STATE** | 对齐后 active 集的 F1、zombie_rate、chain_fidelity | 今天没有 |
| **QUIET** | distractor 轮产生零 op 的比例 | 今天没有 |

`episode_score = 0.6·CARRY + 0.4·SUPPRESS`，在 probe 上取均值。

QUIET 是**否决项而非加权项**：QUIET < 0.8 的 episode 照报 CARRY 但不进 gate。理由很直白——一个什么都往里存的系统能白拿 CARRY。

STATE 是否进 gate 我不替你定（open question）。倾向进：owner 的框架是「完整记录 + 精确检索」，「完整记录」就是 STATE。但对齐层（spec §4.1）是整套里最脆的一环，且需要 40 对对抗对照集，成本不小。

### 4.2 second-half 怎么推广

今天 `E2E_SECOND_HALF_FROM = 9`（16 轮的后半）是「教完了再考」。86 轮下单一切点是错的：第 70 轮才引入的规则没有「后半程」。

正确的推广是**按 constraint 的成熟度，不按 episode 的位置**：

```
一个 gold 节点在某个 probe 上进入计分集，当且仅当：
  gold_active(node, prefix)                    # 构造性为真，零标注
∧ scope_ok(node.scope, probe.context)          # 调产品自己的函数
∧ survives(simulated_recall(prefix, probe))    # 调产品自己的 recall()
∧ applies_to(node, request)                    # 唯一的判断层，见 §6
∧ flushes_since_intro(node) ≥ 1                # 成熟度谓词
```

`flushes_since_intro ≥ 1` 是精确的（harness 知道自己何时 flush 的），不依赖估算。case 编写期另给一条 `MATURITY_GAP = 10` 轮的编排指引，让 lint 能在不跑 SUT 的情况下预检 probe 位置合法。

这样 `E2E_SECOND_HALF_FROM` 从一个魔数变成一个导出量，同时保住原意：不考没教过的东西。

### 4.3 与今天数字的可比性

cp-00（第 6 轮，~6 条 active）单独出一个 `E-legacy-band`。它的分数应该与今天 E 的 0.667 在噪声内一致。差得多说明 harness 或生成器错了，不是产品错了——这是 spec N1 的验收标准，保留。

### 4.4 并行

episode 之间独立、episode 内部严格有序 → 沿用 `bench/runner/parallel.py::run_items`，`workers=10`，`--repeat 2` = 24 个工作单元。单 episode 单趟约 106 次 SUT 串行调用（86 translate + ~15 extraction flush + ~5 consolidation），中位 3s → ~5.3 分钟；两波 + judge ≈ 25–40 分钟墙钟。单趟断言量 ≈ 12 × 58 probe × 5.2 = **~3,600**（今天：222）。

一个必须补的口子：`parallel.py` 的 `Checkpoint` 按 `item.id` 记录，粒度是整个 episode。86 轮的 episode 在第 70 轮挂掉会丢全部 70 轮。episode 长度是今天 persona 的 5 倍，需要**轮级 checkpoint**（append 每轮的 translate 输出与 store 快照）。

---

## 5. 「把这些原子信息融入 user history message 里，输入给我们的 translator」——具体是什么

这句话对应设计里的 `C`（carrier）轮，占 26/86。它是这套设计与今天 Suite E 最本质的差别。

今天的 persona 文件把一轮拆成两个字段：

```json
{"task": "写个 python 函数，把嵌套 dict 拍平成点分隔的 key",
 "natural_correction": "说过了，代码直接给，别解释"}
```

`task` 进 `translate()`，`natural_correction` 只在失败时进 `pending` 喂给 extraction（`run_e2e.py:97-102`）。两者**从不是同一个字符串**。真实使用里最高频的形态恰恰是它们是同一个字符串。

carrier 轮的样子（episode e-07，第 41 轮）：

```
用户消息（一个字符串，就是 composer 里的全部内容）：

  帮我把这个 flaky test 的 root cause 写成给组里的 postmortem，
  上次那份你又从头解释了一遍背景，postmortem 直接从时间线开始就行
```

这一个字符串在同一轮里被消费两次，顺序与产品一致（热键先改写，消息随后被写路径消化）：

```
读路径：translate(text, recall(store, query=text, context={app:"docs", task:"postmortem"}))
        → 必须用第 1..40 轮学到的规则改写它
        → 且必须不去满足那句抱怨本身（抱怨说的是"以后的 postmortem"，
          这一份正在写；这是 one-off vs durable 的分界，也是最难的一格）

写路径：screen_message(text, existing_keys) → spans → Pipeline → run_extraction
        → gold effect: new(c-postmortem-timeline-first)
```

三件事只有 carrier 轮能测，而今天一件都测不了：

1. `screen_message` 的 discourse/material 切分在**真实混合消息**上的行为——今天喂给它的 `natural_correction` 是一句纯规则，切分器无事可做。
2. translator 在**请求文本本身就含规则语句**时会不会去执行那句规则、或把它删掉（`preserves_request` 的 P0 缺陷正是这个形状）。
3. 同一句话既是任务又是规则时，durable / one-off 的判定。

`S`（standalone）轮保留 9 个，因为裸规则消息真实存在，只是不是主流。比例 26:9 是这套设计对「真实分布」的赌注，也是可证伪的：如果 carrier 轮和 standalone 轮的分数差不到 0.05，说明这个区分没有信息量，下一版就砍掉 carrier 配额。

---

## 6. graph 怎么用，以及 10 条人工预算花在哪

### 6.1 图的形状

**节点** = 720 个 gold constraint 节点。cheap LLM 标注：`bucket`（六问有序判定，直接抄 `docs/2026-07-26-bucket-taxonomy.md` §1 的顺序）、`key`、`scope`、`polarity`、`binding`、`salience`、`applies_to`（能在哪类请求上开火）。

**边**：

| 边 | 来源 | 是否需要 LLM |
|---|---|---|
| `supersedes(a→b)` | 我们构造的（`tighten` move 或编排的 contradict） | 否，构造性 |
| `duplicate_of(a,b)` | 我们从语料同义簇里选的 | 否，构造性 |
| `conflicts_with(a,b)` | LLM 在 catalogue 内标（先按 bucket×key 分桶剪枝，剩 ~60 对/episode） | 是 |
| `applies_to(node → request)` | LLM 在 probe 上二元判断 | 是 |

**VALIDITY**（某条在某前缀上是否还有效）= 对 authored effect log 做 fold，纯图上的可达性查询。**零 LLM，零意见**。这是 spec §3.2 第 1 条已经确立的「构造性为真」，图只是把它变成一次查询。

**ACTIVATION**（用户最终提交请求那一刻这条记忆该不该开火）= §4.2 那个五项合取。前三项是产品自己的代码（`gold fold` / `_scope_ok` / `recall`），第五项是 harness 的账本。**只有第四项 `applies_to` 是判断**——而它就是今天 persona 文件里那个手写的 `applicable` 字段。

也就是说：图把 LLM 标注面从「672 条 × 8 个前缀的状态」压缩到「两类二元问题」。

### 6.2 两个二元问题各自都有免费的机械交叉检查

- `conflicts_with` 必须与构造出来的 supersede 链一致：若 a supersedes b，则 a 与 b 必冲突。LLM 答案与 authored 边矛盾 = LLM 错，零成本抓到。
- `applies_to` 有一个机械先验：gold `key` 的词法表面形（复用 `signals.py::_KEY_LEXICON`）在请求文本里命中，则 `applies_to` 大概率为真。

### 6.3 10 条怎么花——一次，在 pilot 阶段

我建议用 lever (a) 的形式实现，但让它同时完成 lever (b) 的功能：

对每个候选 `(node, request)` 拿三个**独立**信号：

1. 词法先验（机械，零 token）
2. DeepSeek 的二元 `applies_to`（temp 0）
3. DeepSeek 对**同一请求的改写表面**再判一次（改写表面我们本来就生成了，免费）

分流：

- **三者一致 → 自动接受**（预期 ~80%）
- **任一不一致 → 进升级队列**，按 (分歧数, bucket 稀有度) 排序。bucket 稀有度优先给 `task_goal` / `reasoning_policy`——taxonomy 文档实测这两个桶的歧义率 23%，是最该花人眼的地方
- **队列 top-10 → owner 看，一次**

owner 那 10 条标签有两个用途，一次投入两处收益：
1. 定操作点：分歧项的默认归宿是 `may_carry`（两个方向都不计分）还是 `must_carry`
2. 成为 `applies_to` 标注 prompt 的 few-shot exemplar，喂给全部剩余语料

其余分歧项一律 → `may_carry`，不计分。

这里有一笔必须公开的账：`may_carry` 是在**用区分度换标注成本**。如果 `may_carry` 超过 applicable 集的 15%，诚实的读法是「activation 标注器不够好」，不是「产品得了 X 分」。所以 **`may_carry` 占比必须与每个分数并排公布**，并在 >15% 时不出 headline。

---

## 7. 生成管线（人工触点只有一个）

| 步 | 内容 | 谁做 |
|---|---|---|
| G0 | 按 §1 预算取候选，落 `bench/gen/harvest/<source>.jsonl`（gitignore），逐条带 provenance | 脚本 |
| G1 | SKELETONISE：源句 → skeleton。**此后源句不再跨墙** | cheap LLM |
| G2 | 准入闸跑在 skeleton 上：G1 抓手（四选一）/ G2 反事实 / G3 桶判定 / G4 第一人称主语 | 3 机械 + 1 LLM |
| G3 | 变异 skeleton 字段；自动导出 `distinctive` 与 mech 判据 | 机械 |
| G4 | UTTER：skeleton + persona card + incident hook → 3 个 surface + `clause` + `alt_clause` | cheap LLM |
| G5 | 四道验收（回读 / licence n-gram / 风格 / 污染 grep） | 2 LLM + 2 机械 |
| G6 | 编排 episode：按 §2.2 日程排引入与失效，插 distractor，定 probe 与 context 精度，写 `diff_plan`。确定性 + seed | 机械 |
| G7 | fold gold；用图 + 模拟 recall 导出 `must_carry` / `must_not_carry` / `may_carry`；回填 `checkpoints[].expect` | 机械 |
| G8 | lint（下表） | 机械，进 CI |
| G9 | pilot 跑 1 个 episode → 升级队列排序 → **owner 看 10 条** → 重拟合 → 重跑 G7/G8 | **唯一人工触点** |

### lint（零 LLM，进 CI）

1. `must_carry` 的每个 cid 在该前缀 gold-active、scope 与 probe context 相容、**且通过模拟 `recall()`**
2. `must_not_carry` 的每个 cid 在该前缀已失效或未引入
3. 每个 `must_not_carry` 与同 probe 内某个 `must_carry` 共享 `key` 前缀（陷阱不许白送）
4. `conflicts_with` 对永不同时 active；且与 authored supersede 链一致
5. 峰值 active > 48 且某 checkpoint 的兼容池 > 32——**否则该 episode 没越过阈值，拒绝加载**
6. `standing_order` surface ≤ 25%；distractor ≥ 8 且八类各 ≥1；存在一个 ≥8 轮的全静默窗口
7. 每条 constraint 的 mech 判据可从其 skeleton 重新推导出来（判据与 skeleton 不许漂移）
8. 每条数值型条目带 `provenance.mutation`
9. 全部 `provenance.use == "skeleton-derived"`，无任何 `verbatim`
10. `gold_state` fold 结果与 `checkpoints[].expect` 一致；`gold.py` 与 `Store.apply_ops` 的 10k fuzz 等价测试通过

spec 的 lint 第 9 条（非 new effect 双人签字）删除，由 §3 的构造性 diff + §6 的三信号分流替代。

### 三个对照臂保留（spec §4.5）

`null-dump`（从不 retire、按 strength 取前 32 无脑注入）、`flat-dump`（绕过 recall 全量注入）、`oracle-ceiling`。理由不变，且现在 SUPPRESS 半边有了真实断言量，`null-dump` 的判定比 spec 写的时候更有力。

额外加一个必报的观测：**`peak_active_observed`**。一个只学到 20 条规则的系统永远到不了 48，密度阈值一次都不会被跨过，suite 会静默退化成稀疏 store 测试而分数看起来还不错。这是这套设计最容易被漏掉的陷阱。`oracle` 模式（注入 gold state）保证跨越，用来把「没跨过阈值」和「跨过了但做错了」分开。

---

## 8. 与 spec 的差异清单（备案）

| spec 原文 | 本设计 | 理由 |
|---|---|---|
| Suite R，12 scenario × 56 constraint，E 退役 | 就是 Suite E，12 episode × 60 节点 | owner 裁定 |
| P5 逐条人工写判据 | 判据从 skeleton 自动导出 | 人工预算归零 |
| P7 非 new effect 双人签字 | 删除，构造性 diff + 三信号分流 | owner 裁定 |
| lint 9 双人签字 | 删除 | 同上 |
| `use ∈ {verbatim, adapted, mutated, original}` | 全部 `skeleton-derived`，repo 内零第三方原文 | licence + 反记忆一起解决 |
| checkpoint 卡 RECALL_CAP / CONSOLIDATE_ACTIVE | 同，但补上 scope 过滤对兼容池的影响，并用 probe context 精度分别施压 | spec 漏算了 `recall()` 的 cap 在 scope 过滤之后 |
| event 三取一 signal/request/distractor | 五取一，新增 carrier（请求与信号是同一个字符串） | owner 的「融入 user history message」 |
| `final` 写在 case 文件里 | 只写 `diff_plan`，`final` 运行时从 SUT 的 `polished` 造 | `polished` 是 SUT 的输出，不是常量 |
| second-half 固定切点 | 按 constraint 成熟度（`flushes_since_intro ≥ 1`） | 86 轮下固定切点无意义 |
| 672 条采购 | 612 条采购 + 108 条派生 | successor 是前驱的变异，不消耗语料 |

### 自报风险

- **[high]** gold 仍然是我们的意见，而样本量会让它看起来像测量——且现在双人签字没了。3,600 个断言会吐出带紧凑 CI 的三位有效数字，底下的标注噪声可能有 10-20%。
  - 缓解：把「意见」压缩到一个字段：validity / suppress / scope / recall 全部构造性或直接调产品自己的函数，只有 applies_to 是判断。每个分数并排公布 may_carry 占比；>15% 时不出 headline，读作「标注器不够好」而非「产品得了 X 分」。
- **[high]** applies_to 标注器与 carriage judge 是同一个模型家族（DeepSeek），误差相关——suite 可能在给自己的意见打分。
  - 缓解：标注与判分必须是两个独立调用，且词法先验（_KEY_LEXICON，零 token）是真正独立的第三方信号。把三方一致率当 suite 健康度指标每次公布。若一致率 < 0.85，先修标注器再看产品分。
- **[high]** SUT 若欠提取（只学到 20 条），active 永远到不了 48，两条密度阈值一次都不跨，suite 静默退化成稀疏 store 测试，而分数看起来还不错。这是本设计最隐蔽的失效模式。
  - 缓解：每 episode 必报 peak_active_observed 与「兼容池是否曾 >32」；lint 第 5 条在 case 侧保证可跨越，oracle 模式（注入 gold state）在运行侧保证跨越，用来把「没跨过」与「跨过了但做错」分开。
- **[medium]** skeleton clean-room 的 licence 论证（命题不受版权保护、repo 内零第三方原文）是我的推断，尤其对 CC BY-SA 源（Wikipedia 占 thin-bucket 已提取的 23%）。
  - 缓解：这条必须 owner 签字，不作为已定事实。签字前 BY-SA 源全部标 copyleft_derived=true 并冻结在 pilot 之外；先只用 Apache-2.0 / MIT / CC-BY / public-domain 源跑 pilot，证明管线可行后再谈 BY-SA 要不要进。
- **[medium]** 回读闸与风格闸方向相反：回读要求命题精确保留，风格要求像真人随口说。闸门可能悄悄选出「可验证但生硬」的句子，于是 suite 又变回一个复读机测试。
  - 缓解：cp-00 的 E-legacy-band 是可证伪的检查：同样 ~6 条规则密度下，生成的 utterance 若比今天手写 persona 明显更难学（分数低 >0.10），说明生成器在往生硬方向漂。同时公布风格分分布而不只是通过率。
- **[medium]** diff 三元组由目标 op 反向构造，比现实容易——真实编辑的意图本就模糊（L 的 revoke 今天 0.50 是证据），suite 可能在 diff 通道上系统性高估。
  - 缓解：messy 变体（clause 同时隐含推翻某条已存规则）+ accept 宽容集，进单独的 E-amb band 不进 headline；同时把 revert_injection（期望零 op）配到 25%，它是这条通道唯一的负向控制。
- **[medium]** cp-06 密集 store 上 consolidation 可能因输出预算截断而静默失败：52 条 active、6 个 bucket 分组，consolidate.py 的 max_tokens=1200 可能截断 JSON，parse_ops 直接返回 []，读起来像「产品不会 merge」。
  - 缓解：每次 consolidation 记录 parse flags 与 prompt/输出 token 数；带 parse flag 的空 consolidation 记为基础设施事件，不计入 merge 分。这本身也是这套 suite 该抓到的第一个产品缺陷。
- **[medium]** parallel.py 的 checkpoint 粒度是整个 episode。86 轮的 episode 在第 70 轮撞上限流会丢全部 70 轮，而 episode 长度是今天 persona 的 5.4 倍。
  - 缓解：加轮级 checkpoint（每轮 append translate 输出 + store 快照 + pending 队列），resume 时从最后一轮继续。这是纯 harness 工程，可以在写任何 case 之前先做。
- **[low]** reword 这一档现在无法计分：providers.py:107 的 V1Provider.extract 显式把 style_rule op 从 bench 契约里滤掉。
  - 缓解：要么放宽契约让 style_rule 进 bench，要么这一档降级为 report-only 并把配额从 15% 挪给 add_constraint。需要 owner 拍一下，别默认。

### 未决问题

- 10 条人工预算花在 activation 标注（我的建议）还是 utterance 自然度？两者只能选一个。选 activation 的理由是它是唯一进分数的判断层；选自然度的理由是生成器一旦跑偏，整批 612 条都要重来。
- skeleton-derived provenance（repo 内零第三方原文、只留 source_id/url/licence）能否满足 CC-BY 的署名要求，以及能否让 CC BY-SA 源（Wikipedia，占 thin-bucket 已提取的 23%）合法进主干？这是法律判断，需要你签字，我不替你认定。
- STATE（store 对齐：active_f1 / zombie_rate / chain_fidelity）进不进 gate？进的理由是你的框架里「完整记录」就是它；不进的理由是对齐层最脆、还要额外 40 对对抗对照集。
- 612 条采购 + 108 条派生（vs spec 的 672 条全采购）可以吗？派生的 108 条是前驱的字段变异，不消耗语料预算，但它们在统计上不是独立样本。
- bench 契约要不要放宽到包含 style_rule op？不放宽的话 reword 那一档（15% 的 diff 轮）只能 report-only。
- 12 个 episode 的语言分布怎么定？今天 8 个 persona 里 6 个是中文。thin-bucket §2.2 的瓶颈 2 指出现有语料集中在 research/code/journalism/stats 四个域，若 12 个 episode 里有 7 个落在这四个域之外，缺口 50-55 条要靠 scope transposition 补——这会影响 episode 的领域选择。
- 轮次 86 是我按密度日程倒推的（要在 cp-06 达到 52 active 同时携带真实比例的失效）。如果你更看重墙钟或成本，可以压到 ~70 轮，代价是 cp-06 的 active 峰值只能靠减少失效来维持，失效原因配额会被挤掉。

---

## 设计 3：Suite E 扩容规范的 delta 审计：人工防线全部作废后，什么机制顶上、什么真的丢了

## 0. 先回答 owner 的第 5 问：语料在什么级别

我在仓库里实际核过（不是从文档转述）：**`bench/gen/harvest/` 不存在，仓库里没有任何 harvest jsonl**。`bench/gen/` 下只有 `prefeval-notes.md` / `judge-audit.md` / `prompts.md`。

分层盘点：

| 层 | 内容 | 现状（核实） |
|---|---|---|
| L0 源裁定 | 哪些源许可干净 | **完成**。scaleup §1（14 用 / 3 慎用 / 12 弃）+ thin-bucket §1（18 用 / 12 慎用 / 22 弃）。唯一真正做完的一层 |
| L1 原子句 | 一句一条的 constraint 文本 | thin-bucket 文档自述「已提取 189 条」（reasoning 139 / task_goal 50），**落盘的只有文中引用的 17 句**（§3.1 十二条 + §3.2 五条）。其余 172 条在本 repo 查无实据。另外四个桶（output_contract / deliverables / execution_policy / communication_style，约 500 条）**为零**，只有预算表 |
| L2 catalogue 条目 | 带 `key`/`scope`/`bucket`/`salience`/`distinctive`/`grade` | **0** |
| L3 图 | 冲突边、继任边、撤回边、失效边 | **0** |
| L4 episode | 折进用户历史的消息文本 | **0** |
| L5 event log + checkpoint + probe | 有序日志与前缀探针 | **0** |

所以 owner 的判断成立且比他说的更严重：不只是「只有原子句」，是**连原子句都只有 17 句落盘**，两个薄桶的 189 条是调研过程中的中间态，四个胖桶的 ~500 条从未开工。「合计预算 ~770、实需 672、留 15% 余量」是一张计划表，不是库存。

真正的工作量在 L1→L4 这三跳，正是原 spec 用 P6「人工编日志」顶着的那一格。新方向的全部价值在于把 **L3 提到 L4 之前**——先定图，再由图生成 episode。下面所有替换机制都建立在这个反转上。

---

## 1. 核心替换：图的方向必须反过来

owner 提的是「DeepSeek 给每条 constraint 标 lifecycle 与 scope，再用图导出 activation 与 validity」。方向对，但**在正确性攸关的那一层必须反过来**，否则只是把两个人的意见换成一个模型的意见，而 §7 开头那句自我警告（「gold 是我们的意见，而样本量会让这个意见看起来像测量」）会变得更糟不是更好。

把图切成两层，两层的可信度完全不同：

**Layer 1 — 逐条静态属性（LLM 标注合法）**
`bucket`（按 bucket-taxonomy §1 的六问有序判定）/ `key` / `scope{app,task,lang}` / `polarity` / `binding` / `facet_family` / `distinctive` / 是否机械可判。这些都是**单句的函数**：第二个标注者只读这一句就能复核，错误是局部的（412 号标错桶只毁 412 号）。LLM 在这层是合法标注者，自一致性可测。

**Layer 2 — 关系边（LLM 标注不可作为 gold）**
`supersedes` / `merges_with` / `revoked_by` / `scope_dead_at` / `conflicts_with`。它们决定每个前缀上的 validity，一条错边污染其下游所有 checkpoint。LLM 在这层给出的是**假设，不是 gold**。

处置分两路：

- **`conflicts_with` 机械导出，不标注。** 同 `key` + 数值不同（`format.line_length`: 79 / 80 / 96）或 `polarity` 互斥（`require` vs `prohibit`）即为冲突对。这是 Layer 1 属性上的集合运算，零判断。spec §3.1 列的三组真实冲突（PEP 8 vs Google Py vs 变异 96；Google devdocs serial comma vs GOV.UK；Conventional Commits vs 本项目 `[scope] content`）本来就是这么来的，只是原来靠人眼发现。
- **其余边先定后写。** 拿到冲突对 (A,B) 之后，**生成** episode：「写一句话，这个持有 A 的用户在此改用 B」→ 边 `contradict(A→B)` 就是**构造性为真**，与 spec §3.2 第 1 类 ground truth 同级，不需要任何人复核。retire / merge / reinforce / new / distractor 同理。

**round-trip 验证**（这是替代双人签字的那件东西）：一个独立标注者只看 {该事件之前的 store 状态, 生成的消息}，必须还原出预期的 op。

- 还原成功 → 该消息确实无歧义地编码了这条构造性为真的边。
- 还原失败 → 这条消息有歧义。**这是数据不是错误**，进 `E-amb` band 带 `accept` 集合，不删（spec §9「不删歧义 case」原样保留，且现在是结构性中心而不是一句纪律）。

诚实说明这买到了什么、没买到什么：它证明「消息忠实且无歧义地编码了一条构造为真的边」，**不证明「人类标注者会给同样的 op」**。这是比双人签字弱的主张，但它是 672 条规模能支撑的主张，而且可重跑、覆盖率 100%（不是抽样）。

**一个反直觉的检查项**：round-trip 分歧率**过低**是坏信号。L 的 `revoke` 今天 0.50，证据就是真实用户在 retire/contradict 之间本来就模糊。如果生成的撤回语句分歧率显著低于真实语料，说明生成器把 bench 洗成了容易的一半——这正是 spec §2.2 拒绝「有歧义就改写」时警告的东西，只是现在改由生成器犯。所以要**按失效原因分族公布 round-trip 分歧率**，并对 retire/contradict 族设下限而非上限。

---

## 2. 逐项裁决：死了什么，谁顶上

### P7 双人签字（§5）—— 死

替代：§1 的 construct-then-round-trip。产出物对齐关系：

| P7 产出 | 替代产出 | 强度变化 |
|---|---|---|
| 非 new effect 的两人一致确认 | 边的构造性为真（不需确认） | **更强**（定义 vs 判断） |
| 不一致 → `label: ambiguous` + `accept` 集 | round-trip 不还原 → 同样进 amb band | 相当 |
| 逐失效原因的作者分歧率 | 逐失效原因的 round-trip 分歧率 | **更弱**（两个相关模型 vs 两个独立人），但 n 从抽样变全量 |

### lint 规则 9「所有非 new effect 必须两人签字」—— 死

替代三条机械 lint：

- **9a**：每条非 `new` 的 `effect` 必须指向一条在 Layer 2 图里存在的边，且该边的两端在 catalogue 中；孤边拒绝加载。
- **9b**：每条非 `new` 的 `effect` 必须带 `roundtrip: {recovered: bool, labeller: <model@version>, at: <ts>}`；缺字段即拒绝。
- **9c**：`recovered: false` 的事件必须带非空 `accept` 集合，且只能出现在 `E-amb` band 的统计里，不进 headline。

三条都是结构断言，零 LLM，进 CI。

### §5 人工审核 checklist（7 项）

| # | 项 | 裁决 |
|---|---|---|
| 1 | 每条都能想象成真人说过 | **部分可机械化，剩下的是真损失**（见 §6） |
| 2 | `distinctive` 在 `src/` grep 不到 | **全机械**。`tests/test_no_bench_contamination.py` 已实现同类守卫，扩一个 `distinctive` 字段的 pass 即可 |
| 3 | 数值型 style-guide 规则已变异并记录 | **全机械**，就是 lint 8 |
| 4 | 陷阱在同一 facet 上 | **全机械**（lint 3 的 key 前缀），且应升级：见 §4 陷阱活检 |
| 5 | 非 new effect 两人同 op | **死**，见上 |
| 6 | 6 条 defect 条目各有事件当靶子 | **全机械**：带 `defect` 的条目必须被 ≥1 个 widening/merge 族事件引用 |
| 7 | `notice` 覆盖全部源 | **全机械**：`provenance.source` 集合 ⊆ `notice` 集合 |

七项里五项干净机械化，一项部分，一项死。这个 checklist 当初就不该是人工的。

### P4 变异（人工逐条）—— 机械化，有产量损失

- 数值变异：正则找数字 + 变异表 + 回填 `provenance.mutation` + lint 8 拒收未变异者。全机械。
- 「无数值可变异的高记忆度规则取反或丢弃，取反语义不安全就丢」：唯一的判断点。机械版本是 **fail-closed 白名单**——只有列在「取反安全」的 key 族（`format.*`、`length.*`、`lexicon.*` 这类）才允许自动取反，其余一律丢。
- **损失的是产量不是正确性**。这就是 thin-bucket §2.4 那个 1.4× 余量的用途。可以承受。

### P5 写 `distinctive` 与 `grade`（人工逐条）—— 机械化，但留了一个真洞

- `distinctive`：变异数值或自造词，模板可导出。
- `grade.mech`：由 `distinctive` 直接生成（`contains_all` / `not_contains` / `numeral_present`）。
- `grade.judge_criterion`：LLM 按固定模板起草。

**危险**：条目和判据出自同一进程——空洞的 constraint 会得到同样空洞的判据，写的人和判的人都发现不了。这是原 spec 把 P5 定为「不能自动」的真正理由。

**替代（这是整份 delta 里最强的一条机器替换）**：把 thin-bucket §5.2 的 G2 反事实闸变成准入硬闸，且全自动——

> 为每条 constraint 生成一对（合规改写 / 违规改写），判据必须接受前者、拒绝后者。两个都过或两个都不过 → 判据作废，条目降级为 `may_carry`（两个方向都不计分）。

它同时干掉三件事：空洞判据、「正确的废话」型 constraint（写不出违规样例的条目自动出局）、以及 §4.3 那条「准入门槛」里本来要靠人抽检兑现的部分。

**留下的洞（必须明说）**：违规样例由同一个模型生成，判据若只咬一个表面 token，模型写的违规样例大概率也刚好缺那个 token，于是「通过」了。缓解：违规样例必须由**另一条 prompt** 生成，要求「违反该 constraint 但保留其表面词汇」（hard negative）。在有机械判据的那 ~40% 上，还有 mech-vs-judge 一致率作外部校验；**在没有机械判据的那 60% 上没有任何外部校验**。这是 §6 的第一条真损失。

---

## 3. §7 十三条防线逐条裁决

| # | 防线 | 裁决 | 替代 / 备注 |
|---|---|---|---|
| 1 | 非 new effect 双人签字 + amb band + 分歧率公布 | **死一半** | 签字死；amb band 与分歧率公布**存活**，改由 round-trip 供给 |
| 2 | `null-dump` 不过即作废本次 run | **原样存活** | 纯机器。**更重要**：见 §4 |
| 3 | `flat-dump` 是 go/no-go | **原样存活** | 「50 条不构成压力」这个结论本身仍是合法产出。文本里的「50 条」要按最终 catalogue 规模重述 |
| 4 | 陷阱有效性活检（null 系统逐 probe 失败基率） | **存活并升级为闸** | 原来是「报出来」，现在必须是**自动隔离**：null 臂能通过的 probe 零信息量，直接移出计分集。这条同时兑现 checklist 4 和 thin-bucket G7 |
| 5 | `distinctive` 哈希 grep `src/`，反向也查 | **原样存活** | 已有 `tests/test_no_bench_contamination.py`，加一个 `distinctive` pass |
| 6 | 数值强制变异，lint 拒收 | **原样存活** | |
| 7 | 高记忆度规则取反或丢弃 | **存活，判断点 fail-closed** | 白名单外一律丢，损失产量 |
| 8 | IFEval boilerplate 改成 user-voice | **存活，但从「纪律」变成「闸」** | 靠 thin-bucket G5（self-instruct 175 条种子做风格锚）+ §6 的 2AFC 判别器强制，不能再靠作者自觉 |
| 9 | 逐条 provenance，NOTICE 由并集生成 | **原样存活，逐字继承** | |
| 10 | lint 白名单挡非可再分发许可的 verbatim | **原样存活，逐字继承** | |
| 11 | 不新增 NC 依赖 | **原样存活，逐字继承** | |
| 12 | AgentIF-OneDay 附件绝不 vendor | **原样存活，逐字继承** | |
| 13 | `gold.py` ↔ `Store.apply_ops` fuzz 等价 | **存活且更关键** | 但**不能写成状态相等**，见下 |

**第 13 条的具体坑（我读代码核到的）**：spec 的 gold 状态机用 `{active, invalidated}` + 四种 reason，而产品 `schema.py:16` 是 `STATUSES = ("active", "retired")` 二值——taxonomy-verdict §4.3 明确「沿用二值，不采纳 7 值方案」。所以等价测试必须写成**同态**而非同一：把 gold 的 `invalidated/*` 投影为 `retired` 后断言相等，reason 与继任指针另行对照产品的 `supersedes` 字段。谁按字面写成相等断言，要么测试红，要么有人「顺手」给产品加字段——而那正是 §9 明令禁止的「不因 bench 而改产品 schema」。

另外两处会让两台状态机漂移的产品行为，fuzz 必须覆盖：
- `store.py:17` `AUTO_RETIRE_AT = -2`：`bump_strength` 是**第二条通往 retired 的路径**，gold 日志里没有对应事件。
- `store.py:141-148` `merge` 只把 `supersedes` 指向 `targets[0].id`，多对一合并的其余前驱没有反向指针——`chain_fidelity` 对 merge 只能校验第一个前驱，这个上限要写进分数定义，不能当成产品缺陷计分。

---

## 4. 三个对照臂：存活，且现在是主要仪器

确认全部存活，全部机器可跑，**并且重要性上升一个档次**——它们现在是**仅存的、能在无人参与的情况下作废一次 run 的东西**。人工防线撤掉之后，对照臂从「附加检查」变成「唯一的效力证明」。

三条具体升级：

1. **`null-dump` 从 run 级作废升级为 probe 级隔离。** 原来只在整个 run 的 suppress 半边比对；现在逐 probe 记 null 臂的通过率，通过率高的 probe 自动移出计分集并单独列表。这是把 §7.4 从遥测变成闸。
2. **`oracle-ceiling` 从「≥0.9 否则 case 有 bug」升级为 CI 门禁。** 672 条是机器生成的，判据也是机器生成的，`oracle < 0.9` 现在是「生成管线坏了」的主要报警信号，应该在冒烟档就跑，不是全量档。
3. **建议加第四臂 `shuffled-store`**：注入数量正确但**来自另一个 scenario** 的 active 条目。它分离「携带了正确的规则」与「携带了看起来像那么回事的规则」。这是对 judge 松紧度的直接检验——如果 judge 在别人的 store 生成的改写上仍判 `must_carry` 命中，那条判据不具区分性。**这是失掉的 judge 抽检里唯一能被机器捡回来的那部分。**

---

## 5. 命名：Suite R 不存在了，这是 Suite E

### 权重

`bench/runner/config.py:41` 当前 `WEIGHTS = {"T": 0.4, "L": 0.3, "E": 0.3}`。

改成 **T .25 / L .25 / E .50**（即 spec 原方案里 R 的位置）。三条理由，第三条是新的：

1. E 现在是性能/对外可引用的那个数（LoCoMo 的类比位）。给它 0.3 与「高分 = 可以拿去用」自相矛盾。
2. T 与 L 是 functionality 单点测量，每类别 n=10，`p=0.5` 时 Wilson 95% CI 半宽 ±0.26。**这样的精度扛不起 70% 的 gate 权重**，现在的 .4/.3 分配是历史遗留不是设计。
3. 反向张力也要说清：把 50% 权重给一个 ground truth 最新、验证最弱的 suite 是有风险的。解法在 §7 的 E-mech / E-judge 双 band——**首版 gate 只压 `E-mech`（无 judge 在环、全机械可验证的那一半），`E-judge` 报出但不入 gate**。这样权重上去了，可验证性没下降。

### 阈值

**不继承，且这次比 Suite R 时代更危险，因为名字一样。** `GATE_OVERALL = 0.80` / `GATE_PER_SUITE = 0.70` 是按 v1 E 语义（8 persona × 3 规则 × 二分判定）定的。新 E 的量纲完全不同，而且**新 E 必然先掉下来**——今天 0.667 是在 3 条规则的 store 上拿的，49 条 active 的密度下不可能更高。spec §0 说「前两次全量跑不设 gate」，这一条原样保留并加一条实现要求：

- `write_snapshot` 增加 `metric_version` 字段，`report.py` 对 version 不匹配的快照**拒绝计入 gate**，而不是静默按老阈值判。

### `bench/results/` 的具体地雷（我核过代码）

`bench/results/` 下已有 8 份 `E-*.json` 与 2 份 `E-repaired-*.json`，语义与新 E 不兼容。`report.py:59-70` 的 `latest()` 已经正确处理了 `E-repaired` 的后缀混淆（那个 bug 修过了），但它按文件名取 `max()`，新旧同名共存意味着**任何纵向曲线都在混两把尺**。处置：把 8 份旧快照移入 `bench/results/archive/`，并靠 `metric_version` 兜底。

### `bench/runner/config.py` 里会直接炸的三个常量

- `E2E_PERSONA_COUNT = 8` —— `run_e2e.py:151` 是硬 error（globbed ≠ 8 就拒跑）。新 E 的 scenario 数不是 8，这行会直接挡住第一次运行。
- `E2E_SECOND_HALF_FROM = 9` —— 「后半程 rounds 9..16」是 16 轮结构的产物，对 112 事件 / 8 checkpoint 无意义。
- `E2E_PASS_THRESHOLD = 0.8` —— 已注释为 REPORTING ONLY，但会出现在新报告里造成误读。

### 8 个 persona 文件

spec 的处置（升级为种子 + 留 `E-legacy` 冒烟）成立，只改一件事：**别叫 `E-legacy`**，新旧同为 E 会让「E-legacy」这个名字自相矛盾且再次污染 glob。改叫 `E0` 或 `smoke`，走独立的 suite id、独立的 results 前缀、不进 gate。

三条必须保住的东西：
- 24 条规则（8 persona × 3）进 catalogue 作 `first_seq ≤ 6`，占据新 scenario 的低密度前缀（对应 cp-01/cp-02）。
- **`E-chained 0.727` vs `E-repaired 0.841` 这一对是本项目唯一的纵向锚点**，必须作为 N1 的验收基线（新 harness 在 oracle 模式 + cp-01/cp-02 密度下与它相差 ≤0.10，差得多说明 harness 错了）。
- 今天 222 个判定点、per-persona repeat spread 0.47 —— 这个 spread 是新 suite 必须打下去的靶子，要在报告里并列。

---

## 6. 真的拿不回来的（不编替代品）

**（1）没有机械判据的那 60% 上，judge 准确率无法测量。**
原 §4.3 / P10 是 6 个 facet × 20 条 = 120 条人工抽检，人力预算 10。机器能提供的只有：judge 自一致性（测稳定性不测准确性）、以及**在同时有 mech 判据和 judge 判据的重叠子集上的 mech-vs-judge 一致率**（这里 mech 侧是真值，所以是真的准确率测量）。问题在于这个重叠子集**系统性地是容易的那一半**（数字、禁用词）。tone / method / reasoning_policy / task_goal——正好是 MCJudgeBench 警告的类别，正好是两个薄桶，正好是产品的差异化所在——**judge 在这些类别上的准确率将一直是未知数**。现有 29/30 的背书是 1–3 规则 context 下拿的，不转移。这是最大的一条不可恢复损失。

**（2）语料级真实性无法自证。**
checklist 第 1 条「每条都能想象成真人真的说过」。机器能做的：thin-bucket G1（抓手闸）/ G4（第一人称闸）是 boolean，可跑；再加一个 **2AFC 判别器**——把生成句与许可干净的真实用户文本（PRISM `open_feedback`，CC BY 4.0，§1 已裁定可用）混合，让 judge 二选一挑出真人写的；显著高于 50% 即判定语料可辨认为合成。

它证明的是「单句不可辨为合成」，不是「真有用户持有这条偏好」。而且它对**分布级错误完全盲**：672 条每一句都像真的，但这**组**偏好不像真实用户群，判别器测不出来。10 条人工看不出分布，看 10 条只能抓系统性校准错误。**这个损失是真实的，不要用「LLM 判过了」盖过去。**

**（3）生成器的口吻会被烤进整个语料。**
所有 ~250 条 retire 事件的措辞出自同一个生成器。如果它写的撤回语句比真人干净，E 就在 retire 上测简单模式，而 retire 恰是 L 今天 0.50 的类别。缓解是 §1 那条反向检查（retire/contradict 族的 round-trip 分歧率**下限**）+ 用 PRISM 真实撤回语句做改写锚。但**「真实分歧率是多少」我们没有测量值**——所以这条缓解目前是有方向、无刻度。

**（4）人力 10 条的花法（我的建议，需 owner 拍板）。**
选项 (a) 与 (b) 二选一其实花不起：672 条上哪怕 5% 分歧就是 34 条，(b) 的升级量天然超预算 3 倍。建议**分割并给 (b) 加排序规则**：

- **6 条给 (a) 前置校准**，全部投在 **retire vs contradict 的判定边界**上。理由：校准错是全局同向错（672 条一起偏），单条标错只毁一条；而 retire/contradict 是整张生命周期图唯一的承重判断，也是 L 今天最差的类别。
- **4 条给 (b) 升级通道，按图的度数排序**：只升级 round-trip 未还原的事件里**下游影响最大**的那 4 个（继任链链首影响其下所有 checkpoint，叶子 filler 只影响一个）。这正好用上 owner 要的那张图，且是可辩护的机械分配规则。
- 其余全部进 `E-amb`，永不删除。

---

## 7. 计分结构的两处必改（新方向逼出来的）

### 7.1 `E-mech` / `E-judge` 双 band

judge 准确率在 60% 的条目上不可测，那就不要把它混进要拿去 market 的那个数：

- **`E-mech`** —— 只统计有机械判据的断言（`preserves_request_ratio` 闸 + `contains_all`/`not_contains`/`regex_*`/`numeral_present`/`same_language`）。**无 judge 在环，完全可复现，这是可以不带星号引用的数。** `must_not_carry` 的绝大多数天然落在这里（前驱的 distinctive token 不出现），所以反 dump 的那半边几乎全在 mech band。
- **`E-judge`** —— 其余断言，报出时**必须并排给出重叠子集上的 mech-vs-judge 一致率**作为误差条。

代价要说清楚：`E-mech` 会系统性偏向 output_contract / deliverables（数字与词面），两个薄桶几乎全在 `E-judge` 里。所以 mech 比例应当被当作**可主动调节的设计杠杆**（选条目、选变异时优先挑机械可判的），但不能把薄桶压没——那半个才是产品要赚钱的地方。gate 压 mech、报告看 judge，是这个张力唯一诚实的解法。

### 7.2 activation ≠ validity，而 `RECALL_CAP` 会让 must_carry 撞墙

owner 的 activation 定义（「用户最终提交请求那一刻，这条记忆该不该 fire」）在产品里已经有确定性实现，就是 `recall.py`：

```
active ∧ kind=="requirement" ∧ scope_ok(scope, context) ∧ (|pool| ≤ 32 或 key 命中 query / 按 recency 补位)
```

前两个合取项是 **validity + scope**，可以从图导出，是 gold。**第三个合取项是产品策略，不是 ground truth。**

spec 的 lint 规则 1 只要求 `must_carry` 的 cid「在该前缀 active 且 scope 相容」，没有考虑 cap。而 spec 自己的 cp 表在 **cp-05 active=42、cp-06 active=49** —— 都超过 `RECALL_CAP = 32`。也就是说 **cp-04 起，`must_carry` 里可以合法地出现 `recall()` 永远不会返回的条目**，E 的天花板被机械地压到 1.0 以下，而分数无法解释成「系统错了」。

这是 spec 里一处必须修的实质缺陷。两条出路，必须选一条并写明这是决定不是意外：

- **(i) 让 lint 直接调用真 `recall()` 生成 `must_carry`** —— 分数干净，但 gold 绑死当前 recall 实现，recall 一改 gold 就变，且这本身就是一种 bench 过拟合。
- **(ii) gold 只声明 validity + scope，分数拆成 `carry@valid` 与 `carry@cap` 两个数** —— headline 用哪个由 owner 拍。我倾向 (ii)：cap 内的选择质量本来就该是一个独立指标（`recall()` 在超 cap 时的挑选正确率），把它和「记住了没有」混成一个数是在丢信息。

顺带三条产品事实，进 lint 否则会白扣分：
- `extraction.py:157` 丢弃 `salience < SALIENCE_MIN(3)` 的 op —— catalogue 里给 salience 1–2 的条目**在设计上不可能被写进去**，必然记 miss。lint 应拒收 salience < 3 的条目，或显式标为「预期不可习得」单独统计。
- `recall.py:38-40` 过滤 `kind == "requirement"`，`style_rule` 永不参与 recall —— 任何被标为改写风格规则的语料条目退出 probe 计分。
- `consolidate.py:38` 触发条件是 `len(active) > 48` **或** `adds_since >= 16`。spec 只押了前者（cp-06 的 49）。`CONSOLIDATE_ADDS = 16` 意味着**在密集引入期 consolidation 会提前触发**，cp-06 未必是「首次在密集 store 上触发」。cp 表要按两个触发条件重算。

---

## 8. 原样继承（不要重写）

| 章节 | 处置 |
|---|---|
| 文首独立复核表（AgentIF / AgentIF-OneDay / WildIFEval / PEP 8 四行） | **逐字继承**。这是一手核验记录，与评测方法学无关 |
| **§1 语料源裁定表（用 / 慎用 / 弃 三张表全部）** | **逐字继承，一个字不改。** 许可裁定不受 owner 这次推翻的任何一条影响，而它是「能不能开源商用」的硬约束。**它现在比原来更承重**：机器管线会大规模摄取，一条许可错在 672 条规模上是全 repo 问题。thin-bucket §1 的两桶裁定表同级继承 |
| §2.1 / §2.2 schema | **继承并扩字段**（`roundtrip`、Layer 2 边、`E-amb` 的 `accept`）。`cid` 空间与产品 hex id 隔离这条设计原样保留 |
| §3.2「gold 不手写，由日志 fold 出来」 | **继承，且是整套东西的支点。** 它本来就是消灭人工标注的机制；新方向只是把它往前推了一层（连日志也由图生成） |
| §3.2 三类 ground truth 可信度分级 | 继承，第 3 类（`effect` 由人判断）改写为「由构造 + round-trip 保证」 |
| §3.2 STATE / BEHAVIOUR 双断言 + revival 不拍板只统计 | **逐字继承**。「只测 STATE 不行」那段论证不受影响 |
| §4.1 三级对齐 + 窄 context judge | 继承。40 对对抗对照集**改为机器生成**（扰动 `distinctive`、换一个 scope 维、改数字——近义反例的正确性是可判定的，因为它按具名字段变异），并且既然免费，规模从 40 对提到几百对 |
| **§4.2 判据作用在改写后的请求上、不是产出的制品上** | **逐字继承。这是整份 spec 最有价值的一处纠错**，把 `max_line_length`/`serial_comma`/IFBench `format:*` 判为范畴错误。新方向完全不触碰它。40% 机械判据的重估同样继承 |
| §4.4 分数定义（`active_f1` / `zombie_rate` / `chain_fidelity` / `S` / `W`） | 继承，加 §3 的 merge chain_fidelity 上限说明、加 §7.1 的双 band 拆分 |
| §4.5 三对照臂 | **继承 + 加第四臂**（见 §4） |
| §4.6 chained / segment / oracle 三模式 | **逐字继承**。`chained − segment` 定位复利、`chained − oracle` 定位习得误差，这套诊断结构不受影响 |
| §4.7 以 scenario 为聚类单位 bootstrap、永不报 checkpoint 级 CI | **逐字继承纪律**；簇数与 DEFF 按最终 scenario 数重算，ρ=0.05 仍是假设不是测量 |
| §6 成本 | 结构继承，数字重算（见下） |
| §7 第 5–13 条 | 见 §3 的表，基本逐字 |
| §8 里程碑 | 重排（N0/N3 不变，N1/N2/N4/N5 改为生成管线里程碑，P7 相关的验收项删除） |
| §9 明确不做的事 | 近乎逐字继承。**两处要重议**：(a)「不做 20 个 scenario」的 12↔20 取舍是按**人时**定价的（「多写 8 个 scenario ≈ 450 条 constraint 的双人复核」），生成变机器之后这条成本曲线变了，应重算不应继承结论；(b)「不删歧义 case」继承且升格 |

---

## 9. 成本与并行（owner 第 4 点）

- **10 workers 是一个 flag**：`run_e2e.py:146` 的 `--workers` 默认 4，`parallel.py:28` 读 `BENCH_WORKERS`。改成 10 本身零成本。
- **但有一个会咬人的具体问题**：`parallel.py:75` 是 `with_retry(lambda: run_one(item), item.id)` —— 重试粒度是**整个 item**。今天一个 item = 一个 persona（16 轮、几十次调用），重跑可以接受。新 E 一个 item = 一个 scenario（~112 事件、约 250 次调用），**第 240 次调用上的一个 429 会把整个 scenario 的花费和墙钟全部作废重来**。而把并发从 4 提到 10 恰恰会抬高 429 率（`retry.py` 的注释明确记着「judge 通道在串行速度下就返回过 429」）。
  **必须做的改动**：把 `with_retry` 下沉到单次 LLM 调用层（`llm.complete` / `judge`），item 级重试只作最后兜底；并把 checkpoint 粒度从 item 降到 checkpoint/event 级。否则「并行化」会净亏。
- **构建期成本从人时变机器调用**：round-trip 标注（~1,350 事件 ×1）+ 反事实对生成与判据鉴别（672 ×3）+ 2AFC 真实性（672 ×1）≈ 4.7k 次额外调用。按 spec §6 的费率假设仍是个位数美元。**结论：钱和人时都不再是约束，绑定约束变成墙钟与 429。** spec 原来「6–8 个工作日人时」这一行作废。

---

## 10. 一页版落地顺序

1. **N0（纯工程，可立刻开工，零语料依赖）**：`gold.py`（含与 `Store.apply_ops` 的**同态** fuzz，覆盖 `AUTO_RETIRE_AT` 路径）、`lint.py`（含新 9a/9b/9c）、`checkers.py` 扩到请求级全套。
2. **N0.5（新增，卡在语料前面）**：Layer 1 标注器 + `conflicts_with` 机械导出 + 图 schema。先把 17 条已落盘的句子跑通全流程，验证管线，再放量。
3. **人力 10 条在这里花**：6 条前置校准（retire/contradict 边界），4 条留给升级通道。
4. **N1**：图→episode 生成器 + round-trip 验证器 + 反事实判据闸；产出第一个 scenario；对 `E-repaired 0.841 / E-chained 0.727` 这个锚点验收。
5. **N2**：四个对照臂（含新增 shuffled-store）+ 陷阱活检自动隔离。
6. **N3**：放量到全部 scenario；许可 lint 与 NOTICE 生成。
7. **N4**：两次全量跑，报 `E-mech` / `E-judge` / `E-crud` / `E-amb` / 四臂 + scenario 聚类 bootstrap CI + 实测 ICC。**此前 E 不产生任何可引用的分数。**
8. **N5**：由 siriux 定权重与阈值，写进 `bench/README.md`。

### 自报风险

- **[high]** 没有机械判据的 60% 断言上，judge 准确率将永久无法测量。原 6×20=120 条分层人工抽检的人力预算是 10。机器替代（自一致性、mech-vs-judge 重叠子集一致率）只覆盖系统性偏易的那一半——数字与禁用词；tone/method/reasoning_policy/task_goal 恰是 MCJudgeBench 警告的类别、恰是两个薄桶、恰是产品差异化所在。既有 29/30 背书是 1–3 规则 context 下拿的，不转移到 49 条 context。
  - 缓解：拆 E-mech / E-judge 双 band：gate 只压 E-mech（无 judge 在环、完全可复现），E-judge 报出但必须并排给出重叠子集上的 mech-vs-judge 一致率作误差条。同时主动把机械判据比例当设计杠杆（选条目、选变异时优先挑机械可判的），但不得把薄桶压没。新增 shuffled-store 对照臂，是唯一能机器捡回的 judge 松紧度检验。承认残余部分不可恢复，不用「LLM 判过了」盖过去。
- **[high]** 生成器的口吻被烤进整个语料：约 250 条 retire 事件出自同一模型。若它写的撤回语句比真人干净，E 就在 retire 上测简单模式——而 retire/contradict 正是 L 今天 0.50 的类别，也是整张生命周期图唯一的承重判断。结果是一个高分但不代表真实就绪度的 bench，正好是 owner 要避免的假信号。
  - 缓解：三条：(1) 用 PRISM open_feedback（CC BY 4.0，§1 已裁定可用）的真实撤回语句做改写锚，要求 paraphrase 不要 invent；(2) 对 retire/contradict 族的 round-trip 分歧率设下限而非上限——分歧率过低是过度清洁的证据；(3) 6 条人工校准全投在 retire vs contradict 边界，给这个下限一个粗刻度。诚实记录：真实分歧率无测量值，该缓解目前有方向无刻度。
- **[high]** spec 的 lint 规则 1 只要求 must_carry 的 cid「active 且 scope 相容」，未考虑 RECALL_CAP=32；而 spec 自己的 cp 表在 cp-05/cp-06 分别是 42/49 active。cp-04 起 must_carry 可合法包含 recall() 永不返回的条目，E 的天花板被机械压到 1.0 以下，分数无法解释成系统错误。
  - 缓解：把 activation 显式拆成 validity+scope（图导出，是 gold）与 cap 内选择（产品策略，不是 ground truth）。两条出路择一并写明是决定：(i) lint 直接调真 recall() 生成 must_carry——干净但把 gold 绑死当前实现，本身是过拟合；(ii) gold 只声明 validity+scope，分数拆 carry@valid 与 carry@cap 分开报。倾向 (ii)。
- **[medium]** suite 名沿用 E 而语义完全改变，config.py 与 results/ 里有多处会静默误读：WEIGHTS["E"]=0.3、GATE_PER_SUITE=0.70 按 v1 E 语义定、bench/results/ 下 8 份旧 E 快照与新快照共处一个命名空间。新 E 必然先掉到 0.667 以下（3 条规则的 store 换成 49 条 active），旧阈值会把它读成灾难性回归。
  - 缓解：write_snapshot 加 metric_version，report.py 对 version 不匹配的快照拒绝计入 gate 而非按老阈值静默判定；8 份旧 E 快照移入 bench/results/archive/；沿用 spec §0「前两次全量跑不设 gate」；权重改 T .25 / L .25 / E .50，首版 gate 压 E-mech。另外 E2E_PERSONA_COUNT=8 是 run_e2e.py:151 的硬 error，会直接挡住第一次运行，必须先改。
- **[medium]** gold 状态机用 {active, invalidated}+四种 reason，产品 schema.py:16 是 STATUSES=("active","retired") 二值（taxonomy-verdict §4.3 明确拒绝 7 值方案）。按字面写「状态相等」的 fuzz 测试要么恒红，要么诱导有人给产品加字段——而那正是 §9 明令禁止的「不因 bench 而改产品 schema」。两台状态机一旦漂移，suite 里每个数字都错且任何 judge 都发现不了。
  - 缓解：写成同态而非同一：把 gold 的 invalidated/* 投影为 retired 后断言相等，reason 与继任指针另行对照产品的 supersedes。fuzz 必须覆盖 store.py:17 AUTO_RETIRE_AT=-2 这条 gold 日志里没有对应事件的第二条 retire 路径。chain_fidelity 对 merge 只能校验 targets[0]（store.py:141-148 只设一个 supersedes 指针），这个上限写进分数定义。
- **[medium]** parallel.py:75 的 with_retry 粒度是整个 item。今天一个 item=一个 persona（几十次调用）尚可，新 E 一个 item=一个 scenario（~250 次调用），第 240 次调用上的一个 429 会作废整个 scenario 的花费与墙钟。而 owner 要的「并发提到 10」恰恰抬高 429 率（retry.py 注释记着 judge 通道在串行速度下就返回过 429）。直接提并发会净亏。
  - 缓解：把 with_retry 下沉到单次 LLM 调用层（llm.complete / judge），item 级重试只作最后兜底；checkpoint 粒度从 item 降到 checkpoint/event 级。改完再提 workers 到 10。
- **[medium]** 反事实判据闸的违规样例由同一个模型生成，判据若只咬一个表面 token，生成的违规样例大概率也刚好缺那个 token 从而「通过」检验。在有机械判据的 40% 上还有 mech 作外部校验，在没有的 60% 上完全没有外部校验——即判据自证。
  - 缓解：违规样例必须由另一条 prompt 生成，要求「违反该 constraint 但保留其表面词汇」（hard negative）。配合 shuffled-store 臂与 null 臂的逐 probe 活检。残余风险明确记录在 E-judge band 的说明里，不并入 headline。
- **[medium]** 语料级真实性（checklist 第 1 条「每条都能想象成真人真的说过」）无法自证。2AFC 判别器能证明单句不可辨为合成，但对分布级错误完全盲——672 条每句都像真的、但这一组偏好不像真实用户群，判别器测不出来；10 条人工也看不出分布。
  - 缓解：跑 thin-bucket G1（抓手闸）/G4（第一人称闸）两个 boolean 闸 + self-instruct 175 条种子做风格锚 + 2AFC 判别器对 PRISM 真实文本。明确在发布材料里声明这三者证明的是「单句不可辨为合成」而非「真有用户持有这条偏好」，不做更强主张。
- **[medium]** 语料实际存量远低于文档给人的印象：bench/gen/harvest/ 不存在，仓库里零 harvest jsonl。thin-bucket 自述的 189 条只有 17 句落盘，四个胖桶（~500 条）从未开工。「预算 770 / 实需 672 / 余量 15%」是计划表不是库存。按文档排期会低估 L1 的工作量。
  - 缓解：N0.5 先用已落盘的 17 句把 Layer 1 标注→冲突导出→episode 生成→round-trip 验证全流程跑通，再放量；把 L1 采集单列为一个里程碑并按零存量估工，不按「已提取 189 条」估。
- **[low]** consolidate.py:38 的触发条件是 len(active) > 48 或 adds_since >= CONSOLIDATE_ADDS(16)，spec 的 cp 表只押了前者（cp-06 的 49 active）。密集引入期第二个条件会先触发，cp-06 未必是「consolidation 首次在密集 store 上触发」，整张 checkpoint 设计意图落空。
  - 缓解：按两个触发条件重算 cp 表的 after_seq 与累计引入数，并在 lint 里断言每个 cp 的意图（首次越 RECALL_CAP、首次越 CONSOLIDATE_ACTIVE）确实成立，而不是靠表里写的注释。同时 lint 拒收 salience<3 的 catalogue 条目（extraction.py:157 会丢弃，必然记 miss），kind=style_rule 的条目退出 probe 计分（recall.py:38-40 永不召回）。

### 未决问题

- 10 条人力怎么分：我建议 6 条前置校准（全投 retire vs contradict 边界）+ 4 条按图的度数排序的升级通道，但 owner 原话是 (a)/(b) 二选一。要不要接受分割？（纯 (b) 的问题是 672 条上 5% 分歧就是 34 条，天然超预算 3 倍，必须有排序规则才落得了地。）
- activation 的 cap 那一层怎么算：(i) lint 直接调真 recall() 生成 must_carry（分数干净但把 gold 绑死当前实现，本身是一种过拟合），还是 (ii) gold 只声明 validity+scope、carry@valid 与 carry@cap 分开报（我倾向这个）？headline 用哪个数？
- 首版 gate 压 E-mech 还是压 E 全量？压 E-mech 意味着 gate 与「产品差异化所在的两个薄桶」几乎不相关；压全量意味着 gate 建立在一个准确率无法测量的 judge 上。这个取舍我没法替 owner 决定。
- scenario 数还定 12 吗？spec 的 12↔20 取舍（CI 半宽 ±0.057→±0.044 不值 450 条双人复核）是按人时定价的。生成变机器之后成本曲线变了，20 个 scenario 的边际成本主要是墙钟。要不要重算？
- E-amb band 里的条目算不算进 headline 的分母？spec 说单独成 band 不进 headline，但当 round-trip 分歧率本身成了「语料够不够真实」的指标时，把它们排除在外会让 headline 系统性偏乐观。
- 旧的 8 个 persona 文件保留为独立冒烟 suite（我建议叫 E0 或 smoke，别叫 E-legacy）之后，还进不进 CI 的 commit hook？它今天是唯一能在 8 分钟内跑完的端到端检查。
- round-trip 标注器用哪个模型？用同一个 DeepSeek 会让两次调用高度相关，round-trip 通过率虚高；换一个模型族（judge 现在是 deepseek-v4-pro，生成侧若也是 DeepSeek）能提供更强的独立性证据，但要多一条 API 通道。这笔账值不值？
- thin-bucket §2.3 里那 6 个「待核验」的新源（medlineplus / gao_yellow_book / nist / openstax / govuk_service_manual / ftc）要不要在这一轮补核？它们是 scenario 覆盖偏斜（现有语料集中在 research/code/journalism/stats 四个域）的主要解药，但每个都要走完整的 primary-artefact 核验流程。

---

## 设计 4：Suite E 672 规模 runner 设计：shard 化并行、事件级 resume、双通道并发与成本/墙钟预算

## 0. 先给结论

| 问题 | 答案 |
|---|---|
| 并行单元 | **shard = (episode, mode, window, repeat)**；12 episode 下共 408 个 shard，最长的一个 114s |
| resume 粒度 | **事件级，零重跑**——靠 `Store` 自带的 append-only JSONL 复原，不是 per-episode |
| 并发天花板 | **judge 通道（Ark）是唯一被实测过的天花板**；产品通道（本机 Anthropic 代理）受的是可用性不是速率限制。两个池、两个 governor |
| 成本 | haiku **2,448 次 / $9.05**（按今天 $0.85 校准，K=1.21）；judge ~9,800 次 / ~$1.15（**费率未核**，5 倍也才 $5.7）。全量一次 **~$10** |
| 墙钟 | product=8 / judge=6、pipelined、25% judge cache 命中 → **~54 分钟**。今天的 4/4 设定要 108 分钟 |
| report.py | `category_rates` 现在只有一个桶，等于把 suite 分打印两遍。改 micro/macro 双读数 + 密度分层 + 塌陷闸门 |

数字出处分三档，下文逐处标注：**实测**（本仓库跑出来或代码里读出来的）／**建模**（按结构推的）／**假设未核**。

---

## 1. 并行单元

### 1.1 今天为什么只能按 persona 并行

`run_e2e.py:96-101` 里有一条从 judge 通道回流进产品通道的运行时依赖：

```python
ok, _flag = _carries(persona["requirements"][i], polished)   # judge 调用
...
if not hit:                                                   # judge 的判决
    pending.append({...})                                     # 决定 store 怎么演化
```

judge 判 miss → 追加纠正信号 → 影响 extraction → 影响 store。所以一个 worker 必须同时持有两个通道，384 次 translate 和 666 次 judge 在同一根线程里串起来。这是今天 workers=4 只能是一个数字（而不是两个）的根本原因。

### 1.2 新设计里这条依赖被 spec 自己消掉了

不是我提的优化，是 §2.2 + §3.2 蕴含的结果：event log 是**作者写定**的（`surface.signal` 是脚本，不是反应），gold 由 fold 导出且"构造性为真"。如果纠正信号仍由运行时 judge 判决触发，gold 就不能离线 fold —— 整套 `gold.py` 的设计基础就没了。

所以：**纠正信号必须是脚本化的，judge 必须退出 store 循环。** 后果是两阶段：

- **Phase 1（产品路径，haiku on Anthropic）**：重放 event，只产出 transcript —— `{probe_id: rewritten_request}` + `{cp: store snapshot}`。零 judge。
- **Phase 2（评判路径，DeepSeek on Ark）**：对 transcript 打分。机械判据（`checkers.py`、`preserves_request_ratio`、`must_not_carry` 的 `not_contains`）也在这一阶段，先跑，机械闸门不过的 probe 直接记 0 并**跳过它的全部 judge 调用**。

附带能力（值得单列，因为 672 条 criterion 一定会改）：transcript 落盘后，`bench/runner/regrade.py <run_id>` 可以在**零 haiku 成本**下用改过的 `judge_criterion` / 修好的 checker 重新打分。今天改一个判据要重跑 $9 + 16 分钟的产品路径。

### 1.3 shard 定义与排序约束

```
shard = (episode, mode, window, repeat)

mode=chained : window = 整条 episode（1 个），112 事件严格有序
mode=segment : window = (prev_cp, cp] 共 8 个，各自注入 gold_state(prev_cp)
mode=oracle  : window = 单个 cp 共 8 个，注入 gold_state(cp)，只跑 probe
```

必须尊重的排序约束，只有一条：**shard 内部严格串行**，因为 `Store` 状态在演化。

不存在的约束（要说清楚，因为这是并行度的来源）：

- shard 之间零共享状态——每个 shard 拥有**私有的 `Store` 文件路径**，不是今天的进程内 `list[Requirement]`。
- segment / oracle 需要的 `gold_state(cp)` 是**计划期**算出来的纯 fold（零 LLM），不是运行时依赖。
- repeat 之间独立（`GEN_TEMPERATURE=0.0` 下可能逐字相同，这一点由 §4.4 的 cache 命中率去**实测**，不预设）。
- **chained 内部不可再分。** 把 chained 按 checkpoint 切开，得到的定义上就是 segment。chained − segment 正是"复利误差"这个量，所以 gate 指标的墙钟下界就是一条 chained episode = 114s（建模），没有配置能突破。

12 episode × repeat=2：

| mode | shard 数 | 每 shard 调用数 | 每 shard 秒数（建模） |
|---|---|---|---|
| chained | 24 | 39 | 114 |
| segment | 192 | ~5 | ~15 |
| oracle | 192 | 3 | ~6 |
| 合计 | **408** | 2,448 | product 6,600s |

owner 那句"20 tasks, max-worker=10, ten at a time"精确对应 chained 层：24 个 chained shard、10 workers、约 3 波、每波 2 分钟 ≈ 6 分钟走完最长的那一层。

### 1.4 调度：必须 LPT，不能按文件序

408 个任务里 24 个比其余长 8–20 倍。`pool.map(one, todo)` 按提交序发，todo 是 `sorted(glob)` 的文件序，chained shard 有可能排在最后 → 尾部只剩 1 个 worker 在跑、9 个空转。改动很小：

```python
def run_items(suite, items, run_one, *, workers, resume=True,
              weight=lambda it: 1.0):          # 新增
    ...
    todo.sort(key=weight, reverse=True)        # LPT：长任务先入池
```

`weight` 由计划器给：chained=112、segment=14、oracle=3（事件数即可，不需要真实秒数）。

---

## 2. Checkpoint / resume

### 2.1 三层，不是一层

| 层 | 单位 | 文件 | 作用 |
|---|---|---|---|
| A · run 身份 | 整次运行 | `bench/.run/<run_id>/` | `run_id = sha256(cases_hash + git_sha + provider + modes + repeat)` |
| B · 结果 | shard | `<run_id>/results.jsonl` | 今天 `Checkpoint` 的语义，只是 id 变细：`e-07/chained/-/r1`、`e-07/segment/cp-05/r2` |
| C · shard 内 | 事件 | `<run_id>/shards/e-07.chained.r1.{store,journal}.jsonl` | 只 chained 需要 |

**run_id 进路径这一条是必须的。** 今天 `run_items` 只按 `item.id` 判重，改了一个 persona 文件再跑，会静默地把两个版本 case 的结果混在一份 snapshot 里。8 个 persona 你能看出来，408 个 shard 看不出来。

### 2.2 chained shard 的 resume 是零重跑的

关键在于 `store.py` 已经把这件事做完了：`_append` 每次追加完整记录、`from_dict` 保留 `created_at`（`recall()` 正是按它排序的）。所以：

```python
def run_chained(shard):
    store = Store(shard.store_path)                    # 自动复原到上次落库状态
    journal = Journal(shard.journal_path)              # 每事件一行
    start = journal.last_seq + 1                       # 无 journal 则 0
    pending = journal.pending_buffer()                 # 作者写定的信号，可重建
    for ev in shard.events[start:]:
        ...
        journal.append({"seq": ev.seq, "kind": ..., "probe_out": ...})
```

- **journal 每事件一行**（~1KB × 112 行，可忽略），所以恢复代价是 **0 次 LLM 调用**，不是"回退到上一个 flush 边界再重跑 ≤8 次"。既然写一行这么便宜，就没有理由只在 flush 边界写。
- **半完成的 episode 绝不出分。** 它在 B 层不存在（B 层只在 shard 完整结束时写一行），所以聚合看不到它。
- 落盘顺序：先 `store` 追加（产品自己做），再 `journal` 追加。崩在两者之间 → 恢复时 journal 少一行、store 多一次 apply，重放该事件会重复 apply。用 journal 行里的 `store_line_count` 做幂等断言，不一致就把该 shard 标 dirty 重跑（丢一个 shard 而不是丢一个数字）。
- segment / oracle shard **不做 C 层**：≤14 事件 / ≤5 次调用，整块重跑比维护 journal 便宜。

### 2.3 环境硬事实：scratch 不能放 iCloud

仓库在 `~/Library/Mobile Documents/`。408 个 shard × 2 个文件 = 816 个高频追加的小文件放进 iCloud 同步目录，是在自找麻烦——`bench/runner/config.py:40` 的注释已经记了一次"iCloud can transiently hide a file"。

`bench/.run/` 必须落在 `$TMPDIR`（或 repo 内 `.gitignore` 且用 `xattr -w com.apple.fileprovider.ignore#P 1` 排除同步），只有最终 snapshot 和 transcript 回写仓库。

### 2.4 完整性断言（替代今天的 `E2E_PERSONA_COUNT`）

今天那道 guard 只挡"iCloud 藏了个文件"，挡不住"某个 shard 中途永久失败、run 继续、snapshot 拿 400/408 当完整套件出分"。

```python
snap["expected_shards"] = plan.n_shards
snap["completed_shards"] = len(results)
if snap["completed_shards"] != snap["expected_shards"]:
    snap["score"] = None
    snap["headline_valid"] = False
    snap["missing"] = sorted(plan.ids - done_ids)
    sys.exit(2)
```

---

## 3. 并发天花板

### 3.1 两条通道，限制来源完全不同

| | 产品路径 | 评判路径 |
|---|---|---|
| 模型 | `claude-haiku-4-5` | `deepseek-v4-pro` |
| 客户端 | `llm.py::_client`，单个 `anthropic.Anthropic()` | `judge.py::_client`，单个 `httpx.Client(timeout=120)` |
| 客户端侧上限 | Anthropic SDK 默认连接池远高于我们的量级，不是瓶颈 | httpx 默认 `max_connections=100 / keepalive=20`，20 以下不是瓶颈 |
| **真实约束** | **本机代理的可用性**——`llm.py:5`、`retry.py:4` 都记了它"一次掉一两分钟"。这是可用性问题，不是速率问题 | **实测的 429**——`parallel.py:15` 原话：judge 通道在**串行速度下**就返回过 429。这是本系统里唯一被测量过的天花板 |
| 建议 | `--product-workers 8`（4→8→12 按重试率爬） | `--judge-workers 6` + token bucket 限速 |

今天 workers=4 之所以能成立，是因为 judge 占了调用量的 2/3（666 vs 432 实测），4 个 worker 实际只对 Ark 维持了 ~2.7 并发。**"4 曾经崩过"是 backoff 重写前的事，重写后 4 是被证过的；6 以上是外推，必须靠这次 run 自己的遥测回填，不能拍。**

### 3.2 两个必改的地方

**(a) retry 必须从 item 级下沉到 call 级。**

`parallel.py:75` 是 `with_retry(lambda: run_one(item), item.id)` —— 整个 item 包在重试里。今天一个 persona ~50 次调用，代价还能忍。一个 chained shard 39 次调用，单次调用失败率 p 时，整 shard 被重跑的概率是 `1-(1-p)^39`：

| p | shard 重跑概率 |
|---|---|
| 0.005 | 18% |
| 0.02 | **54%** |

即最后一次 judge 撞 429，前面 38 次 haiku 白付。**把 `with_retry` 放进 `llm.complete()` 和 `judge()` 内部**，`run_items` 不再包 item——shard 失败就落进 journal，靠 §2.2 恢复。

**(b) 429 要全局降速，不能只降失败的那一路。**

`retry.py` 是 per-call backoff，没有跨 worker 协调。一个 429 只让 1/W 的负载退让：W=4 时退让 25%，W=10 时退让 10%——**这个机制的有效性随并发上升而下降，方向是反的**。

而且 worker 数本身就是错误的速率旋钮：服务端限的是 rate，worker 数控的是 concurrency，`rate = W / latency`。通道变慢（正是接近限额时的表现）你的 offered rate 自动下降，通道恢复你又尖峰上去——控制环反了。

```python
# bench/runner/ratelimit.py  —— judge 通道专用
class Governor:                       # token bucket + AIMD
    def __init__(self, rate=3.0, burst=6, floor=0.5, ceil=8.0): ...
    def acquire(self): ...            # 每次 judge 调用前
    def on_429(self):  self.rate = max(self.floor, self.rate / 2)
    def on_clean_window(self):        # 连续 60s 无 429
        self.rate = min(self.ceil, self.rate + 0.25)
```

产品通道不需要 governor（限制是可用性），但需要一个**熔断**：连续 N 次 `LLMUnavailable("connection")` 时暂停整个 product 池而不是让 8 个 worker 各自 backoff——代理掉线时它们本来也做不了事，全停能让 judge 池独占带宽把积压清掉。

### 3.3 心跳（不是可选项）

`MAX_ATTEMPTS=7` + `MAX_DELAY=240` 意味着单次调用最坏能沉默 4 分钟；代理掉线时 8 个 worker 一起沉默。owner 的明确口径是"静默超过几分钟就当你死了"，而且这个项目真出过后台任务静默挂 33 分钟。

```
[t+12:30] shards 187/408 | running=8 queued=213 | product 8w  judge 6w R=2.5/s
          429×3  proxy-drop×1  parse-flag 0.4%  | ETA 41min
```
30 秒一行，写 stdout 也写 `<run_id>/heartbeat.log`。

---

## 4. 成本与墙钟

### 4.1 实测输入

| 项 | 值 | 来源 |
|---|---|---|
| `TRANSLATOR_SYSTEM` | **2,813 字符** | 实测，与题面一致 |
| `EXTRACTION_SYSTEM` | **5,815 字符** | 实测。**题面给的 5,228 对不上，差 11%**，本模型按实测值算 |
| `CONSOLIDATE` system | 945 字符 | 实测 |
| `JUDGE_SYSTEM` | 316 字符 | 实测 |
| 今天全量 E | 432 次 haiku（384 translate + ~48 extraction），$0.85 | 实测 |
| haiku-4-5 | $1 / $5 per MTok | 题面给定 |
| DeepSeek-v4-pro on Ark | — | **未核实**，沿用旧 spec 的 $0.3/$1.2 假设 |

token 换算按 3.7 字符/token（英文技术散文 + JSON）。

### 4.2 校准

用同一套公式反算今天这一跑：$0.70（建模）vs $0.85（实测）→ **校准因子 K = 1.21**。下面所有 haiku 金额都乘了 K。这是单点校准，不是拟合。

### 4.3 SUT（haiku-4-5），12 episode × 112 事件 × 56 constraint × 8 cp × 3 probe

每 pass 调用数：extraction 11（~85 signal / `BATCH_N=8`）、consolidate 4（56 adds / `CONSOLIDATE_ADDS=16`）、translate 24（8 cp × 3 probe）。

| mode | passes | 调用 | 金额 |
|---|---|---|---|
| chained ×2 | 24 | 936 | $3.73 |
| segment ×2 | 24 | 936 | $3.73 |
| oracle ×2 | 24 | 576 | $1.60 |
| **合计** | | **2,448** | **$9.05** |

单次调用 $0.0037，是今天 $0.0020 的 **1.9×**。这个倍数完全来自两处产品常量，不是猜的：translate 的 prompt 里挂了 `RECALL_CAP=32` 条召回（今天 3 条），extraction 的 prompt 里挂了最多 56 行编号 index（今天 3 行，`INDEX_ROW_TOKENS=20`）。

### 4.4 judge（DeepSeek on Ark）

| 用途 | 次数 | 口径 |
|---|---|---|
| 对齐（第 3 级窄二元） | 4,608 | 只 chained+segment 需要（oracle 注入完美 store）；48 passes × 8 cp × ~40 条 active × **30% 机械未决** |
| must_carry 语义 | 5,184 | 72 passes × 24 probe × 3.0（机械闸门后剩下的） |
| **合计** | **9,792** | in 2.64M / out 0.29M |

金额：**$1.15（假设费率）／$5.73（5 倍）**。

**全量一次 ≈ $10.2，最坏 $15。钱不是约束。**

冒烟档（3 episode × chained ×1，state 只判 cp-04/cp-08）：~120 haiku + ~500 judge ≈ **$0.6 / ~7 分钟**，可以挂 commit。

### 4.5 墙钟：judge 是瓶颈，差 3 倍

延迟是**假设**（haiku extraction 4.5s / consolidate 4.0s / translate 2.0s；judge 2.0s），第一次全量跑必须实测回填。

```
串行秒数：  product 6,600s (110 min)   judge 19,584s (326 min)
最长单 shard（一条 chained episode，judge 已解耦）：114s = 1.9 min
```

| product / judge | cache 命中 | product | judge | **pipelined** | 两阶段 |
|---|---|---|---|---|---|
| 4 / 4（今天的设定） | 0% | 32min | 96min | ~108min | 128min |
| **8 / 6（建议）** | **25%** | 16min | 48min | **~54min** | 64min |
| 8 / 6 | 0% | 16min | 64min | ~72min | 80min |
| 10 / 10（Ark 允许的话） | 25% | 13min | 29min | ~32min | 42min |

**建议配置：`--product-workers 8 --judge-workers 6`，pipelined，约 54 分钟。**
pipelined = shard 的 phase 1 一完成立刻把它的判据推进 judge 队列，两个池同时在跑，不是先跑完全部重放再打分。

**judge cache（免费，且顺带出一个真结论）。** 判据是 `temperature=0`，产品路径也是 `GEN_TEMPERATURE=0.0`，所以 `(criterion, context)` 完全决定结果。按 `sha256(judge_model + criterion + canonical_json(context))` 做内容寻址缓存，oracle 模式的第二次 repeat 几乎全命中。

但要说清楚代价：**如果 repeat 2 全部命中，repeat 2 也就什么都没测到。** 这不是缓存的锅——如果 SUT 输出逐字相同，那次 repeat 本来就零信息量，缓存只是把这件事**显式化**了。所以命中率要作为一等公民报出来：某个 mode 命中率 100% = 该 mode 无 run-to-run 方差、repeat=1 就够。默认**只在 run 内缓存**；跨 run 复用要显式 `--judge-cache-across-runs`，且 key 里加 SUT git sha + cases_hash。

### 4.6 最高杠杆的优化不是加并发，是加机械判据

judge 侧串行秒数是产品侧的 3 倍（326 vs 110 分钟）。**每省一次 judge 调用 = 省 2 秒瓶颈资源。**

把机械对齐覆盖率从 70% 推到 85%（`distinctive` 是刻意种下的变异数字/自造词，本来就是给 grep 用的），对齐调用 4,608 → 2,304，省 77 分钟串行、在 6 worker 下省 ~13 分钟墙钟。这是零 LLM 的工程，比争取 Ark 多给两个并发靠谱得多。

---

## 5. report.py：mean-of-means 必须改

### 5.1 今天到底发生了什么（用本仓库的实测数字）

`category_rates` 按 `r["category"]` 分桶，而所有 persona 的 category 都是 `"persona"` —— **只有一个桶**。所以 `suite_score` = 8 个 persona 均值的均值，打印出来的那行 `persona 0.67` 就是 suite 分本身，一行冗余。

三次 run 的实测（second-half 判断点密度：minimalist 24 / student 24 / pm 16 / researcher 12 / writer 12 / datasci 8 / dev 8 / mixed 8，共 112）：

| run | macro（今天的分） | **micro（按判断点加权）** | micro − macro |
|---|---|---|---|
| 13:38 | 0.788 | 0.842 | **+0.054** |
| 20:31 | 0.693 | 0.744 | **+0.051** |
| 21:33 | 0.667 | 0.661 | **−0.006** |

20:31 → 21:33 这一步：

- macro 动了 **−0.026**（读起来像噪声，不会有人去查）
- micro 动了 **−0.083**，是 macro 的 **3.2 倍**
- 底下真实发生的是 `minimalist-zh` **0.708 → 0.194**，塌了 0.514，折合 **12.3 个判断点**
- 而 `minimalist-zh` 承担 **21% 的证据量**（24/112），在 macro 里只占 **12.5% 权重**

**mean-of-means 不只是掩盖了塌陷，它主动地给证据最多的那条 episode 降权。** 而 `micro − macro` 的符号翻转（+0.054 → +0.051 → −0.006）正好指出"你的高密度 episode 是不是在扛分"，这是免费拿到的诊断量。

再看统计功效（Wilson 95% 半宽，p=0.75）：单个 persona n=8 → **±0.260**，比整个 gate 带还宽；suite n=112 → ±0.079。新设计下 ~5,000 条断言朴素 ±0.012，但按 episode 聚类有效样本只有 12，**必须报聚类 bootstrap，绝不报朴素区间**。

### 5.2 具体改动

**(1) `suite_score` 返回结构体，headline = `min(micro, macro)`**

```python
def suite_score(results) -> dict:
    pts   = sum(r["points"] for r in results)          # 新增：每个 shard 记判断点数
    micro = sum(r["carried"] for r in results) / pts   # 按判断点加权
    macro = mean(episode_mean(e) for e in episodes)    # 今天的算法，保留为诊断
    return {"headline": min(micro, macro), "micro": micro, "macro": macro,
            "gap": micro - macro, "per_repeat": [...], "points": pts}
```

取 `min` 而不是二选一：micro 让 60 点的 episode 一家独大，macro 抵消掉密集 episode 的塌陷（上面实测过）。`min` 两个方向都不好刷，且不需要凭空定权重。

**(2) 密度夹逼进 lint**，每条 episode 的计分点落在均值 ±20%（今天是 8–24，3 倍差）。夹住之后 micro ≈ macro 是构造性的，`gap` 就变成纯诊断量。

**(3) `category_rates` → `strata_rates(results, by=...)`**，每层返回 `(rate, n, wilson_lo, wilson_hi)`，分层维度：`mode` / `bucket`（产品自己的六桶——这套件声称要证明的就是这个）/ `facet_family`（6）/ `effect.op`（new·reinforce·contradict·retire·merge）/ `episode`。这才是能据以排工程优先级的数，今天那一行不是。

**(4) 塌陷闸门，是 gate 不是 print**

```python
REGRESSION_DROP = 0.25
for e in episodes:
    if prev and prev[e] - cur[e] >= REGRESSION_DROP:
        snap["headline_valid"] = False
        snap["regressions"].append({"episode": e, "from": prev[e], "to": cur[e],
                                    "points": n_points[e]})
```
拿今天的数据回测：20:31 会因 `writer-zh −0.472` 触发，21:33 会因 `minimalist-zh −0.514` 触发。**两次 macro 均值都没报警。**

**(5) suite 级 spread。** 今天 `spread` 只存在于 per-persona 字段里（`writer-zh` 出现过 **1.0**，即三次 repeat 分别是 1.0 / 0.0 / 0.333，没人看见）。按 repeat index 独立算 suite 分再报 min/max/SD——实测三次 run 的 per-repeat suite spread 是 0.047 / 0.094 / 0.052。

**(6) 聚类 bootstrap CI**，episode 为簇、10k 次重采样，打印进 headline 行：`E 0.667 ±0.071 (12 clusters, ICC=0.0x)`。两次 run 的 CI 重叠时**拒绝**输出"回归/改进"字样。

**(7) judge 健康度分层。** 今天 `judge_parse_flags` 是一个整数。9,800 次调用下 2% 的 parse flag = 196 个 fail-closed 的"no"，全部计为 miss、直接压低分数。按 facet_family / bucket 报 flag 率，任一层 > 1% → `headline_valid: false`。

**(8) 三条对照臂进 snapshot 头部**，不是另一份文档：`null_dump_suppress_delta`、`flat_dump_delta`、`oracle_ceiling`。§4.5 说 null-dump 差值 < 0.05 就作废本次 run —— 这条只有写进 snapshot 才会被执行。

**(9) 一个现成的 bug：`write_snapshot` 的 case_hash 用 `p.glob("*.json")`（非递归）。** episode 一旦落进 `bench/cases/episodes/e-01/*.json` 这样的子目录，hash 会静默变成空摘要，每份 snapshot 都声称同一个 `cases_hash`，"这一跑用的是哪版 case"就永久丢失了。改 `sorted(p.rglob("*.json"))` 并把相对路径一起喂进 hash。

**(10) 另一个现成的保真度缺口：`run_e2e.py:55-67` 的 `_apply_ops` 是 `Store.apply_ops` 的重写版**，缺 `merge` 分支、不写 `supersedes`、不带 key/scope/salience/bucket。3 条规则时无所谓；新 E 里 `chain_fidelity` 直接打 `supersedes` 指针、merge 是配额内的计分失效原因——用这个简化状态机等于**在一个产品并不存在的 store 上给产品打分**。runner 必须直接用 `memtranslator.store.Store`（顺带把 §2.2 的免费 resume 也拿到）。

---

## 6. 落地文件清单

| 文件 | 动作 |
|---|---|
| `bench/runner/schedule.py` | 新增。episode → shard 计划器，出 `weight`、`expected_shards`、`run_id` |
| `bench/runner/run_episodes.py` | 新增。两阶段两池 pipelined 驱动，取代 `run_e2e.py` 在 gate 上的位置 |
| `bench/runner/journal.py` | 新增。C 层事件日志 + 幂等断言 |
| `bench/runner/ratelimit.py` | 新增。judge 通道 token bucket + AIMD |
| `bench/runner/judgecache.py` | 新增。内容寻址，报命中率 |
| `bench/runner/regrade.py` | 新增。零 haiku 成本重打分 |
| `bench/runner/parallel.py` | 改。`weight` + LPT 排序；去掉 item 级 `with_retry`；`run_id` 进 checkpoint 路径 |
| `bench/runner/retry.py` | 改。下沉到 call 级，接入 governor |
| `src/memtranslator/llm.py` | 改。`complete()` 内部包 retry |
| `bench/runner/judge.py` | 改。内部包 retry + governor + cache |
| `bench/runner/report.py` | 改。§5 全部九条 |
| `bench/runner/checkers.py` | 扩。`regex_present/absent`、`preserves_request_ratio`、`numeral_present` |
| `bench/runner/config.py` | 改。`PRODUCT_WORKERS` / `JUDGE_WORKERS` 分开；`E2E_PERSONA_COUNT` → `expected_shards` |
| `bench/replay/gold.py` · `lint.py` | 新增，按原 spec §3.2 / §8-N0，另加密度夹逼 lint |


### 自报风险

- **[high]** retry 停留在 item 级：一个 chained shard 39 次调用，单次失败率 2% 时有 54% 的概率整条被重跑，前面 38 次 haiku 白付。这是当前代码的实际行为（parallel.py:75 把整个 run_one 包在 with_retry 里），不是假想。
  - 缓解：把 with_retry 下沉进 llm.complete() 和 judge() 内部，run_items 不再包 item；shard 失败落进 journal，靠事件级 resume 恢复。
- **[high]** judge 通道（Ark）在串行速度下就返回过 429（parallel.py 自己记的）。建议的 6 worker 是从被证过的 4 外推来的，可能一上量就崩。而且当前 retry 只让失败的那一路退让，W=10 时只退让 10%——降速机制的有效性随并发上升反而下降。
  - 缓解：token bucket 显式控速（rate 而非 worker 数）+ AIMD：429 时全局把 rate 减半、连续 60s 干净再加回来。首跑按 4→6→8 爬并把每档的 429 率写进 snapshot，下一跑的设定由实测定，不拍。
- **[high]** 672 条 constraint 的 gold 只有 10 个人工标注项兜底，其余由 DeepSeek 标。系统性标错某一类 op（最可能是 retire/contradict 的边界，L 的 revoke 今天就卡在 0.50）会被 5,000 条断言的紧凑 CI 包装成一个看起来很精确的错数。
  - 缓解：runner 侧能做的是让偏差可见而不是被均值稀释：按 effect.op 和 bucket 分层出分、报每层 n 与 Wilson 区间，某一 op 家族系统性偏低会显示为跨 episode 一致的层内异常；ambiguous band 单独成表不进 headline；三条对照臂进 snapshot 头部并让 null-dump 差值 <0.05 直接作废本次 run。
- **[high]** run_e2e.py 的 _apply_ops 是 Store.apply_ops 的简化重写（无 merge 分支、不写 supersedes）。新 E 直接给 chain_fidelity 和 merge 打分，沿用它等于在一个产品并不存在的 store 上给产品打分。
  - 缓解：runner 改用 memtranslator.store.Store 本体（每 shard 一个私有路径），顺带拿到免费的事件级 resume；再补 spec N0 的 gold.py ↔ Store.apply_ops fuzz 等价测试钉死两个状态机。
- **[medium]** judge cache 让第二次 repeat 几乎全命中，于是 repeat 变便宜的同时也不再测量任何方差——而 repeat 存在的唯一理由就是测方差。
  - 缓解：把 cache 命中率作为一等结果报出（某 mode 100% 命中 = 该 mode 零方差、repeat=1 即可，这本身是结论）。默认只在 run 内缓存；跨 run 复用需显式开关且 key 里带 SUT git sha + cases_hash。
- **[medium]** micro 作为 headline 会让判断点最多的 episode 主导；macro 会抵消密集 episode 的塌陷（本仓库实测：minimalist-zh 塌 0.514、占 21% 证据量，macro 只动了 0.026）。任一单独用都能被刷。
  - 缓解：headline = min(micro, macro)，两个都打印，gap 作为密度倾斜诊断；同时在 lint 里夹逼每条 episode 的计分点到均值 ±20%，让两者构造性接近。
- **[medium]** 408 个 shard × 2 个高频追加的小文件放在 iCloud 同步目录下（仓库位于 ~/Library/Mobile Documents/），bench/runner/config.py 已经记过一次 iCloud 静默藏文件。
  - 缓解：bench/.run/<run_id>/ 落 $TMPDIR，只有最终 snapshot 与 transcript 回写仓库；这条同时写进项目 CLAUDE.md，不要第二次踩。
- **[medium]** 墙钟模型里的全部延迟（haiku 4.5/4.0/2.0s、judge 2.0s）是假设，一次也没实测；DeepSeek-v4-pro 在 Ark 上的费率同样未核实（沿用旧 spec 的 $0.3/$1.2）。54 分钟这个数可能差 2 倍。
  - 缓解：首跑打开 per-call 计时与 usage 记账写进 snapshot，用实测替换模型；金额侧即使费率差 5 倍全量也只到 ~$15，结论「钱不是约束」不受影响，受影响的只有墙钟。
- **[medium]** 把 judge 移出 store 循环改变了 E 的语义：今天的模拟用户是「被判 miss 才纠正」的反应式，新 episode 是脚本式。跨版本的 E 分数不可直接比较。
  - 缓解：这是 spec 的 gold-by-fold 设计蕴含的结果（运行时判决驱动 store 就无法离线 fold），不是可选优化；但要在 snapshot 里打 protocol_version 并把旧 E 归档为 E-legacy 冒烟，明确不做跨协议比较。
- **[low]** 408 个 shard 里 24 个比其余长 8–20 倍。按文件序提交给 ThreadPoolExecutor 可能让 chained shard 排在最后，尾部只剩 1 个 worker 在跑。
  - 缓解：run_items 增加 weight 参数并对 todo 做 LPT 降序排序（用事件数当权重即可，无需真实秒数）。

### 未决问题

- episode 数与每条的 constraint 数怎么切？本设计按 12 × 56 = 672 算（沿用旧 spec 的 scenario 规格），shard 数、CI 簇数和墙钟都直接依赖这个切法。若改成 16 × 42 或 8 × 84，chained 的关键路径和聚类功效都要重算。
- 新 E 的权重与 gate 由 owner 定。E 现在是 performance suite（对标 LoCoMo / LongMemEval 的位置），T/L 是 functionality——旧的 0.4/0.3/0.3 和 GATE_PER_SUITE=0.70 是按 3 规则 E 的量纲定的，量纲已经变了。方向层的事，不替你拍。
- judge 允许按 probe 批量吗？把一个 probe 的 3 条 must_carry 合成一次调用能把瓶颈资源砍到 1/3（墙钟 54min → ~30min），但会破坏「一判据一调用一二元」这条已经过抽检背书的协议，criterion 之间会互相污染。我倾向不批，但这值 20 分钟墙钟，你决定。
- repeat 次数：GEN_TEMPERATURE=0.0 下 oracle 模式很可能逐字可复现。要不要先跑一次量 cache 命中率，命中率 >95% 就把 oracle 的 repeat 降到 1（省 288 个 shard）？这需要先有一次实测才能定。
- Ark 侧 deepseek-v4-pro 的真实 RPM/TPM 限额和当前价目——两个都没核过。有没有控制台能直接查到？这决定 judge_workers 是 6 还是 10，也决定墙钟是 54 分钟还是 32 分钟。
- 「judge 退出 store 循环、纠正信号改为脚本化」这一条虽然是 gold-by-fold 设计的必然结果，但它确实改变了 E 测的东西（反应式 → 脚本式模拟用户）。要不要在 spec 里单独立一条备案，还是直接当 §2.2 的既定含义？
- 机械对齐的覆盖率目标定在多少？本模型假设 70%，推到 85% 能省 13 分钟墙钟。这取决于 distinctive 的写法纪律（每条都要是可 grep 的变异数字/自造词），是 P5 的人工成本和 runner 墙钟之间的交换。


---

## 对抗复核


### 判定：salvageable

**致命缺陷**

- 升级队列以「分歧」为筛选条件，而系统性标注偏差恰恰产生「一致」——10 个人工名额在结构上永远采不到它要防的那类错误。三路一致的样本直接进 gold，不经任何人眼。

- canary 灵敏度 s 测的是「coords 被人为改坏、与文本不一致」的错；真实错误里文本是从 coords 生成的，二者必然一致。两个分布不相交，所以公布的残余错误率 f/s 不是对任何量的估计——而它正是被拿来替代「我们全看过了」的那个数字。

- d_coords 的输入 u.kind ∈ {assert, withdraw, scope_shift} 本身就是 retire-vs-contradict 的答案（见其伪代码 withdraw / scope_shift 两个分支直接拿到 u.key / u.scope / u.dead）。在 L 今天卡在 0.50 的那一类上，「三路独立导出」实际是「计划的两份拷贝 + 一个廉价 LLM」。

- scope 漏填在 relate() 上不是对称噪声而是有方向的偏差：漏一边→B_EXCEPTS_A（谁都不死），两边都漏→伪 CONTRADICTS（本该 INDEPENDENT 的跨语言规则互杀）。且 I8 只拒绝过窄的 scope，没有任何闸拒绝过宽——构建流程对这个偏差是单向棘轮，主动选择它。I1/I2/I3/I7 全部不报警。

- bench 的 ~90 key 封闭注册表与产品自造的 key 空间不是同一个空间（EXTRACTION_SYSTEM 规则 4 让 SUT 自由发明 key；recall._KEY_LEXICON 只有 14 个词根）。「调用产品自己的 recall()/_scope_ok」这条辩护对 must_fire 可满足性、I4、I6、lint 3 全部失效——lint 在 gold 对象上模拟，跑的不是运行时那个函数。

- 产品 status 只有 (active, retired)：scope_dead 完全不可观测；merge 只在 supersedes 里记 targets[0] 一个前驱；revival 在写路径上无代码路径（un-retire 只能走 server.py 的手动 API）。图导出的分辨率高于测量能承载的，E 分低时无法归因于 gold 还是产品。


**论证**

## 结论先说

反对意见成立。意见没有被消除，被搬家了，而且搬到了一个**误差相关性更高、且现有控制手段在结构上测不到**的位置。但设计不是不可救——有三处是真机械的（fold、distinctive-token 的 suppress、传递性不变量），坏掉的是「可信度论证」那一层，不是整个流水线。所以判 salvageable，同时**「图导出的 gold 比手写 gold 更可信」这句话按现在的论证不成立**，必须换成更窄的真命题。

以下每条我都在代码上核过，标注了「核实过 / 推测」。

---

## 1. 致命的那条：升级筛选条件与要防的错误类反相关

**核实过。** 设计里人工名额的分配路径是唯一的：`voi()` 排序 → 分歧队列 top-10。而 §4.1 的分歧表把「三者一致」直接判为「接受，无人工」。

问题在于：**独立随机的标注噪声产生分歧，系统性偏差产生一致。** 这不是修辞，是流水线的因果结构决定的——

episode 设计的顺序是 `源句 → SKELETONISE(LLM) → skeleton → 变异 → UTTER(LLM) → utterance`，graph 设计的 coords 也是从同一次阅读里出来的。如果 skeletoniser 把一条 Google Python style rule 读成了全局规则（丢掉 `code_lang: python`），那么：skeleton 无 scope → 生成的话语里没有任何限定语 → 回读闸读不出 scope（字段两边都缺，相等，PASS）→ D_text 读散文也读不出 scope（散文里本来就没有）→ **三路一致，自动接受。**

于是设计声称最强的那道防线（三路交叉）在这一类上恒为绿灯，而人工名额按定义看不到它。owner 的 lever (b)（LLM 标全部、只升级歧义项）在这个失效模式下**期望产出 0 条相关升级**。

设计给 lever (a) 留的 6 个前置名额也救不了：它们被指定取在「三条已知的决策边界上（retire vs contradict / widen vs new / merge vs independent）」——这三条同样是**分歧形状**的边界，不是从 corpus 主体随机抽的。所以 10 个名额里 0 个落在一致区，而一致区承载了 ~80% 的分数质量（设计自己的预期）。

**这条是本次审查里唯一我认为无法靠调参绕过的结构性错误。**

## 2. canary 灵敏度测的是另一个分布，f/s 不是估计量

**核实过（逻辑，非代码）。** §4.3 的 canary 做法是：往已标注批里注入 40 条人为损坏（换 value、放宽 scope、翻 polarity、替换 key、withdraw 写成 amend），要求交叉检验命中 ≥ 0.90。

但人为损坏是**在正确的 coords 上事后施加**的，所以损坏后的 coords 与「从未损坏的 skeleton 生成的那句话」必然不一致 —— D_text 一读就炸。这测的是「我们能不能发现 text 与 coords 打架」。

真实错误的产生方式相反：coords 先错，话语**从错的 coords 生成**，text 与 coords 完美一致。这两个分布**不相交**。

后果：s ≈ 0.9 是在一个人为构造的、必然可检的子集上测的，把它当分母去算 `真实错误率 ≈ f/s`，得到的数没有统计含义。而设计明写「这是取代『我们全看过了』的那个数字」——被取代物是空的。

**最小修复**：canary 必须在 SKELETONISE 之前注入，即损坏源句的**解读**，然后让整条流水线（含 UTTER）在损坏解读上跑完。这样 text 与 coords 一致地都错，才是真实分布。我预计这样测出来的 s 会**远低于 0.9**，那才是有用的信息。

## 3. 「三路独立」在最该独立的那一类上是假的

**核实过（读 d_coords 伪代码）。** 设计画的独立性边界是「d_coords 可以知道 u 陈述了哪条，不能知道它压过哪条」。但它自己的 `d_coords` 有三个分支：

```
if u.kind == "scope_shift":  ... c.scope.get(d) == v for d,v in u.dead.items()
if u.kind == "withdraw":     ... c.key == u.key and scope_relate(c.scope, u.scope) in ("EQ","A_SUB_B")
cn = u.asserts               ... relate(cn, c)
```

`u.kind` 三选一本身就是「这句话是撤回还是改写」的判定，而 withdraw / scope_shift 分支还直接拿到了目标区域（`u.key` / `u.scope` / `u.dead`）。也就是说：**revoke 与 scope_dead 这两类上，d_coords 拿到的是答案，不是坐标。** 只有 assert 分支是真算术。

设计声称把 retire/contradict 的歧义「变成了结构差异：有替代值 → CONTRADICTS，无替代值 → WITHDRAWS」。但「有没有替代值」是生成器按计划决定要不要往话语里塞一个值——**这是作者的意图，不是文本的性质**。真实用户说「行宽那条以后不用管了」时，替代值在不在句子里恰恰是模糊的，这正是 L 的 revoke 卡在 0.50 的原因。

所以在 bench 最想测好的失效类上，D_plan 与 D_coords 是同一个意见的两份拷贝，唯一可能反对的是 D_text（一个廉价 LLM 读散文）——**正是本设计要取代的那个东西**。设计的决策卡示例（「行宽那条以后不用管了」，读法 A vs 读法 B）恰好就是这一类，它出现在人工队列里不是巧合，是因为这一类根本没有导出，只有投票。

## 4. scope 漏填在 relate() 上是有方向的偏差，且构建流程主动选择它

**核实过——我把设计给的 `relate()` / `scope_relate()` 原样抄下来跑了：**

| 情形 | relate() 返回 | d_coords 后果 |
|---|---|---|
| 真值：两条都 `code_lang: python`，96 vs 80 | `CONTRADICTS` | 旧条目死（正确） |
| 新条目漏填 `code_lang` | `B_EXCEPTS_A` | **谁都不死**，旧条目永远 active |
| 两条都漏填（系统性塌缩） | `CONTRADICTS` | 碰巧正确 |
| 真值 python 96 vs java 100（本该无关） | `INDEPENDENT` | 正确 |
| 上一行两条都漏填 | **`CONTRADICTS`** | **伪 supersede，杀掉一条活规则** |

两个方向都坏，而且方向不同：漏一边 → gold 欠失效（僵尸留在 must_fire 里，**奖励一个从不 retire 的系统**，正好反向污染 null-dump 对照臂）；两边都漏 → gold 过失效（伪链）。

关键在于，最后一行的伪 CONTRADICTS **对全部不变量隐形**：I1 不报（gold 自己杀掉了一条，不会同时 active）；I2 不报（同 key，传递性自洽）；I3 不报（scope 是 EQ 不是 OVERLAP）；I7 不报（它有非 INDEPENDENT 伙伴，不是孤儿）。整套机械不变量对这一类是全盲。

更糟的是**构建流程对这个偏差是单向棘轮**：I8 可达性会机械拒绝 scope 过窄的条目（「条目永不激活 → 机械拒绝」），而 scope 过宽只有「D_text 读回」这一道软闸——而 §1 已证明回读闸对**漏填**（两边字段都缺 → 相等 → PASS）在原理上无效，它只能抓**篡改**。episode 设计还把「55% global `{}`」写进 scope 分布指标，等于给塌缩发了通行证。

一条现实约束让这更严重：`thin-bucket-sourcing.md:249` 自陈「名义 189 条、实际 17 个家族」。语料不是 672 个独立样本，是几十个家族的展开。**一次家族级的 scope 误读同时污染一整族。** 设计自己的 `voi()` 例子写着 `cluster_size = 43` —— 它把「一个决定传播到 43 条」当作人工名额的杠杆来用；标注器用的是同一条管道，只是没人看着。

## 5. 「调用产品自己的函数」这条辩护对 key 相关的断言全部失效

**核实过（跑了代码）：**

- `recall._KEY_LEXICON` 只有 14 个词根：`citation, code, comment, doc, email, explanation, format, language, length, meeting, report, research, style, tone`。
- `_key_hits_query('code.line_length', '帮我写个 python 函数把嵌套 dict 拍平')` → **False**（`code` 的表面形只有 `code` / `代码`，中文请求里都没有）。`_key_hits_query('commit.subject_mood', '写个 commit message')` → True，纯属 `len(part) > 2` 的字面回退撞上了。**cap 之上的相关性排序由 14 个硬编码词和字面巧合决定**，bench 那份 90 key 的注册表对产品检索零作用力。
- `EXTRACTION_SYSTEM` 规则 4 让 SUT 自由发明 key（"a two-part facet key like email.length"），**开放词表**。bench 要封闭词表才能让 `relate()` 成立。两个 key 空间不通约。

具体崩掉的断言：
- **must_fire 可满足性**：lint 在 gold 条目（gold key / gold scope）上模拟 `recall()`，运行时跑的是 SUT 条目（SUT key / SUT scope）。这是两次不同的函数应用，lint 的保证是空的。`_scope_ok({'task':'postmortem'}, {'task':'组里的postmortem'})` → **False**——而 EXTRACTION_SYSTEM 明确要求「use exactly that wording as the rule's breadth: the user's phrasing IS the scope」，逐维字符串相等注定失配。
- **I4（DUPLICATES 必须在某点被 merge）**：产品的合并候选由 `consolidate.buckets()` 决定——先按 `r.bucket` 再按精确 `r.key` 再按 `key.split(".",1)[0]`。我跑过：同 key 不同 bucket 的两条**永不同组**；而同 bucket 的全部 unkeyed 条目被塞进**一个**候选组，等于邀请产品去合并图上判 INDEPENDENT 的任意两条。I4 既不可满足也不可防。
- **I6 / lint 3（must_not_fire 陷阱须与 must_fire 共享 key 前缀）**：共享的是 bench 虚构空间里的前缀，与产品的召回行为无关，陷阱的「不白送」保证是装饰。

## 6. 图的分辨率高于测量能承载的，分数低时不可归因

**核实过（schema.py / store.py）：** `STATUSES = ("active", "retired")`。

- `retire` 与 `contradict` 都产出 `status="retired"`，唯一差别是 contradict 另加一条 `supersedes=old.id` 的新记录。
- `merge` 退休全部 targets，但新记录**只写 `supersedes=targets[0].id`**。一个 3→1 的 merge，产品结构上最多表达 1/3 个指针 —— `chain_fidelity` 会把一个结构性必然的 2/3 损失读成产品错误。
- `scope_dead` 在产品侧**完全不可观测**，只能落成 `retired`，与 revoke 无从区分。图上「纯算术不是判断」对 gold 成立，对打分无用——没有可比的产品信号。
- **revival 在写路径上无代码路径**：`apply_ops` 没有任何 op 能把 retired 翻回 active；`reinforce` 只加 strength 不改 status；un-retire 只有 `server.py:125` 的手动 HTTP API。所以「两种产品行为都记为通过、分开统计」这个中立立场是假的，只有一支可达。

## 7. 剩下两条控制手段的实际功效

- **打乱对照**（把 coords 在条目间随机置换，分歧率必须暴涨）：置换 key 会摧毁几乎所有关系，分歧率必然暴涨。它测的是「d_coords 有没有读它的输入」，不是「d_coords 对不对」。对**轻微系统偏差**功效≈0。把它列为三大负对照之一是范畴错误。
- **E-legacy 可比性**（cp-00 的 ~6 条规则应与今天 0.667 在噪声内一致）：这是设计给出的唯一可证伪检查，但新流水线同时改了六件事（话语生成、carrier 轮、context 传入、key/scope 赋值、recall 真正被触发、consolidation 被驱动）。今天的 `run_e2e.py:86` 是 `_polish(rd["task"], [...])`——**第三个参数 context 根本没传**，且 `_apply_ops` 造的是 `Requirement(text=...)`、无 key 无 scope，所以今天的 E 从未跑过 `_scope_ok` 也从未跑过 cap 分支。一个标量差异无法在六个变量间归因。

## 8. 量化：为什么「相关」比「分散」更糟

设计自己的数字：720 个 gold 节点、单趟 ~3,600 条断言、`blast` 早死条目 ≈ 20 / 末尾 ≈ 1。算出来：

| coords 错误率 | 坏节点 | × blast 8 | × blast 20 |
|---|---|---|---|
| 2% | 14 | 3% 断言质量 | 8% |
| 5% | 36 | 8% | **20%** |
| 10% | 72 | 16% | **40%** |

注意**放大倍数本身不是罪**——手写 effect log 的每个判断同样有 blast ~8–20。真正的差别是**相关性**：手写错误在条目间近似 iid，会互相抵消、体现为方差；标注器错误按源/家族共享，体现为**偏差**，不进 CI，且指向同一个方向。设计公布的是 bootstrap CI 与 f/s，两者都只能测方差项。**一个系统性偏移的 gold 会给出一个又紧又错的区间**——这正是 spec §7 自己写的那句话（「错 15% 却报三位有效数字的 bench，比它取代的更糟，因为它会被信」），而新方案把这个风险**提高**了，同时把 spec 里唯一针对它的防线（双人签字）删掉了。

而且错误集中在 chain 条目上（`role` 由度数导出，chain = 有关系边的），也就是 `E-crud` 子分——「该驱动工程优先级的那个数」。

## 9. 公平地说，哪些是真的赢了

不能只拆不认：
1. **`d_plan` 的 fold 确实构造性为真**——相对于计划。它消灭的是誊写/一致性错误（600+ 条 × 8 前缀手写状态必然出的那类），不是判断错误。这是真收益，spec N0 的 fuzz 等价测试值得保留。
2. **`must_not_fire` 用 `not_contains(distinctive)` 机械判**是本次最大的真赢：今天 SUPPRESS 半边**完全不存在**，加上它几乎零 LLM 成本。注意它**不依赖图**——手写 gold 配 distinctive token 也能拿到同样的东西。
3. **I1 / I2 传递性检查**能抓中间环节 key 打错的真誊写 bug。
4. **「生成而非标注」**确实买到 `R(G(x)) == x` 这条可跑的等式——但只对回读闸比较的字段、且只对**篡改**有效，对**遗漏**在原理上无效（§4）。

## 10. 我认为必须做的修改（按性价比）

1. **把 10 个名额从分歧队列挪到一致区随机抽样。** 这直接答 owner 的 lever (a)/(b) 二选一：**选 (a)，但抽样点必须在三路一致的条目里随机取**，不是在决策边界上取。分歧项本来就有 `may_fire` 降级兜底，不需要人工。
   附带一个必须说清的算术：**10/10 全对，只能把 corpus 错误率的 95% 上界压到 25.9%**（20 条 → 13.9%，30 条 → 9.5%）。这是 10 条预算的诚实天花板。想拿一个能对外营销的分，要么名额涨到 30，要么把宣称从「已验证」降到「已抽样，上界 26%」。**owner 需要在这两者之间选，不能两个都要。**
2. **scope 禁止缺省。** 六维每维必须显式给值或字面量 `ANY`，skeletoniser 被迫选择。这样「漏填」从不可见变成可比对的事件，回读闸也才有东西可比（`ANY` vs `python` 不相等）。这一条单独就能堵掉 §4 的主要通道。
3. **canary 前移到 SKELETONISE 之前**，损坏「解读」而不是「已标好的坐标」，让 text 与 coords 一致地错。测出来的 s 才可用；我预计会显著低于 0.9，这个数本身就是最有价值的产出。
4. **加一条真正独立的第四路导出：从 L0 源句直接判。** 源句是流水线唯一没碰过的物件（licence 闸已经要求它留在 build 机上）。「这两条源子句是不是对同一个量给了不同的值」用 regex 在源上判，不看任何 LLM 标注。这是目前唯一能打破生成一致性的东西。
5. **key 空间二选一**：要么让 SUT 的 key 也走封闭注册表（spec §9 明说不因 bench 改产品，那就是不行），要么**删掉所有依赖「bench key 与产品 key 同空间」的断言**（I4 的 merge 期望、I6、lint 3、must_fire 的 recall 可满足性），merge 只用文本等价判。现在这一层是在给一个虚构空间打分。
6. **d_coords 不许收 `u.kind`。** withdraw / scope_shift 的判定必须从话语的坐标里算出来（例如「u 断言了一个同 key 同 scope 但 value 为空的节点」），否则就诚实地承认 revoke / scope_dead 两类是**构造性 gold 而非导出 gold**，并把它们和 assert 类分开出分——不要混进同一个 headline。

## 11. 一句话回答被问的那个问题

**没有逃掉。** 意见从「作者判定这次是 contradict」搬到了「廉价 LLM 判定这条的 key 与 scope 是什么」，而后者的错误经 `relate()` 一致地放大到几百条断言上；设计给的三道交叉检验里，两道（D_plan / D_coords）在最难的类上共享同一个作者答案，第三道（D_text）读的是从同一次错误解读生成出来的文本；用来量化残余误差的 canary 测的是另一个分布；用来兜底的 10 个人工名额按定义采不到一致区。所以它确实把意见洗成了看起来像测量的东西——**但洗得不彻底也不是不可修**：上面 6 条改完之后，它给的是「一个一致、可审计、且错误率有已声明上界的 gold」，那是一句可以对外说的、比手写 gold 强的话；「更可信」这句现在这个论证撑不住。


### 判定：salvageable

**致命缺陷**

- voi() 的定义域是 flag，不是 constraint。三路一致的条目根本不产生 f，因此不进排序、不进 top-10。这不是权重没调好，是样本空间错了：任何「产生一致而非分歧」的错误类，10 个名额在结构上不可能碰到它。coords 的投票熵对全部 672 条免费可得，却只在已经分歧的子集上作为 p_wrong 的乘数被使用。

- 存在一整类高发系统性错误产生完美三路一致：bucket 边界错 → key 分区错 → 关系消失。链条是机械的：key 注册表「按 bucket 分区，每 bucket ~15 个 key」，所以 bucket 判错强制导致 key 来自错误分区；relate() 第一行 `if a.key != b.key: return INDEPENDENT`，边直接消失；无边则 I1/I2/I3/I4 全部无对象；D_text 「一次一个 bucket」，两条被分到不同桶的条目在两次独立 prompt 里各自答 in_force，也一致。项目自己的 /Users/siriux/Library/Mobile Documents/com~apple~CloudDocs/Documents/Codes/Projects/MemTranslator/docs/2026-07-26-taxonomy-verdict.md 实测 bucket 歧义 23%（51/224），且明写「单标注者、强制单选，真实分歧率大概率更高」，其中 55% 集中在 deliverables↔output_contract 一对边界上。

- I4 是循环定义，抓不住它声称要抓的那个坑。I4 写的是「DUPLICATES 对必须在某个 seq 被 merge」，而 DUPLICATES 只在 `a.key == b.key` 时才可能由 relate() 产出。「语料里未声明的重复对」这个失效模式的成因恰恰是 key 被劈开——劈开的同时就把 DUPLICATES 边删掉了。I4 只能看见已经用同一 key 标好的重复，也就是本来就不会出问题的那些。后果是可计价的：产品的 src/memtranslator/consolidate.py::buckets() 按 bucket→精确 key→facet 前缀分组，用的是 haiku 的 bucket 判断，与 bench 侧 DeepSeek 的判断不是同一个；产品把它们合并（正确行为），gold 说两条都该 active，于是记 1 个 miss + 1 个 phantom，在 cp-06 之后每个 checkpoint 都记一次。

- scope 收窄/放宽错误对三条导出全部不可见，且方向性地抬高分数。dim_rel 里 `None` = 全集，是 LLM 信息不足时的默认落点；产品 recall._scope_ok 对 `scope={}` 的条目永不过滤。而 D_text 的封闭答案集 {not_yet_mentioned, in_force, superseded_by:n, withdrawn, merged_into:n, no_longer_applies_scope} 里没有任何一项能表达「这条的作用域比文本说的宽」——no_longer_applies_scope 是生命周期答案（scope 被 scope_shift 杀死），不是宽度答案。设计 §4.4 却把「scope 太宽」的抓手写成「D_text 读回」。一条本该 {task: commit-msg} 却标成 global 的规则，三路都答 active/in_force，而它同时进了 must_fire（送分）并退出了「活但越界」must_not_fire 陷阱（新增的唯一真陷阱被掏空）。episode 设计自报 55% 节点是 global {}，正是这一类错误的收敛方向。

- 传播回验把人工杠杆做成了只能追认 D_text。规则是「传播后对该簇重跑 D_text；不合率 >20% 判定簇为假，回滚整簇进 E-amb，不再花第二个名额」。而 top-10 的高权类正是 TEXT_DISSENT(W=1.0) 与 THREE_WAY(W=1.0)——owner 被叫来仲裁的前提就是 D_text 与 plan+coords 不合。若 owner 站 plan+coords（即推翻 D_text），把这个标签传播到一个同质簇上，D_text 会在簇内近 100% 反对，>20% 必然触发，回滚。若 owner 站 D_text，传播只是复述 D_text 本来就会给的答案。所以该杠杆的两个稳定输出只有「无变化」和「弃簇」，它在形式上不可能在自己被设立的那个方向上纠正 LLM。

- cluster_key 含 disagreement_class，导致 owner 的一条语义规则被不一致地施加。簇键是 (bucket, key_family, disagreement_class, value_type)。owner 的答案落成的是一条读法规则（如「以后 X 就不用了 且未陈述替代值 → revoke」），这是全语料通用的语义裁定；但它只传播给「恰好以同一方式分歧过」的条目，语言形式相同但两个 reader 恰好都读成 supersede 的那些不在簇内、不受规则约束。结果是同一句用户话式在 gold 里同时存在两种读法。而 revoke/contradict 正是 L suite 今天卡在 0.50、整个扩容要修的那一类——gold 在这一类上自相矛盾。

- D_text 是 SUT 的一次重新实现，它的分歧率主要度量的是它自己的能力，不是语料的歧义。它的任务是：读 86 轮渲染文本前缀 + 一个桶的打乱条目，判定每条的生命周期状态。这正是 MemTranslator 存在的理由；如果一个 flash 档模型读完整 transcript 就能可靠地导出哪些约束仍然有效，产品就不必存在。于是 (a) f/s 里的 f 被 D_text 噪声主导，残余错误率被高估且不可分解；(b) 「歧义率目标带 8–15%，低于 8% 判定语料过净、退回重写」是一个装错传感器的控制回路——若分歧由 reader 能力主导，这条规则会驱使语料人为变脏去满足一个模型本来就会产出的数字；(c) 分歧量随 checkpoint 前缀长度增长，最密的 cp-06..cp-08 会主导 flag 流，而那里恰好是 blast 最低的区段。成本估计也偏低：cp-08 的前缀在中文下约 3.4k token 加 catalogue ~1.2k，不是 ~2k。


**论证**

## 一句话结论

10 个名额本身不是问题，**分配方式是问题**：`voi()` 只在分歧集上有定义，而本语料最大的一类系统性错误按构造产生一致而非分歧。这不是调权重能修的，是样本空间选错了。

---

## 1. 先给一个与模型无关、不可辩驳的量

10 次抽样的统计分辨率有硬上限。若 owner 看 10 条**随机**样本、10 条全对，按 rule of three，语料错误率的 95% 上界是 3/10 = **30%**。而设计要发布的 headline 是 scenario 聚类 bootstrap、CI 半宽 ±0.057 的三位有效数字。标注误差项比抽样误差项大约 5 倍，且不可压。

更糟的是：`voi()` 排序让这 10 条**不是随机样本**，于是连这条 30% 的弱推断都拿不到——非随机选样上不存在向总体的外推。所以设计其实是在两件事里选了一件而没说清：这 10 个名额做的是**校准（定操作点）**，不是**验证（给出错误率保证）**。gold 可信度实际上 100% 压在 canary 灵敏度上，而 canary 只覆盖已建模的五类。这一点设计 §4.3 承认了一半（「对已建模错误类的估计」），但没承认下面这条：其中两类的 s ≈ 0。

规模对照：672 条 × 每条约 3 个真正独立的判断（key / scope / value-polarity）≈ **2,000 个标注决策**，外加 12×58 个 probe 的 activation 判定。10/2,000 = 0.5%。

---

## 2. 分歧与「要紧的错误」相关吗？——反相关

**(a) `blast` 与 `p_wrong` 按构造反相关。** `blast` 由设计自述「早死的条目 ≈ 20，末尾的 ≈ 1」——早死 = 在链上 = 有 AMENDS/CONTRADICTS 构造边 = 同 key 是构造出来的 = 数值走了 regex 优先 + 序列化回环。**链上条目是全语料被机械检查最密的一类，p_wrong 最低。** 反过来，p_wrong 最高的是 freeform（上限 35%，按定义拿不到任何边）、bucket 边界条目、scope 欠标条目——它们全都 blast ≈ 1。`voi` 里动态范围最大的两项 `cluster_size`（1–43）× `blast`（1–20）都是**生成计划的属性**，不是标注风险的属性，乘积由它们主导。设计自己举的决策卡例子就是行宽 96/72——数值型、regex 抽取、构造链上——全语料被过度决定程度最高的条目类型。这正是「把名额花在本来就容易的条目上」。

**(b) 权重把唯一可观测的证据压到最低。** `W[PLAN_VS_COORDS] = 0.1`，理由是「机械可修，不该烧人工」。但 plan 说 AMENDS 而 coords 算出 INDEPENDENT，正是 key 劈开在链上留下的唯一足迹——也是这一类错误在全语料中唯一可观测的地方（独立条目上没有 plan 边可对撞，完全静默）。而「机械修复」的动作是把两个 key 强行改成相等，**这恰好抹掉了「注册表分区不足」这个信号**。自动修复队列在这里销毁证据。

**(c) TEXT_DISSENT（最高权重）会被一个 prompt 形状的产物灌满。** D_text「一次一个 bucket」，`superseded_by:<n>` 的 n 索引在本桶内。跨桶的 supersede 对它**不可表达**。叠加实测 23% 的 bucket 歧义（55% 集中在一对边界上），一批真实的 supersede 对会稳定产出 `plan == coords ≠ text`，被路由到最高权的人工队列。名额被一个实现选择消耗，而不是被真实的 gold 不确定性消耗。

---

## 3. 停止规则不可计算

「owner 与流水线在这 10 个上一致率 < 8/10 → E 不进 gate」。但这 10 条是**因为导出之间分歧**才被选中的：在一条 flagged 条目上流水线没有一个答案，它有两三个。与谁比一致？把 plan+coords 当流水线，则 owner 站 D_text 时全记不一致；反过来同理。这个指标在它被计算的那个样本上**没有定义**。而且方向是反的：若选择器有效（专挑最难的），8/10 几乎必然不达标，预注册的后果会永远触发；若选择器无效（按第 2 节实为挑容易的），几乎必然达标。它的偏置由选择器决定，不由流水线质量决定，两种情形下都不携带信息。

---

## 4. canary 的灵敏度是注入位置的产物

40 条 canary 分五类，其中「替换 key」只有落在**链上条目**时才可能被 I7/plan-vs-coords 抓到。若 8 条均匀注入到 672 条（每 episode chain ≈ 20/60），约 2.6 条落在可检测区，实测 s ≈ 0.33；若刻意注入链上，s 被抬高但不代表总体。「放宽 scope」按第 2 节的机制 s ≈ 0（D_text 无该答案）。于是 `f/s` 对这两类要么无定义要么发散，而「≥0.90 才发布」的纪律会长期卡死在一类**架构上不可检测**的错误上——因为设计明写 bucket「对关系无影响」。可预见的结果不是修检测器，是砍掉那一类 canary 或降阈值。

---

## 5. 未计入 10 个名额的人工判断

- **~90 条 key 注册表 + enum domain + 六维 scope 词表**。三条导出**全部条件于同一份词表**，因此词表错误是共模错误，交叉一致率只测「给定词表下的自洽」。这是全系统杠杆最大的人工判断，体量远超 10 条，却在天花板之外；若交给 LLM 写，则「coords 是唯一 LLM 信任面」的说法不成立——LLM 连选项集都是自己造的。设计自己的风险 8 承认注册表要在 G2 后「按孤儿率回填一轮」，那就是一次人工词表修订。
- 两份设计合计约 15 个 open question（licence 签字、STATE 进不进 gate、style_rule 契约、scope.lang 重载、revival 立场……），每一个都塑造数百条。诚实的账是：**label 预算 10，decision 预算 20+**。

## 6. episode 设计版本的三信号，实为 1.5 个

`applies_to` 的三信号里，(2) DeepSeek 二元判定与 (3) DeepSeek 判改写表面是同族同模型近同内容，不是两票。(1) 词法先验用 `signals.py::_KEY_LEXICON`，我数了：**只有 14 个词根**（email/code/report/doc/meeting/research/tone/length/format/language/style/explanation/comment/citation）。~90 个 key 的分量（`line_length`、`section_order`…）大多不在其中，`_key_terms` 回落到 `[part] if len(part) > 2`，即在中文请求里匹配字面量 `line_length` ——近乎恒 False。恒定信号不携带排序信息；而若扩表使其有效，扩表由与标注者同一套语义直觉写成，独立性随即消失。三信号分流退化成「DeepSeek vs DeepSeek」。

---

## 7. 什么是成立的（我确实试着破了这几条但破不掉）

- **「先建图→从边生成文本」的方向翻转**是对的，`D_plan` 构造性为真这一层无懈可击。
- **数值 regex 优先 + 类型槽序列化回环**真正把 LLM 从环里拿掉了，不是修辞。
- **I1/I2/I3/I5/I8** 是真不变量、真便宜——条件是 key 注册表正确。
- **episode 设计不写 `final` 只写 `diff_plan`** 是对今天 persona 文件的一处硬性正确性修复（今天把 SUT 输出当常量存了），与 10 个名额的问题正交。
- **carrier 轮**（请求与信号同一字符串）是真实分布里最高频而今天完全测不到的形态，值得保留。

---

## 8. 若必须在 10 条以内活下来，我会怎么改

1. **10 条全部改为分层随机抽样**，分层键 = (bucket 边界对, scope 是否为 null, value 是否 freeform)。放弃「修正个别条目」的幻想，换回那条唯一能说的话：一个 95% 上界。发布时把上界写进报告，不写「我们校准过了」。
2. **加两条零成本机械不变量补上盲区**：(I10) 同一 episode 内任意两条 constraint，若其 `gold_text` 的内容词 Jaccard ≥ 阈值但 `relate()` 判 INDEPENDENT，构建期报错——这条抓的正是 I4 因循环定义漏掉的 key 劈开；(I11) 任何 `scope` 全 null 的条目必须在至少一个 probe 上作为「活但越界」陷阱出现，否则拒绝入库——强制 scope 宽度承担代价而不是白拿分。
3. **反转传播回验的判据**：簇有效性不能以「与 D_text 相合」为准，否则杠杆自锁。改为以簇内 coords 的四维同一性 + canary 注入的簇内检出一致性为准。
4. **删掉 8–15% 目标带**，或先用一批人工确认为「无歧义」的条目测出 D_text 的基线错误率，把它从分歧率里减掉再谈语料歧义。
5. **把 bucket 从「对关系无影响」改成有影响**：既然 key 注册表按 bucket 分区，bucket 就已经在决定每一条边了。要么承认这一点并加同 key 必同 bucket 的强制约束 + 跨桶 supersede 的显式检测，要么解除注册表的 bucket 分区。现状是两头都不占。
6. **STATE 分暂不进 gate**，直到 I10 在首个 scenario 上跑出的孤儿/伪独立率被公布——它直接决定被产品 consolidation 正确合并却被 gold 判错的量级。

按 23% 的 bucket 歧义、每三条边界条目里有一条在同 episode 内有语义搭档估算，全语料约有**几十对**被静默劈开的重复，每对在 cp-06 之后的三个 checkpoint 上各贡献 2 个错判 state 断言，量级在 ~3,600 个断言里占**个位数百分点**，方向是系统性压低分数、且惩罚的是产品的正确行为。这个数字是我按上述假设推的**估计，不是测量**——但它可以在写任何语料之前，用 I10 在首个 scenario 上便宜地测出来。


### 判定：salvageable

**致命缺陷**

- CARRY 占 headline 60%，但实测对注入集合几乎不敏感：注入 8 / 30 / 52 条时 carry 分别是 6/6、5/6、5/6。任何把该规则装进 store 的臂都拿同样的分。0.6 的权重打在一个不区分系统的量上，全部区分度被迫压进 0.4 的 SUPPRESS 半边。

- flat-dump 不是 baseline 而是 oracle：它有完美 store，所以 CARRY 更高（probe 1 实测 3/3 vs 真系统 2/3）、死条目一条都没有故 SUPPRESS-on-dead 免费满分、STATE=1.0、QUIET=1.0。它唯一可能被扣分的地方是「活但越界」陷阱，实测泄漏率 1/6。它在每一个分量上都 ≥ 真系统，spec §4.5 那条 go/no-go 会以「分不开」告终，而两份设计的主要机械（activation 推导、MUST_FIRE_CAP、touched_keys、六维 scope 及其投影失真）全部建在这个不会动的层上。

- lint「must_carry 必须通过模拟 recall()」这一条在结构上禁止了任何能检出长程遗忘的断言。实测：pool=52、用图设计提的 ~90 key 注册表时，recall() 的输出与「单纯取最新 32 条」重合 30/32（94%），每个 query 只有 0–2 个 key 命中 _KEY_LEXICON。于是每一条计分的正向断言都落在最近 32 条窗口内，一个「只留最新 32 条、从不 retire、不看 scope」的系统能满足其中几乎全部。

- must_not_fire 陷阱没有可达性约束。死条目按构造一定比它的后继老，任何带 cap 的 baseline 会先把它们挤掉：按 episode 设计自己的密度表模拟，null-dump 在 cp-06/07/08 只注入 23%/37%/43% 的死条目，其余 57–77% 的陷阱断言对一个零生命周期逻辑的系统直接记满分。同一效应也把真系统自己的 retire 失败在高密度处藏起来——正是这套 suite 号称要施压的那一段。

- scope 维度对 SUT 不可见且对指标近乎不可测：translate._requirement_block 只打印 text，scope 字段从不进 prompt；实测越界规则被带进改写只有 1/6。六维 scope、lang 重载的投影失真、recipient/artifact 的 bench_only 处理，全部无法让数字移动。


**论证**

## 结论

会分开一部分，但不是设计者以为的那部分。**SUPPRESS 的死条目通道是真信号；CARRY 和整个读路径是装饰。**我跑了实测，不是推演。

## 实测（claude-haiku-4-5，temperature 0，机械判据，每格 n=6）

脚本在 `/private/tmp/claude-501/.../scratchpad/probe.py`、`probe2.py`、`sim.py`。

| 注入了什么 | 改写里带出来了吗 |
|---|---|
| 已 revoke 的规则（prompt 里没有后继） | **5/6 带出来** |
| 已 supersede 的旧规则（后继也在 prompt 里） | **6/6 带旧值**，且新值 0/6 |
| 活但越界的规则（措辞里写明 Java） | 1/6 |
| 活但越界的规则（scope 只在字段里，措辞不写） | 1/6 |
| dilution：store 8 / 30 / 52 条时带出目标规则 | 6/6 → 5/6 → 5/6 |

三条读数：

1. **死条目泄漏率 0.83–1.0。** 只要死条目真的进了 prompt，translator 就会照做，而且在 supersede 对里它选了**先列出的旧值**、丢了新值——一次断言两处失分。这是全套设计里唯一真有区分度的通道。
2. **越界泄漏率 0.17，且与 scope 是否写进措辞无关。** translator 自己按话题词面做过滤，把 recall 的 scope filter 的活干掉了。
3. **dilution ≈ 0。** 52 条注入和 8 条注入几乎一样准。flash 的上下文根本没被 50 条压住——spec §4.5 那个「50 条构不构成读路径压力」的可证伪前提，答案是**不构成**。

## 分离度算术

用实测 yield + 我按 episode 设计自己的密度表跑的可达性模拟（`sim.py`，400 seed）：

| cp | 真系统 SUPPRESS | null-dump | Δ | 折进 episode_score |
|---|---|---|---|---|
| cp-06 | 0.896 | 0.793 | 0.104 | **0.041** |
| cp-07 | 0.834 | 0.667 | 0.166 | 0.067 |
| cp-08 | 0.806 | 0.613 | 0.194 | 0.077 |

（真系统的 retire recall 取 0.50，即今天 L 的 revoke 实测值。）

对照：spec 自己的作废线是「suppress 半边相差 < 0.05 即本次 run 作废」，spec 自己算的 scenario 聚类 CI 半宽是 ±0.057，今天 E 同一份 case 三次跑出 0.788 / 0.693 / 0.667。**预期分离度和噪声、和自我作废阈值是同一个量级。** cp-06 已经在 0.05 线上。

flat-dump 方向是反的：它唯一的扣分点 yield 0.17，同时 CARRY 因完美 store 净赚。净差 ≤ +0.02 **且符号偏向 flat-dump**。

## 为什么会这样——三个机制

**(a) translator 在替 recall 干活。** SUT 是同一个 haiku，四个臂共用。prompt rule 1 明写「只在明显适用时改写」。读路径犯的错要先穿过一个独立做同类过滤的 LLM 才能变成分数，衰减系数就是上表的 yield。scope 那一列 0.17，等于 scope filter 的贡献被吃掉 83%。

**(b) recall() 在密度下就是 recency。** 实测 pool=52 时输出与「最新 32 条」重合 94%；提议的 ~90 key 注册表里每个 query 只有 0–2 个命中 `_KEY_LEXICON` 那 14 个词根。这里有个死结：不扩词表 → 读路径没有内容选择可测；扩词表去覆盖 bench 的 90 个 key → 就是 owner 明令禁止的 bench overfitting，而且违反 spec §9「不因 bench 而改产品」。

**(c) 死 = 老，是构造性的。** 被 supersede 的条目一定比后继早创建，cap 按 created_at 砍尾巴，于是一个纯 recency 的 baseline 顺手实现了大半个 retirement。57–77% 的陷阱断言因此白送。

## 决定走向的具体设计选择

**能把它救回来的：**

1. **权重反过来。** `0.6·CARRY + 0.4·SUPPRESS` 应改成 SUPPRESS 主导（我建议 0.3/0.7）。CARRY 实测不分系统，SUPPRESS 实测分。
2. **STATE 进 gate。** 这是 open question 里最该现在拍板的一个：null-dump 的 zombie_rate = 1.0，STATE 是唯一能干净打穿它的分量。把它留在 gate 外，等于把唯一稳赢的证据丢掉。
3. **加 must_not_fire 的可达性 lint。** 每个陷阱必须是「一个 recency-32 baseline 在该 probe 上真的会注入」的条目，否则拒收。这一条能把上面 57–77% 的白送断言全部换成有区分度的。代价是要控制 intro→death 的间距（死得离引入太远，陷阱就免费），这是 episode 编排的硬约束，两份设计都没写。
4. **补上真正的读路径消融臂：同一个学到的 store + 绕过 recall()。** 现有三臂没有一个是这个。flat-dump 用完美 store，所以它是 oracle 不是 baseline；null-dump 同时换了写路径和读路径，两个变量一起动。缺了这条，「recall 有没有用」这个问题这套 suite 结构上答不了。
5. **null-dump 的排序规则必须重写。** 「按 strength 取前 32」在这个 bench 里排的是一个常量——`Requirement.strength` 初始 1，`run_e2e._apply_ops` 的 reinforce 根本不 bump strength（只改 updated_at），episode 设计里 reinforce 也只有 3/68。全是平票，实际排的是 tie-break。写成 recency-32 才是那个真正威胁 suite 的 trivial baseline。

**会把它推向装饰的：**

6. **CARRY 的分数由生成器的措辞决定，不由记忆质量决定。** 同一条 88 列规则，写成「写 Python 代码按 88 列折行」被带进 Python 请求 5/6，写成「代码按 88 列折行」只有 1/6。两份设计都让 utterance 由 skeleton（含 `trigger` 字段）渲染出来，也就是**生成器直接调节 headline**。这个旋钮必须预注册并公布（措辞里含请求话题词的比例），否则 E 的分数可以在不碰产品的情况下调 ±0.2。
7. **12 × 51 = 612 条语料买不到与之相称的区分度。** 花在 corpus 上的边际收益集中在死条目陷阱上；把预算从「612 条 constraint」挪成「更少 constraint、更多失效事件与更多 probe 命中死条目」，同样人时能拿到高得多的分离度。

## 顺带查到的两个会直接产生假结果的实现事实

- `bench/runner/run_e2e.py:86` 从不传 `context`，scope 至今一次都没被跑过。两份设计都假定 context 通路存在，它不存在。
- `bump_strength` / `AUTO_RETIRE_AT = -2` 只挂在 `src/memtranslator/server.py:78`，`Pipeline` 和 `V1Provider` 都不走。episode 设计里占 25% 的 `revert_injection`（期望零 op、strength_delta = -1）在 bench 里**什么都不会发生**；产品唯一那条机械可靠的隐式退役路径不在测量范围内，被测的全是 LLM 那条。

## 诚实的边界

每格 n=6、单一 backbone、单一 facet（行宽）、温度 0。方向性强，量值别当定论。真正该做的是在写第一条语料之前跑一次预注册的小实验：3 个 facet × 4 个臂 × 20 个 probe ≈ 240 次 haiku 调用、几美元、一小时，直接给出「死条目 yield / 越界 yield / dilution 斜率」三个数。**这三个数如果落在我实测的位置，612 条语料写出来的 headline 主要是在测生成器的措辞。**
