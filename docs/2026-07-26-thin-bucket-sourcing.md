> **我的独立复核（2026-07-26）**：抽查两个供给量最大的源,均成立——`allenai/natural-instructions` LICENSE 确为 **Apache-2.0**（task_goal 主力）,`google/eng-practices` LICENSE 确为 **CC BY 3.0 Unported**（reasoning_policy 主力）。
>
> **产出**：189 条候选 = reasoning_policy 139 + task_goal 50;判分方式 judge 147 / mechanical 42。对照配额（reasoning ~100、task_goal ~70）:**reasoning 超供 39%,task_goal 缺口 20 条(29%)**,处置见文末补充。
>
> **最值得记住的一条裁定**：NeurIPS / ICLR / ICML 三家的 reviewer guidelines **全部因无许可被弃**——页面无版权声明、无 terms、无授权,而 ICML 页面唯一的明示授权是准许复用 **logo**,反衬出对正文的沉默是刻意的。这三家本是这类语料的第一直觉来源,结果一个都不能用;替代路径是 PREreview toolkit（CC BY 4.0）与 ACL Rolling Review（MIT，慎用）。
>
> 另一个易踩的坑：**PLOS 的论文是 CC BY,但 PLOS 网站内容全权保留**;同理 PRISMA/CONSORT 作为期刊论文是 CC BY,但 equator-network 站点再分发的 checklist PDF 附加了禁止修改条款——**永远从期刊/PMC 版取并引那个 DOI**。

# 两个薄桶（reasoning_policy / task_goal）的 sourcing plan

---

## 1. 裁定表

### 1.1 用（licence 已在 primary artefact 核实，可直接摄取）

| source_id | 许可 | 许可出处 URL | 供给桶 / 预估条数（去重后） |
|---|---|---|---|
| `prereview_toolkit` | CC BY 4.0 | https://zenodo.org/api/records/5484087 | A 45–75 / B 15–25 |
| `turing_way_peer_review` | CC BY 4.0（文档部分；MIT 只覆盖软件） | https://github.com/the-turing-way/the-turing-way/blob/main/LICENSE.md | A 20–30 / B 10–15 |
| `nsf_merit_review` | US Gov work，公有领域（仅文本，图不取） | https://www.nsf.gov/policies/reuse.jsp | A 8–16 / B 7–14 |
| `prisma_2020` | CC BY 4.0 | https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1003583 | A 13–21 / B 2–4 |
| `consort_2025` | CC BY 4.0 | https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1004587 | A 9–14 / B 3–5 |
| `osf_prereg_template` | CC0 1.0 | https://api.osf.io/v2/preprints/epgjd/?embed=license | A 14–21 / B 6–9 |
| `gsrrf_2023` | CC BY 4.0 | https://pmc.ncbi.nlm.nih.gov/articles/PMC10514995/ | A 6–8 / B 5–7 |
| `strobe_ee_2007` | CC BY | https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.0040297 | A 7–13 / B 1–2 |
| `spirit_2025` | CC BY | https://pmc.ncbi.nlm.nih.gov/articles/PMC12035670/ | A 4–6 / B 2–3（须与 CONSORT 去重） |
| `prisma_p_2015` | CC BY | https://pmc.ncbi.nlm.nih.gov/articles/PMC4320440/ | A 4–7 / B 2–3（只取 item 6/7/16/17） |
| `google_eng_practices` | CC BY 3.0 Unported | https://github.com/google/eng-practices/blob/master/LICENSE | A 36–60 / B 24–40 |
| `openssf_badge_criteria` | MIT OR CC-BY-3.0+ | https://github.com/coreinfrastructure/best-practices-badge/blob/main/LICENSE | A 22–30 / B 8–10 |
| `openssf_concise_guides` | Apache-2.0 | https://github.com/ossf/wg-best-practices-os-developers/tree/main/LICENSES | A ~20 / B ~10 |
| `threat_modeling_manifesto` | CC BY 4.0 | https://www.threatmodelingmanifesto.org/ | A ~10 / B ~8 |
| `wikinews_policies` | CC BY 4.0（2024-12-16 后）/ CC BY 2.5 | https://en.wikinews.org/wiki/Wikinews:Copyright | A 30–52 / B 10–18 |
| `super_natural_instructions` | Apache-2.0（**仅** Definition/Categories/Examples；Instances 不取） | https://github.com/allenai/natural-instructions/blob/master/LICENSE | A 50–105 / B 100–195，外加 76 个 category 动词轴 |
| `bloom_newton_2020` | CC BY 4.0 | https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2020.00107/full | A 4–8 / B 36–72（作为生成器而非语料） |
| `self_instruct_seeds` | Apache-2.0 | https://github.com/yizhongw/self-instruct/blob/main/LICENSE | A 10–20 / B 5–10，外加 175 条风格锚 |

### 1.2 慎用（许可可用但带条件，须先满足条件）

