# 写侧攻坚循环(2026-07-31)

Owner 协议:循环 = 认瓶颈 → 修(简单修复或轻量设计,LightMem/SimpleMem 优先)→
验证(qwen 先、ling 防 harness overfit)→ 下一瓶颈。产品不得 overfit 到 bench。

## 度量基线

- oracle(gold store):qwen 0.95/0.96,ling 0.90/0.88,glm 1.00/1.00 —— 读侧已非瓶颈。
- real(链式):qwen 0.43/0.37(4 集合并,单跑),STATE 0.43-0.73。
- real 断点归因(R9 store,23 判定点):W2 学到被杀 35% / W1b 抽取漏 26% /
  W1a 筛选丢 22% / R1 选择 0% / R2 织入 17%。**写侧合计 83%。**

## 验证纪律(本循环学到的)

- 单集 owner 指标 n≈10、链式方差 ±0.1,**单个修复必须用机制级指标验证**
  (裸 retire 数、空转族数、STATE、保真分类),owner 指标只做多集合并的阶段验收。
- 每项改进:pytest + L(qwen)→ 机制取证 → ling L 复核。E1 全量复跑只在阶段末。

## 瓶颈清单(按实测证据排序)

| # | 瓶颈 | 证据 | 状态 |
|---|---|---|---|
| B1 | 抽取层裸 retire 杀活规则 | e-05 取证:62 轮内 extract 发 10 裸 retire,9 个无接替者(净损失);consolidation 零 op。重叠 grounding 被任务闲聊打穿 | **修复已上(P1),机制验证中** |
| B2 | 同事实空转:一条规则学 4 个 id,同文本 supersede 链后全灭 | e-05 "brief and colloquial" 时序 4 学 4 杀 | **修复已上(P2),机制验证中** |
| B3 | 抽取漏抽(过筛选但无 op),中文规则重灾 | e-01 四条 zh 规则(113字符/699词/63字符/简洁)全部从未入库 | 待攻 |
| B4 | 筛选层丢规则形状 | "no headings"、"avoid single leading underscore"、verb-buried 等无数字、命令否定式,正则不认 | 待攻(动 signals 需过 L noise-reject 双 1.00) |
| B5 | 内容失真:学到但极性翻/数字漂 | "11 句上限"学成 "at least 11 sentences" | 待量化(取证 C 出数) |
| B6 | 读侧织入尾巴 17% | headings 类规则注入未织 | 低优先(oracle 已 0.96) |

## 改进提案池