| source_id | 许可 | 许可出处 URL | 供给 | 附加条件 |
|---|---|---|---|---|
| `acl_rolling_review` | MIT（LICENSE 在 repo root，但 copyright 行写的是上游 Jekyll 主题作者） | https://github.com/acl-org/aclrollingreview/blob/main/LICENSE | A 54–81 / B 6–9 | 只取"规则的想法"改写成第一人称，**不逐字复制 H1–H17 表**；同时发 support@aclrollingreview.org 求书面确认，回信后升级为"用" |
| `rust_api_guidelines` | Apache-2.0 OR MIT | https://github.com/rust-lang/api-guidelines/blob/master/LICENSE-APACHE | A 6–9 / B 2–3 | 只挖 documentation / future-proofing / flexibility 章；naming 与 interoperability 章会把 output-form 污染进 A 桶 |
| `apache_voting` | Apache-2.0 | https://www.apache.org/licenses/LICENSE-2.0 | A 4–8 / B 2–4 | 只取 veto-needs-justification 一族，不做大规模采集（本组性价比最低） |
| `wikipedia_wp_v` | CC BY-SA 4.0 | https://en.wikipedia.org/wiki/Wikipedia:Copyrights | A ~14 / B ~1 | ShareAlike。走 clean-room：只取思想，句子全部重写，禁止逐句 paraphrase；provenance 字段标 `copyleft_derived=true`，交付前人工签字 |
| `wikipedia_wp_nor` | CC BY-SA 4.0 | 同上 | A ~13 / B ~2 | 同上（本源是 fact/inference/speculation 分离的最佳来源，值得走这个流程） |
| `wikipedia_wp_npov` | CC BY-SA 4.0 | 同上 | A ~11 / B ~4 | 同上 |
| `wikipedia_wp_rs` | CC BY-SA 4.0 | 同上 | A ~17 / B ~1 | 同上；A 桶单页产出最高 |
| `wikipedia_supplementary` | CC BY-SA 4.0 | 同上 | A 18–30 / B 0 | 同上，且约 25% 是 diction/output-form，须先过桶判定 |
| `uk_code_of_practice_stats` | OGL v3.0 | https://code.statisticsauthority.gov.uk/copyright/ | A 12–20 / B 3–5 | 站点 JS 渲染，practice 原文没抓下来；**必须从 Code 3.0 PDF 重抽条文**再入库。许可已核实，条文文本未核实 |
| `promptsource_p3` | Apache-2.0 | https://github.com/bigscience-workshop/promptsource/blob/main/LICENSE | B 50–120 raw → 实际约 20 | 先按 `original_task: false` 过滤再看；过滤后不足 50 条可用就整源丢弃 |
| `flan_v2` | Apache-2.0 | https://github.com/google-research/FLAN/blob/main/LICENSE | A 8–18 / B 2–7 | 10.5k 行模板里只有约 5 条不同规则，禁止规模化挖矿，手取即可 |
| `natural_instructions_v1` | Apache-2.0 | https://github.com/allenai/natural-instructions-v1/blob/main/LICENSE | A 45–85 / B 35–65（潜在） | **阻塞**：61 个 task 文件在任何 live primary source 都取不到（repo 无 tasks/ 目录，instructions.apps.allenai.org 无响应，HF 镜像全是 v2）。不要排进 build，先找 AI2 或 Internet Archive 快照 |
| `dolly_15k` | CC BY-SA 3.0 | https://creativecommons.org/licenses/by-sa/3.0/ | 8 条 | 倾向不取：为 8 条定义背 ShareAlike 不划算。八分类是事实性分类体系（不受版权保护），自己写描述即可 |

### 1.3 弃

| source_id | 许可 | 许可出处 URL | 弃因 |
|---|---|---|---|
| `neurips_reviewer_guidelines` | 无 | https://neurips.cc/Conferences/2025/ReviewerGuidelines | **无许可**。整页 footer 只有 cookie 声明，无版权声明、无 terms、无授权。且 NeurIPS 自己的投稿条款要求作者/审稿人向其授权，说明该组织有权利意识而只是没给我们——比"沉默"更糟 |
| `iclr_reviewer_guide` | 无 | https://iclr.cc/Conferences/2025/ReviewerGuide | **无许可**，同上。唯一有价值的规则（SOTA 不构成拒稿理由）在 ARR H5 里有等价表述 |
| `icml_reviewer_instructions` | 无 | https://icml.cc/Conferences/2025/ReviewerInstructions | **无许可**。页面上唯一的明示授权是准许复用 ICML **logo**，反衬出对正文的沉默是刻意的。neurips.cc / iclr.cc / icml.cc 同一 CMS，整族一次性拒，不要逐年复查 |
| `plos_reviewer_guidelines` | All rights reserved（网站内容，区别于 PLOS 的 CC BY 论文） | https://plos.org/terms-of-use/ | 最容易骗人的一个：PLOS 的**论文**是 CC BY，**网站内容**不是。所需内容可经 PREreview（CC BY 4.0，明示改编自 PLOS Peer Review Center）合法取得 |
| `nature_springer` | All rights reserved，明文禁止再分发 | https://www.springernature.com/gp/legal/general-terms-of-use/15067848 | 条款明文："not permitted to be distributed in any form"。且 referee 页 303 跳转 idp.nature.com 鉴权，摄取等于绕过访问控制。两条独立理由 |
| `science_aaas` | All rights reserved，教育用途且明文排除商业 | https://www.science.org/content/page/terms-service | 明文"does not authorize the use of content under any circumstances for commercial purposes"，正好卡在我们必须过的那条轴上 |
| `cope_guidelines` | CC BY-NC-ND 3.0 | http://creativecommons.org/licenses/by-nc-nd/3.0/ | NC 卡商用，ND 卡改写（改写成第一人称正是我们的核心操作）。双重否决。内容本身也大量是机构流程，本就不满足 rule 2 |
| `acm_ieee_guides` | 无法确定 | https://www.acm.org/publications/policies/roles-and-responsibilities | **primary artefact 打不开**（acm.org 403；ieeeaccess / journals.ieeeauthorcenter 掉连接或空 body）。按 rule 1，取不到许可即弃，不凭记忆认证。且两家都是订阅出版商，走正式 permission 流程，期望值低 |
| `cochrane_handbook` | All rights reserved（© Cochrane / Wiley） | https://www.cochranelibrary.com/help/permissions | 本族最大的陷阱：内容质量最好、免费可读，但免费可读 ≠ 可再分发。授权仅限"Cochrane review 的撰写/编辑/评审"。硬弃，且要写进 ingestion checklist 防止有人再放进来 |
| `grade_handbook` | 无开放许可，需向编辑逐案申请；配套 JCE 系列多为 CC BY-NC-ND 或付费墙 | https://gdt.gradepro.org/app/handbook/handbook.html | permission-on-request 不是 licence。想要 certainty-rating 框架就从某篇 CC BY 的方法学论文里复述（想法不受版权保护，表达才受），provenance 指向那篇 |
| `care_statement` | 专有，明文非商业（© IMI LLC） | https://www.care-statement.org/copyright | "These documents may not be used commercially." 明确 NC。且内容偏叙事完整性，本来就接近 output-form，损失极小 |
| `prisma_scr` | 无法核验（green OA 作者稿无许可声明；出版版 Annals 全权保留） | https://www.acpjournals.org/doi/10.7326/M18-0850 | Unpaywall 报 oa_status=green、license=null。**机构库能下载 ≠ 有再分发权**，这是本族的常见误判。替代品：GSRRF（CC BY）覆盖同样的 review-type 选择议题 |
| `crsh_prereg` | GPL-3 | https://github.com/crsh/prereg/blob/master/DESCRIPTION | GPL-on-data，copyleft 会传染到 benchmark repo。它打包的上游模板各有各的许可，直接去上游取；最大的那个（OSF Prereg）已经是 CC0 |
| `equator_prisma_sites` | 无 CC；站点条款要求保留声明且**禁止修改** | https://www.equator-network.org/terms-of-use/ | 事实上的 ND 条款（"no material may be modified, edited or taken out of context"）。核心陷阱：PRISMA/CONSORT/SPIRIT/STROBE 作为**期刊论文**确是 CC BY，但这些站点再分发的 checklist PDF 条款更严。永远从期刊/PMC 版取并引那个 DOI。保留其作为 discovery tool |
| `linux_kernel_process_docs` | GPL-2.0-only | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/plain/COPYING | 已核对 raw source：submitting-patches.rst 等文件均无 SPDX 头，按 COPYING 即 GPL-2.0-only；而 maintainer-handbooks.rst **有** SPDX 头，说明 docs tree 是刻意 GPL 而非漏标。GPL-on-data 硬弃。别被 docs.kernel.org 渲染页只显示"©the kernel development community"误导 |
| `owasp` | CheatSheetSeries 为 CC BY-SA 4.0；www-community repo **无 LICENSE** | https://github.com/OWASP/CheatSheetSeries/blob/master/LICENSE.md | 两个独立问题：BY-SA 是 copyleft-on-data；而威胁建模页实际所在的 www-community repo 的 licence 字段为 null，唯一授权说法是站点 footer 一句话，未附着于 artefact。用 Threat Modeling Manifesto（CC BY 4.0）替代 |
| `ifcn_code_of_principles` | 无（仅 © 2026 IFCN） | https://ifcncodeofprinciples.poynter.org/ | **无许可**，且找不到任何 terms 页授予（poynter.org/terms-of-service 为 404）。损失是真实的（Principle 2 是本族最紧的 source-hierarchy 规则），但按 rule 1 只能弃；想要就写信要 CC BY |
| `bbc_editorial_guidelines` | 无开放许可；BBC 条款仅许个人/非商业/教育、不得修改 | https://www.bbc.co.uk/usingthebbc/terms/ | 商用与"修改"两条都不过。诚实声明：bbc.co.uk / bbc.com 在本环境不可抓取，许可结论来自 BBC 条款页的二手回收，未直接读到 primary artefact——无论如何按 rule 1 都是弃 |
| `reuters_handbook` | 未发现任何许可声明（Thomson Reuters 版权） | https://www.reuters.com/about-us/ | 公开可读的 PDF 里没有版权/许可声明，Reuters 页面也未授权。"网上能读到"不是 licence。第二条独立理由：手册自称 guiding principles 而非规则，是散文形态，违反 rule 3 |
| `ap_news_values` | All rights reserved，明文"may not be published, broadcast, rewritten or redistributed" | https://apnews.com/about/terms-of-service | 明文禁止的正好是"rewritten"，即我们 pipeline 的核心动作。诚实声明：ap.org / apnews.com 本环境不可抓取，结论基于 AP 通行版权声明与其执法记录，非直读 |
| `trust_project` | 无版权授权，且对 8 项指标主张商标 | https://thetrustproject.org/trust-indicators/ | 无许可 + 商标主张。同时也是本族产出最低的一项（8 条短指标，其中数条是编辑部组织承诺而非用户可持有的偏好），弃掉几乎无成本 |
| `ofcom_broadcasting_code` | 无法在 primary artefact 核验；二手可见的是"准确复制、不得置于误导语境"的自定授权，非 OGL | https://www.ofcom.org.uk/about-ofcom/our-website/copyright | 两条：(1) ofcom.org.uk 对所有路径 403，读不到 primary artefact，按 rule 1 即弃；(2) 即便按二手条款，"reproduce accurately"最自然的读法是禁止修改，而我们全程在修改。特意记录，因为它是 BBC 的显然替代品，但同样不过关 |
| `unesco_fake_news_handbook` | 二手报为 CC BY-SA 3.0 IGO，**无法在 primary artefact 确认** | https://unesdoc.unesco.org/ark:/48223/pf0000265552 | unesdoc 403，落地页无许可声明，PDF 文本层抽不出（唯一信号是嵌入图元数据名为 `by-sa [Converted].eps`，佐证但不构成声明）。按 rule 1 弃。且即使确认也是 ShareAlike，产出远低于 Wikinews，不建议回头核验 |
| `big_bench` | Apache-2.0（许可没问题） | https://github.com/google/BIG-bench/blob/main/LICENSE | **按产出弃**，不是许可问题：1046 个 task.json，description 平均不到十个词，是标签不是规则（"Evaluate claims as true or false"），全族性价比最差。次要理由：每个文件都带作者要求的 canary 串，明确请求不要进入训练语料，再发布进会被爬的 benchmark 与其意图相悖。只保留 `keywords` 词表作为 A 桶的组织轴 |
| `bloom_university_handouts` | CC BY-NC-ND 4.0（Arkansas）/ CC BY-NC-SA 4.0（Texas A&M）/ 多数机构 PDF 无许可 | https://creativecommons.org/licenses/by-nc-nd/4.0/ | NC 直接出局，Arkansas 的 ND 还额外禁止改写。无许可的机构 PDF 按 rule 1 同样弃。特意列出，因为这些页面在 "Bloom taxonomy verb list" 的搜索结果里排在最前，是本族最可能被误摄取的一批；等价内容在 Newton et al.（CC BY）里更好且有证据支撑 |