| # | 提案 | 对应瓶颈 | 性质 | 状态 |
|---|---|---|---|---|
| P1 | 撤回意图门:裸 retire 需撤回形状 span 证据(复用 _WITHDRAW_PAT,span 级) | B1 | 零 LLM 守卫,LightMem "delete 仅限直接冲突/显式撤回" | **已实现**,L 过(revoke 1.00),链式机制验证中 |
| P2 | 同事实→update:重复 new / 零变化 contradict 转 reinforce(数字变化豁免) | B2 | 零 LLM 守卫,LightMem "同事实→update" | **已实现**,L 过(dedup 1.00) |
| P3 | 写侧覆盖复核:过筛 span 无对应 op 时,一次点名补抽调用(镜像读侧数字复核) | B3 | 协议层,+1 异步调用 | 提案 |
| P4 | 抽取 op 保真门:op 文本的数字必须出现在源 span;极性词族(max/min、否定)与 span 一致,不一致丢弃或降级 new | B5 | 零 LLM 守卫 | 提案 |
| P5 | 筛选层规则形状扩充:命令否定式(no/avoid/don't + 名词)与格式名词(headings/underscore/fencing) | B4 | 正则,需守住 noise-reject 1.00×2 与 distractor 误触率 | 提案(动刀谨慎) |
| P6 | flush 批次 4→2:减小批内干扰,代价抽取调用×2 | B3/B5 | 参数 | 提案(先 P3/P4) |
| P7 | store 版本链治理:supersede 链同文本折叠(写时,而非读时) | B2 | 零 LLM | P2 已部分覆盖,观察 |

## 轮次日志

- **循环1(收口)**:B1/B2 → P1/P2 已实现。pytest 459 绿;L qwen 0.926
  (掉分四例全为既有类别,非门引起;revoke/dedup 1.00)。e-05/e-02 链式复跑
  owner 指标持平(单集噪声内)。机制取证(3 并行分析)结论:
  - P2 机械有效:e-05 重复族 3→1(修订垃圾链消失);但漏数字变体近重复
    (e-02 出现 "at least 11/at most 11/at least 17" 三 id 无链家族)。
  - P1 未堵住:e-05 无接替者 retire 19→25(方差混杂;且 merge 只给
    targets[0] 记 supersedes,记账虚增无主 retire)。
  - **绑定性故障 = W2(8/13 occ),R1=0**。三种死法:
    a. supersede 链错向+继承者死亡(e02-s01:对的 "at most 11" 被错的
       "at least 17"(实为 postmortem 规则误 contradict 到 email cap)顶掉,
       后者又死,全链无活口)—— 4 occ;
    b. 无接替者裸杀(e05-c19 三条同规则全灭、e05-c07 活 4 版后
       supersedes=None 死)—— 2 occ;
    c. merge 连坐(e05-c24 标识符规则并进模块名条目,模块名 facet 一更新
       整条陪葬)—— 2 occ。
  - 保真分析:13 个 should_fire cid 只有 1 个有 faithful 活条目;另发现
    content_tokens 词干化盲点(politeness/friendliness 不折到
    polite/friendly,量表低估幸存质量)。

## 循环2 方案:store 层继承者存活不变量(version-stack pop)

设计(合成建议 + 我的收敛,LightMem update/delete 分离的机械化):
1. **反向指针** `superseded_by`:被 contradict/merge 淘汰的条目记录谁替了它
   (merge 给**每个** target 记,修记账伪影);
2. **retire 语义分级**:抽取层撤回门从"拦截"升级为"标注"——有撤回证据的
   retire 带 `withdrawal=True`(硬死,终结链);无证据的照旧拦截。
   consolidation 冲突 retire 由 sanitizer 附 `heir_id`(内容重叠最大的幸存者);
3. **链弹出**:无撤回证据且无继承者的 retire 落到 X 时,若 X.supersedes=A 且
   A.superseded_by=X,则 A 复活(版本栈 pop)——直接覆盖死法 a;
   有 heir 的 retire 不弹(facet 已有活的统治者);withdrawal 不弹(用户终结全链)。
4. 撤回门重叠判据从"非空交集"强化为 overlap_is_reference(≥2 token 或数字锚)。

预期覆盖 6/8 W2 occ;死法 c(merge 连坐)需后续 facet 级 supersede,本轮不做。
风险:复活真撤回的规则(靠 withdrawal 标志隔离)、e-02 数字变体无链家族
在不变量下共存活(读侧 rule 8 newest-wins 兜底,观察)。

### 循环2 收口

实现:schema `superseded_by` / store retire 三分级+版本栈 pop / merge 全员
反向指针 / 同态契约测试参考 Gold 机同步升级(fuzz 加三种 retire 风味,
202 用例)。裁判:pytest 465、L qwen 0.944(revoke/dedup 1.00)。
链式机制指标:**无主 retire e-05 25→15、e-02 14→4;pop 实际触发 3 次;
e-05 STATE 0.67(历史最好)**。owner 指标单集仍在噪声内摆动(e-05
per-memory 三跑 0.44/0.33/0.22 vs STATE 0.58/0.56/0.67 反向),再次确认
单集 owner 指标不可用于单修复验证。
残留:gold 关键条目仍经两个"有牌照"通道死亡——被授证的 withdrawal retire
与带 heir 的冲突消解。**新发现:gold 每集本有 12-13 个真撤回,retire 量级
没错,错在瞄准。**

## 循环3:contradict facet 相容门(进行中)

死亡通道实锤(e-02 最新 store):postmortem 的"至少17句"被 contradict 到
email 句数上限上,新文本还被幻觉成 "in emails"——合法外形、继承者活着,
撤回门与不变量都无法触及。
修法:contradict 的最佳 grounding span 推断任务 kind,与靶子 kind 双向已知
且不相容 → 降级为 new(内容保留,击杀取消)。复用 infer_task_kind/
kind_matches,缺信息不拦截。单测 3 例;pytest 468。
教训:L 与链式验证不可并行打同一端点(自造 429 → ops=[] 假阴性)。

### 循环3 收口

链式:e-05 **0.56/0.56(该集历史最好)**、e-02 0.33/0.09(恶化,查明
**非门误伤**——无共活污染)。e-02 真死因改判:**B5 出生即翻极性**
("11句上限"被抽成 "at least 11 sentences",正确版本从未存在,一切
击杀守卫无从救起)。循环1-3 已提交 `e47130e`。

## 循环4:P4 op 极性保真门(收口)

new/contradict 带数字的 op:数字溯源到 span,span 与 op 的界限词族
(min 族:至少/at least/no fewer than vs max 族:最多/不超过/under/at most)
冲突 → 丢弃 op。理由:**缺席的规则下次重述可自愈,反转的规则永不自愈且
主动有害**。词族单侧明确才判,双侧或无 → 放行。单测 4 例;pytest 472。
L qwen 0.926(dedup/revoke 1.00,P4 零成本)。

## 阶段验收(进行中)

- **ling L 全栈复核:0.796 → 0.870(循环1)→ 0.907(循环1-4)**,dedup
  0.17→1.00,revoke 1.00 —— 双骨干同向,anti-overfit 通过。
- qwen L 今日多跑 0.889-0.963 摆动(失败项均为既有类别:原子化拆分、
  gist 措辞、model 用 reinforce 代 contradict),均值较基线 0.963 略低
  ~0.03,是方差还是守卫栈小成本待两连跑判定 —— 观察项。
- qwen E1 ×4 合并验收(守卫栈全量,单跑):
  **per-task 21/43 = 0.49(改进前 0.43)、per-memory 22/48 = 0.46
  (改进前 0.37)**,双指标越 haiku 带(0.38-0.39/0.29-0.35)。
  STATE 均值 ≈0.62;e-01 0.62/0.62、e-05 0.56/0.56 单集历史最好;
  e-02 仍是落后集(0.50/0.22,残留=B4 筛选层丢 verb-buried/emoji-faces
  类 + 极性翻转变体)。
- ling 链式 e-05 单集 anti-overfit 复核运行中。

## 下一轮候选(按证据)

- B4 筛选层规则形状(e-02 的 c16/c04 是 3/13 的 W1 主力,双集稳定复现);
- e-05 merge 连坐的 facet 级 supersede(循环2 遗留);
- qwen L 均值较基线 ~-0.03 的两连跑判定;
- 消融检查(阶段末做一次):把守卫栈逐个关掉跑 L,确认每道门仍在挣饭吃,
  防守卫堆积腐化。

## 阶段收口(2026-07-31)

- ling 链式 e-05 单集:**0.67/0.67,STATE 0.56** —— 免费弱骨干在同集上
  越过 qwen(0.56/0.56),守卫栈对弱模型的兜底作用实证成立。
- anti-overfit 全链通过:每道门在 qwen(L 带内、四集合并 0.49/0.46)与
  ling(L 0.796→0.907、链式 0.67/0.67)双侧同向。
- 提交:`e47130e`(循环1-3)+ `809d9dc`(循环4+验收)。

## 骨干切换 + write-think 对照(2026-07-31 下午)

Owner 裁定:主模型 ark:deepseek-v4-flash(plan 通道,thinking 关);
qwen/ling 降为辅助验证,只在主模型结果确定后开。judge 主通道(coding/v3)
配额耗尽,按预案切备用 plan key,**裁判模型 deepseek-v4-pro 不变,尺子可比**。
(2026-08-02 owner 指令「所有 llm 走回主 api 的 ark」:探活确认 coding/v3
配额已恢复,产品端与 judge 端一并切回主通道,备用 key 留在 .env 注释里。
**运维坑（已修复）**:过去产品侧只看进程里的 `ARK_*`,而 bench 从项目
`.env` 读取 `LLM_*`,两条配置链会漂移。现在两侧统一读取
`LLM_API_KEY` / `LLM_BASE_URL`:进程环境优先,本地运行自动回退到项目
`.env`,不再需要导出 `ARK_*`。)
基建:llm.py Ark 通道("ark:" 前缀 + ":think" 后缀语法)、writer 独立模型键
(MT_WRITER env 覆盖,A/B 不改文件)、think 预算头寸、judge 跨进程限速器
(6 路并发曾把共享 judge 通道打爆——AIMD 桶是进程内的,N 进程合力冲垮;
文件锁全局 150ms 间隔后 7 路稳定)。

### deepseek-v4-flash 基线(thinking 全关)

- oracle **1.00/1.00 满分**(qwen 0.95/0.96,与 glm 持平)
- robustness 41/46;L 0.870(dedup 1.00)
- real ×4:e-02 0.33/0.27(S0.52)/ e-05 0.67/0.67(S0.77)/
  e-09 0.23/0.35(S0.54)/ e-01 0.69/0.69(S0.83)
- **合并:per-task 21/44=0.48,per-memory 24/50=0.48**(qwen 同代码 0.49/0.46)

### write-think 对照(writer=:think,读侧不变)

- real ×4 合并:per-task 17/42=**0.40**,per-memory 20/47=**0.43**(全输)
- L **0.815**,其中 **diff-supersede 0.17**(基线 0.83)——思考型 writer
  在 supersede 目标选择上大幅劣化,与 qwen+reasoning 时 L 掉分同构
- STATE 均值 0.695 vs 0.665(略升,但 op 质量与 owner 指标双降)

**裁定:写侧 thinking 关闭保持默认。** "异步=延迟免费" 成立,但 deepseek
的思考让破坏性 op 的瞄准变差,收益为负。单跑数据,方向与 qwen 先例一致。

## 循环5-6 + 阶段验收(2026-07-31 晚)

- 循环5(筛选层双机制):抱怨式纠偏模式(+3)/短耐久锚回溯两句。两个实测
  缺口(emoji-faces 抱怨式、underscore 指代分离)复检通过;c16/c15 改判
  W1b(过筛后抽取丢,非筛选责任)。
- 循环6(一次性例外门):deepseek 骨干新病——一次性例外折成持久规则,
  noise-reject-task 破到 0.67(先于循环5,骨干切换即有)→ 门后回 1.00,
  类别例外零误伤。提交 `9448813`。
- **阶段验收(deepseek,循环1-6全栈,单跑)**:
  e-02 0.44/0.18(S0.60)/ e-05 **0.78/0.78**(S0.75)/ e-09 0.38/0.47
  (S0.58)/ e-01 0.77/0.77(S0.73)
  **合并 per-task 26/44 = 0.59,per-memory 27/50 = 0.54**
  (轨迹:0.33/0.23 → 0.43/0.37 → 0.49/0.46 → 0.48/0.48 → **0.59/0.54**)
- 辅助验证(owner 协议,主模型结果确定后开):qwen L 0.926、ling L 0.889,
  两者 dedup/noise-reject-task/revoke 全 1.00 —— 守卫栈三骨干同向。
- 残留:e-02 仍是落后集(per-memory 0.18,verb-buried 类 W1b 抽取丢 +
  极性变体);下一轮候选:e-02 W1b 深挖(P3 写侧覆盖复核)、merge 连坐
  facet supersede、守卫栈消融。

## 异步预算 A/B(2026-07-31 深夜):负结果入账

Owner 门槛:异步侧 +0.5 摊销调用需买到 ≥+0.1 owner 指标。实现覆盖复核
(首抽沉默的规则形状 span 二遍点名)+ 出生保真投票(op vs 源 span 三点
判据),中途被 L 抓出三个二遍行为罪并机械修正(偷懒 reinforce 顶掉
contradict → 二遍禁 reinforce;撤回中复活规则 → withdrawal-span new 门;
投票判据误伤放宽协议 → 判据收窄为方向/否定/数字)。

**A/B 裁决(每臂 3 轮 ×4 集,~130 判定点,ON/OFF 轮区间不重叠):**
- OFF:per-task **0.515**,per-memory **0.514**,STATE 0.69
- ON: per-task 0.402,per-memory 0.397,STATE 0.63
- **+0.5 调用买到 −0.11 → 默认 OFF**(代码与 MT_RECHECK/MT_VERIFY 环境
  开关保留)。机理:守卫栈之后写路径的绑定约束已从"抽不够"变为"店内
  扰动"——复核补的多是首抽正确忽略的 op,进店引发 churn 与稀释。
- 修正入账:上一验收的 0.59/0.54 是高抽签;**当前真实水位 0.515/0.514**
  (三轮合并)。轨迹:0.33/0.23 → 0.515/0.514(全部循环)。
- 顺带产出(保留):withdrawal-span new 门(通用防复活)、二遍禁
  reinforce 原则、A/B 用 env 开关基建、三轮合并的验收纪律。

## 循环7:三项并验(2026-08-01)

1. **merge 连坐修复**:a) 跨 facet 合并门——key 不同且文本两两 Jaccard<0.5
   的 merge 拒绝(近重复的跨 key 合并放行,保住维护窗口三重复类);
   b) **受害者指针泛化 pop**——无主非撤回死亡时,所有 superseded_by 指向
   死者的条目集体复活(合并体死亡=解散合并,不再连坐带走源规则)。
   同态 Gold 机同步(pop 按 heir 指针全量)。单测 3 例,pytest 484。