---

## 2. 供给量核算

### 2.1 现有存量

已提取 189 条，桶分布：

| | 原始 | 去重后 | 过质量闸后（见 §5 gate） |
|---|---|---|---|
| reasoning_policy | 139 | ~120 | ~100–105 |
| task_goal | 50 | ~38 | ~28–32 |
| 合计 | 189 | ~158 | ~130 |

去重理由：语料内已有明确重复。`WP:NOR`"不要把两个来源缝成第三个结论"与补充页那条几乎逐字相同；"Never hand me Wikipedia"与"Wikipedia 是线索不是引用"同义；"surprising claim 需要多个来源"与"extraordinary claims 更高证据门槛"同义；self-published 有两条、editorial oversight 有两条。task_goal 更严重：`commit to a pick`（OpenSSF）/`comparison 必须选一个`（Bloom）/`commit to one`（PromptSource）三条同义；`accept/reject verdict`（SNI）/`assessed judgement not description`（Bloom）/`decision and confidence not balanced overview`（Turing Way）三条同义；`每个问题都要带修法`（PREreview）与`don't admire the problem`（TMM）同义。

### 2.2 与 bench 目标的对账

12 scenario × 56 constraint = 672 个 slot；两桶占 20–25% → **134–168 slot，约合每 scenario 11–14 条**（建议 8 A / 4 B）。

**总量不是瓶颈。** 已裁定为"用/慎用"的源里未挖掘的余量还有 300+ 条：PREreview 已取 5 / 可取 45–75；ARR 已取 18 / 可取 54–81；Google eng-practices 已取 11 / 可取 60–100；PRISMA-CONSORT-STROBE-OSF-SPIRIT 一族已取 21 / 可取 50+；Wikinews 已取 5 / 可取 30–52；SNI 已取 13 / 可取 150–300。

真正的瓶颈有三个：

**瓶颈 1：B 桶占比过低。** task_goal 只占已提取的 26%，去重后降到约 23%。若希望两桶大致 6:4，B 需要从 30 翻到 55–70。可用的 B 桶发动机是充足的，不需要新源：SNI 的 76 个 category 是现成的动词轴（约 40–60 条）；Bloom 阶梯作为生成器（约 35–70 条）；PromptSource 的 `original_task:false` 子集（原始 50–120，过滤后约 20）；Turing Way + NSF + GSRRF 还有约 20 条未取。B 桶可以做到 100+。

**瓶颈 2（真正的缺口）：scenario 覆盖严重偏斜。** 现有 189 条按 scope 聚类：