2. **守卫栈消融**:MT_ABLATE 环境开关按名跳过七道抽取门,BENCH_RUN_DIR
   隔离 checkpoint;all-on 参照 + 7 路单关 L 对照运行中。
3. **跨语言撤回盲区取证**:e-01(zh 话语×en store)链式跑,钩住
   run_extraction 的 flags 统计撤回意图门的拦截明细——判定"合法 zh 撤回
   被门挡住导致僵尸规则"是否真实发生及其量级。

### 循环7 三项裁决(2026-08-01)

1. **merge 连坐**:跨 facet 合并门 + 受害者指针泛化 pop 落地(单测 3,
   Gold 机同步)。e-05 两跑 STATE 0.76 / headline 0.80,无合并连坐复发。
   **新发现**:store 里仍有 5 条**抽取出生即复合**的分号条目(ATOMISE
   指令被违反)——连坐风险的另一半在抽取层,列为下一候选(机械分号拆分,
   注意豁免 "— except" 例外折叠)。
2. **守卫栈消融(L 单跑,all-on 参照 0.944)**:
   oneoff −0.074、wnew −0.055 = **实证挣饭**;intent/facet 各 −0.018(小,
   但链式域另有取证依据);ground/fidelity L 持平(裁判域在链式,维持);
   **dedup 关掉 +0.019(噪声内,列观察——它的链式价值是修订垃圾链坍缩)**。
   无互相抵消迹象,栈保持现状。