| scope 簇 | 条数 |
|---|---|
| 论文阅读 / 同行评审 / 研究想法 | ~45 |
| 来源质量 / 引用 / 事实核查 | ~55 |
| 代码 / 依赖 / 安全 / 技术选型 | ~28 |
| 数据与统计 | ~15 |
| 通用任务形态（无领域） | ~30 |
| 其他 | ~16 |

全语料是 research / code / journalism / stats 四个域，`scope_hint` 标 "global" 的只有约 10 条。如果 12 个 scenario 里有 7 个落在这四个域之外（医疗信息查询、消费决策、求职、法律咨询、个人理财、旅行规划、创意写作之类），那 7 个 scenario 各需 ~11 slot = **约 77 个 slot，现有语料最多只能靠 global 与 source-hierarchy 族覆盖约 25 个，缺口 50–55 条（A 约 35 / B 约 18）**。

**瓶颈 3：家族多样性而非句子数量。** 139 条 A 桶归并后只有约 17 个推理家族，且极度不均：source quality/hierarchy 一族独占 ~28 条，statistical evidence discipline ~15，fact-vs-inference ~10，criticism-must-be-substantiated ~10，其余家族各 5–8。若一个 bench 里 40 个 item 都在考"给出处"，有效区分度会远低于名义条数。B 桶约 14 个家族，多数家族只有 1–3 个成员。

### 2.3 补缺方案（按性价比排序）

1. **Scope transposition，约 30 条，成本最低。** 把 17 个 A 桶家族里领域无关的成员按新 scenario 重新实例化，但**必须换上领域特有的牙齿**（一个具名来源类型或一个具名失效模式），否则退化成重复。示例：WP:RS 的"单个 study 先去找 review/meta-analysis"转到医疗信息场景 → "别拿一篇研究就告诉我某个补剂有用，先看有没有 meta-analysis 或临床指南"。同族、不同词面、不同判分锚点。
2. **Bloom 阶梯生成 B 桶，约 20 条。** 每个（scenario × 跨层动词替换）生成一条，这是 §1 里 Bloom 源被判定为"生成器而非语料"的用法。
3. **SNI 的 76 类 category 抽 B 桶动词轴，约 15 条。**
4. **新源补覆盖，约 60–100 条潜力——全部标记为待核验。** 下列都是按现有 rule 1 有较大概率过关、且正好落在未覆盖领域的候选，但**我没有打开它们的 primary artefact，许可陈述均为二手未核验，不得直接入库**：
   - `medlineplus_evaluating_health_info`（NLM，疑似 US Gov 公有领域）— 医疗信息场景的证据标准。待核 https://medlineplus.gov/evaluatinghealthinformation.html 及 NLM copyright 页
   - `gao_yellow_book`（US Gov，疑似公有领域）— Government Auditing Standards 的 sufficient/appropriate evidence 章，是审计域的纯 A 桶材料。待核 https://www.gao.gov/yellowbook
   - `nist_ai_rmf` / `nist_sp_800_30`（US Gov，疑似公有领域）— 风险与不确定性判断，可覆盖工程决策与合规场景
   - `openstax`（疑似 CC BY 4.0）— critical thinking / statistics / writing guide 教科书，日常域的领域无关推理规则来源，家族多样性最好的补充。待核 https://openstax.org/ 的 licensing 页
   - `govuk_service_manual`（疑似 OGL v3.0）— 证据不足时如何决策，覆盖产品/服务决策场景
   - `ftc_consumer_advice` / `cfpb`（US Gov，疑似公有领域）— 消费与理财场景（注意：只取"如何判断证据"的规则，不取任何构成理财建议的内容）
   
   每个源走与本表同样的核验流程（打开 primary artefact、读 LICENSE / copyright / dataset card、记 URL），预估各 15–40 条。
5. **self-instruct 的 175 条种子全部作为风格锚**，用于校验所有生成条目"像不像真人说的"。

### 2.4 补缺后的预期

A 桶 135–150 / B 桶 65–80，合计 200–230。相对 134–168 slot 的目标有约 1.4× 余量，用于吸收 §4 pilot 阶段预计 20–30% 的区分度淘汰。**结论：目标可达，但必须先做 scenario 覆盖对齐和 B 桶扩产，不能靠继续在现有四个域里加句子。**

---

## 3. 质量抽样

### 3.1 最好的 12 条