3. **跨语言撤回盲区**:e-01(zh×en store)flags 取证——撤回意图门拦截的
   2 个 retire 目标均为 gold 活规则(**正确拦截,是救援不是误杀**);
   期末 store 僵尸规则(gold 死 store 活)= **0**。词根+数字桥当前够用,
   不加词表,文档化测试保留为哨兵。

## 循环8:ATOMISE 机械执行 + 全套测试(2026-08-01)

抽取层出生即复合的分号拆分(共享 evidence_id;`— except` 折叠豁免、
引号/反引号内分号算内容、任一半内容不足不拆;复合 contradict 只让第一半
留 target,其余落 new——两个 contradict 打同一目标会造假 supersede 链)。
单测 5 例,pytest 489。

**全套测试结果(deepseek 全栈)**:
- L **0.926**(dedup/diff-supersede/revoke/noise×2 = 1.00)
- robustness **42/46**(骨干基线 41/46,带内)
- real 两轮合并:per-task **0.488**、per-memory **0.495**、STATE 0.68
  —— 对标基线 0.515/0.514/0.69,**在噪声内持平**(基线单轮区间 0.47-0.59)
- 机制验证:分号复合活条目 5 → 2(残留 2 例是拆分后仍带分号的合法单规则
  文本,非复合)