| # | 条目 | 好在哪 |
|---|---|---|
| 1 | "When you check a dependency for me, flag anything of medium severity or worse that's been publicly known and unpatched for more than 60 days."（`openssf_badge_criteria`） | 带数字阈值和严重度门限，判分可以完全机械化；同时是真实工程师会长期持有的偏好，不是机构口径 |
| 2 | "Judge whether a project is alive on concrete signals: commits in the last twelve months, a release in the last twelve months, more than one maintainer."（`openssf_concise_guides`） | 把"这个库还活着吗"这种模糊判断换成三个可数事实，是"证据标准"这个概念最干净的实例 |
| 3 | "Never use citation counts, author names or venue prestige as a stand-in for whether a claim is sound."（`acl_rolling_review`） | 明确的禁止式，禁止对象是具名的三样东西，可词面检测；且它禁的是一个真实存在的默认行为 |
| 4 | "If a difference comes with no variance, seeds or significance test, tell me it isn't established yet — don't repeat it as a result."（`acl_rolling_review`） | 触发条件明确（缺方差/种子/检验），要求的动作明确（降级为未确立）。可以设计出必然诱发违反的输入 |
| 5 | "If a dozen outlets are echoing one original report, trace it back before you tell me it's been independently confirmed."（`wikipedia_wp_rs`） | 抓的是一个具体且高频的推理失误（把转载当独立佐证），不是"要多方求证"这种空话 |
| 6 | "Treat other AI systems' output as unverified until you've checked it against a real source."（`wikipedia_wp_rs`） | 当代真实用户偏好，且在 agent 语境里天然可诱发（给 agent 一个 LLM 生成的材料） |
| 7 | "Before you say anything about individual lines, tell me whether this change should exist at all."（`google_eng_practices`，B 桶） | 教科书级 task_goal：它改的是动词与顺序，而顺序是可二值判定的 |
| 8 | "With something half-finished, tell me whether it's worth continuing at all before you get into polishing the details."（`prereview_toolkit`，B 桶） | 与 brief 里的 canonical example（"研究想法要的是新颖性与可行性裁决，不是展开"）几乎同构，且适用面比论文场景宽 |
| 9 | "Tell me who or what dropped out of the data before the headline number was computed, and whether that could bend the answer."（`consort_2025`） | 要求的是一个具体的分析动作 + 一个方向性判断，两者都能在输出里指认 |
| 10 | "Ask me what result would change my mind before we go looking, so I can't move the goalposts afterwards."（`osf_prereg_template`） | 罕见且真实：约束的是 agent 对**用户本人**推理纪律的介入，正好落在 brief 里"pushing back on the user's assumptions"那一格 |
| 11 | "If the material I gave you doesn't settle the question, say so rather than producing an answer anyway."（`super_natural_instructions`） | 负空间约束，最好判也最有区分度：只要 scenario 设计成材料确实不足，合规输出与违规输出几乎不可能混淆 |
| 12 | "On a second look at something I've revised, go through your earlier points one by one and close each out as addressed or reasonably rejected."（`turing_way_peer_review`，B 桶） | 多轮场景，且判分可以逐条对账（上一轮 N 个 point，这一轮闭环了几个），接近机械判 |

补充两条差点入选、值得留用的：`google_eng_practices` 的"A green test suite isn't evidence — check the tests would actually fail if the code broke"（把"有测试"和"测试有效"分开，很少有语料能表达这个区别）；`acl_rolling_review` 的"If I answer one of your objections, drop it"（多轮 + 反固执，且可对账）。

### 3.2 最差的 5 条，各自坏在不同地方

| # | 条目 | 失效模式 |
|---|---|---|
| 1 | "Come at my design from more than one angle instead of a single lens."（`threat_modeling_manifesto`） | **无阈值的正确废话。** "more than one angle"没有可数定义，任何写了两段的输出都能算通过。这就是"be rigorous"的变体，只是换了个说法。真人也不会这么说——真人会说"你别只从性能角度看，也说说这玩意儿上线以后谁来维护" |
| 2 | "Ask yourself whether each finding is genuinely worth my time and drop the ones that aren't."（`threat_modeling_manifesto`） | **约束了一个不可观测的内心动作。** 输出里不会留下"我自问过"的痕迹，judge 无从判起；而且没有反事实——不存在一个"违反了这条但仍然完成了任务"的输出。放进 bench 就是全员满分 |
| 3 | "On science questions, work from the actual facts and the chain between them rather than the most plausible-sounding option."（`super_natural_instructions`） | **把"把任务做好"本身当成了约束。** 这条等价于"回答科学问题时要答对"。没有任何用户会把它当作一条需要长期携带的个人偏好——它是任务成功的定义，不是对任务的额外要求。来源是众包 spec，这个出身在句子里露得很明显 |
| 4 | "Don't recite facts back at me — classify them and put them in your own words."（`bloom_newton_2020`） | **分类学术语泄漏。** "classify them" 是 Bloom 的 Comprehension 层动词，不是人话。真人说的是"别把原文抄给我，用你自己的话讲一遍"，不会要求"分类"。这条暴露了把 Bloom 当语料而非生成器的风险，也说明必须用 self-instruct 的 175 条种子做风格锚 |
| 5 | "Skip the tour of your methodology and start on the actual thing in front of you."（`threat_modeling_manifesto`） | **既是 output-form 混入，又与语料内其他条目直接冲突。** 它约束的是"怎么呈现"（别写开场白），不是"凭什么下结论"，桶归错了；更糟的是它与 `turing_way_peer_review` 的"Start by telling me how you did the assessment"、`prereview_toolkit` 的"先给两三句你对主张的理解"、`gsrrf_2023` 的"开工前先说成品长什么样"三条正面矛盾。同一个 bench 里出现互斥 constraint，会让判分结果不可解释 |

五条共同的"不像真人"信号：主语漂移（不是"我要你…"而是无主语的规范陈述）、缺少触发情境（没有"当我…的时候"）、缺少一个能被指认的具体对象。真实用户的规则几乎总带一个具体的痛点实例，因为那条规则就是被某次糟糕经历打出来的。

---

## 4. 判分可行性

### 4.1 先确定判什么

translator 架构下有两个可判位点，难度差一个量级：