**裁定:循环 7-8 机制上成立(单测+取证),owner 指标上中性。** 不撤销
(它们关的是罕见但不可逆的破坏路径:合并连坐、复合条目不可部分覆盖),
但**不再指望这条线出分**。

### 下一瓶颈已明确:e-02 是系统性离群集

两轮 per-memory 1/11、1/9(≈0.10),**两轮一致,不是方差**;同期
e-01 0.67/0.92、e-05 0.67-0.78。全部剩余损失高度集中在这一集,
下一循环应只针对 e-02 做逐 miss 取证,而不是继续加通用守卫。

### 运维教训
- 本机内存 ~2GB,10 个 bench 进程后仅余 353MB:**并行上限由内存定,不是
  judge 限速**;
- 查进程状态别接 `head`(截断造成"进程全灭"误判)、内存用 `free -m`
  (`free -g` 取整误导);重定向日志有 stdout 缓冲,空日志 ≠ 死进程。

## 循环9 + bench 修正 + 循环7-8 效果裁决(2026-08-02)

### 循环9:撤回瞄准检查(`4fa2227`)

e-02 击杀取证抓到撤回**瞄错靶**:用户撤「33 headings」规则,系统杀掉
「11 columns」规则;撤「verb 后置」规则,杀掉「写完整句子」。原判据只验
"某撤回 span 与靶子达到 reference 强度重叠",而 include/at least/sentence
这类通用规则词自己就能凑够——**重叠证明的是 span 提到了靶子共享的词,
不是 span 点名了靶子**。修法:提取引号内的指代 → 全部活条目打分 →
受害者必须是最佳匹配,否则**改瞄用户真正点名的那条**(救健康规则 +
兑现撤回意图)。L 0.926,revoke/dedup/diff-supersede/noise×2 全 1.00。

### bench 修正(`dda6f23`):只改两条,且否掉了自己的批量方案

批量审计两版判据都不可用:宽判据(轮次任务 ≠ gold scope)156 处,但那是
bench **故意**的跨任务陈述设计;严判据(只看陈述句)55 处,仍大量假阳性
(陈述句常同时含任务请求与规则)。**scope 忠实性无法机械审计到支撑批量
改写的精度,只有逐条读原文才作数** —— 记入纪律。
实改两条:e02-c23 / e02-s04 的 scope postmortem → email(话语逐字说
"per email",全文无 postmortem,轮 context 亦为 email);连带在 email 轮
移除严格不可满足的 e02-s01 期待(seq48/56),保留 seq44(恰好11句可同时
满足)与 seq60(report 轮)。

### 循环7-8 效果 A/B(修正后尺子,MT_ABLATE=atomise,mergegate,pop)

| 臂 | per-task | per-memory | STATE |
|---|---|---|---|
| **ON(全栈)** | **0.459** | **0.505** | 0.69 |
| OFF(三机制全关) | 0.430 | 0.430 | 0.68 |

**+0.075 per-memory,循环7-8 确实有效** —— 此前"指标中性"的判断是被
两个混杂因素掩盖:旧尺子的 scope 缺陷 + 循环9 才修的瞄错靶撤回。
增益全部来自 e-02(2/9,1/7 → 6/9,4/9)与 e-01(4/12,4/13 → 6/13,7/12);
e-05 反而略降(8/9,7/9 → 6/9,6/9),该集本就高位,属噪声或轻微代价,
列观察。**当前真实水位:per-task 0.459 / per-memory 0.505(2 轮 ×4 集)。**