- **P1：改写后的 request**——translator 有没有把这条 durable requirement 织进去。已提取条目里的 `checkable` 字段写的全是这一层（"rewritten request must…"）。
- **P2：agent 的最终输出**——agent 有没有真的照做。

**建议主判 P1，抽样判 P2。** 理由：P1 是短文本上的存在性判定，reasoning_policy 这类"判断方法"约束在 P1 上可判性远高于 P2；P2 留 20–30% 的 item 做端到端验证，用来证明"织进去"确实带来行为变化，否则整个 benchmark 只测了 translator 的复述能力。两层分数分开报，不要合并。

### 4.2 四层判分

**T1 — 机械判（P1 上），约占 16%（189 条里 `checkable` 标 mechanical 的约 30 条）。**
适用条件：constraint 携带数字、具名实体或禁用词。
- 数字型：60 天 + medium 严重度（`openssf_badge`）；12 个月 + maintainer > 1（`openssf_concise`）；至少 2 个独立来源（`wikinews`）
- 具名实体型：Wikipedia / mirror 被禁；headline vs body；citation count / venue / prestige；peer-reviewed 优先层
- 禁用词型：`bloom` 那条"不许说 understand / appreciate / be aware / know"可以直接用词表判
- 成对要素型："effect size 与不确定度必须同时出现"、"相对数必须配绝对数"、"估计值必须带 uncertainty / CI / margin of error"

实现：每条 constraint 配一组 `required_lexicon`（同义扩展表）和 `forbidden_lexicon`，用正则 + 一个小的语义等价表，不要用裸正则。

**T2 — 机械判（P2 上），约 25–35 条。**
只在输出里存在可枚举产物时可用：
- 结构性产物：limitations 段是否存在；confidence / certainty 评级是否存在；major/minor 分级标签是否存在
- 裁决 token：accept/reject、yes/no、单一 recommendation 是否存在（B 桶的 verdict 族大量适用）
- 可数事实：引用数 ≥ 2；被引 URL 的 host 去重后 ≥ 2（判来源独立性的粗代理）

**T3 — judge 判，二值化 rubric，约占 55–60%。**
这是主力。写窄的六条工艺规则：

1. **判"可指认的痕迹"，不判"品质"。** 把"使用批判性分析"改写成：*输出中是否存在至少一处被点名的弱点，且该弱点附带具体位置（章节/行号/引文）？是=1，否=0。* 存在性判定的标注一致性远高于程度判定。
2. **强制引证再判（quote-then-judge）。** judge 必须先从输出里摘出支撑片段，再给 0/1；摘不出即判 0。这一条单独就能压掉大部分 judge 的幻觉式给分。
3. **顺序类约束按位置判，接近机械。** "先说该不该做再说行级问题"、"先验证再解释"、"先跑预注册分析再探索"、"先形成自己的判断再看文献"——切段后比较首次出现位置即可。语料里至少有 8 条属于这一类，应尽量往这里归。
4. **禁止复合谓词。** "把 major 和 minor 分开**并且**标注每一条"要拆成两条 item，或在 rubric 里明确只判其中一个 predicate。一条 constraint 一个 predicate，是二值化的前提。
5. **元声明不得计分。** 判据里写死：仅出现"我将进行批判性分析"这类元陈述而实体内容中无对应痕迹的，判 0。否则 agent 会用套话刷分。
6. **成对反例锚（minimal contrast pair）。** 每条 constraint 预写一个合规参考输出和一个违规参考输出，judge 做的是三分类（更接近合规锚 / 更接近违规锚 / 都不像），而不是开放式打分。这既提高一致性，也顺带做了 constraint 的有效性检验——**如果你写不出一个"违反了它但仍然完成了原任务"的输出，这条 constraint 是空的，应当在生成阶段就被砍掉**（见 §5）。

**T4 — 判不了，生成阶段剔除。** 内心动作类（"ask yourself whether…"）、无阈值程度词类、与任务成功同义类。

### 4.3 B 桶的特殊便宜

task_goal 有一个 A 桶没有的判分优势：因为它**替换动词**，可以判"输出属于哪一类任务产物"，而不是判质量。"这段输出是 summary 还是 verdict"是一个窄得多的分类问题，一致性高，甚至可以训一个便宜的分类器或用结构特征代理（有无单一结论句、有无逐节复述结构、有无"综上/推荐"型收束）。B 桶应尽量往这个形态设计，避免写成模糊的态度要求。

### 4.4 校准与准入

每条 constraint 入库前：3 名标注者在 10 对（合规/违规）样本上判，Fleiss κ ≥ 0.6 才准入，否则退回改写 rubric 或降级为 T4 剔除。这个门槛会砍掉相当一部分 A 桶的软性条目，要在供给量里预留（§2.4 的 1.4× 余量就是为此）。

### 4.5 陷阱设计（这两个桶特有的实验设计要求）

对 prohibition 类约束（别用 Wikipedia、别搞 false balance、别把 op-ed 当证据、别把相关当因果），**只看输出无法区分"遵守了"和"根本没机会违反"**。必须为每条这类 constraint 绑定至少一个**诱导违反**的 scenario：问一个只有 Wikipedia 好答的问题、给一个有明确科学共识但媒体常搞两边论的议题、塞一篇 op-ed 当唯一可用材料。

配套的准入检查：在**无 constraint 的 baseline** 上跑一遍 pilot，如果 baseline 通过率 > 0.7，说明这条 constraint 在该 scenario 上没有信息量，必须换 scenario 或换 constraint。这是本次设计里最容易被漏掉、也最能决定 bench 有没有区分度的一步。

---

## 5. 风险：退化成"正确的废话"

### 5.1 七种退化路径

1. **无阈值程度词。** "be rigorous" / "be critical" / "consider multiple angles" / "think carefully"。这是最常见的一种，且 A 桶天生倾向于此，因为源材料里大量规范陈述本身就是这个形态。
2. **与"把任务做好"同义。** "回答科学问题要基于事实"、"推理步骤不要冗余"。这类看起来是约束，实际是任务成功的定义，不携带任何用户特异性信息。
3. **与 output_contract 混淆。** "别写开场白"、"别用 groundbreaking 这种词"、"引用要跟在引文旁边"。这些约束的是呈现，不是判断依据。混进来会让两个薄桶虚假变厚，同时污染 bucket 的语义定义。
4. **机构口径残留。** 主语不是"我/你"、或规定第三方义务的条款（brief 里点名的"reviewers must not reveal author identities"型）。同行评审、审计、期刊政策这三类源天生带这个毛病。
5. **分类学术语泄漏。** Bloom 的 classify/synthesise、PRISMA 的 item 编号、SNI 的 "the given passage"、GRADE 的 certainty domain 名。词面一看就不是人说的。
6. **桶内同义堆叠造成虚假多样性。** 三条"要给结论别中立"、两条"别把两个来源缝起来"。名义 189 条、实际 17 个家族。
7. **不可违反的 constraint。** scenario 里根本没有违反机会 → 全员满分 → 零区分度。

### 5.2 生成阶段的硬闸（全部为 boolean，不过即丢）

按顺序跑，前面的便宜、砍量大：

- **G1 抓手闸。** 每条 constraint 必须至少携带以下四者之一：(a) 一个数（60 天、12 个月、至少 2 个来源）；(b) 一个被禁的具体行为或具名词；(c) 一个顺序关系（X 先于 Y）；(d) 一个必须出现的具名产物（confidence rating、limitations 段、accept/reject 结论、被点名的弱点）。四项全无 → 丢。这一条直接封死退化路径 1。
- **G2 反事实闸。** 必须能写出一个"违反了该 constraint 但仍然完成了原任务"的输出。写不出 → 该 constraint 与任务成功同义 → 丢。封死路径 2，也是 §4.2 rule 6 的副产品，两处共用一份反例锚。
- **G3 桶判定闸。** 问一个判别问题：改掉这条规则，改变的是**结论本身**，还是只改变**结论的呈现**？后者归 output_contract。封死路径 3。
- **G4 第一人称闸。** 必须能自然改写成"我要你…/别…"，主语只能是我或你，不得涉及第三方义务；再过一个"我能想象自己对助手常年这么要求吗"的判定。封死路径 4。
- **G5 风格闸。** 禁用词表（classify、synthesise、item、passage、rubric、criterion 等分类学词）+ 用 self-instruct 的 175 条种子做 few-shot 风格锚，对每条打"像不像真人随口说的" 1–5 分，< 4 退回改写；每批人工抽检 10%。封死路径 5。
- **G6 去重闸。** embedding 余弦 > 0.85 合并；同时建 `scope_hint × predicate_type` 二维覆盖表，同一格子上限设 N（建议 N=3），超了必须换家族。封死路径 6。
- **G7 可违反性闸。** 每条 constraint 必须绑定至少一个"诱导违反"的 scenario，并在 unconstrained baseline 上通过率 ≤ 0.7。封死路径 7。这一闸必须放在最后跑，因为它需要真实 pilot 数据，也是唯一有成本的一闸。

### 5.3 另一类风险：copyleft 污染

Wikipedia 五个页面（CC BY-SA 4.0，https://en.wikipedia.org/wiki/Wikipedia:Copyrights）和 dolly-15k（CC BY-SA 3.0，https://creativecommons.org/licenses/by-sa/3.0/）是本次唯二进了"慎用"的 copyleft 源，而 Wikipedia 恰好贡献了已提取条目的约 23%（44/189）。风险在于这些条目一旦混进主干，整个 corpus 的许可状态就说不清了。

三条处置：(1) 每条 constraint 强制带 `provenance` 与 `copyleft_derived` 字段，无 provenance 不入库；(2) BY-SA 派生的条目要么走 clean-room 重写并由人签字确认无原表达残留，要么单独分片并以 CC BY-SA 4.0 发布、与主干隔离；(3) 由于 WP:RS / WP:NOR 的内容质量确实最高，值得为它们单独走 clean-room 流程而不是简单放弃——但这必须是有人签字的决定，不是默认路径。

同时把三条踩过的陷阱写进 ingestion checklist，防止后续有人重新引入：Cochrane（免费可读 ≠ 可再分发）、PLOS（论文 CC BY ≠ 网站内容 CC BY）、EQUATOR/prisma-statement.org（期刊版 CC BY ≠ 指南站再分发的同一份 checklist）。