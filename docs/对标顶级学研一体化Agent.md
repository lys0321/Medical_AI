# 医枢 MedNexus vs 顶级学研一体化 Agent：对标与演进

> 更新：2026-11-17。结论基于一手来源（官网 / 官方博客 / 论文）调研与本地代码盘点。
> 这份文档回答两个问题：**我们和顶级差在哪**、**哪些差距值得补、已经补了什么**。

## 一、一句话结论

顶级产品的真正护城河**不是模型参数，而是确定性的行为设计 + 可核验来源约束 + 分层记忆**。
大模型是"措辞与综合"的放大器，不是这些能力的来源。

医枢的路线恰恰押在这条护城河上——证据纪律（拒答、可回溯、FSRS-lite 证据门槛、诊断→补救闭环
真实接线）是它相对通用 Agent 的**差异化优势**，而不是短板。真正需要补的，是把这套纪律
延伸到"证据呈现"和"学习者状态"两个维度。

## 二、能力分层：什么必须靠模型，什么规则就能做

| 层 | 能力 | 必须大模型 | 规则/工程能否独立做 |
|---|---|---|---|
| A 确定性基础层 | 资料摄取、段落级引用定位、来源边界与拒答、证据分级、掌握度记录、间隔重复调度 | 否 | **能**（本地应用的真正护城河） |
| B 规则骨架+模型填充 | Socratic 引导、自适应出题、抽认卡/测验生成、学习者画像的非结构化抽取 | 是（措辞） | 部分：骨架用规则，措辞需模型 |
| C 强模型依赖层 | Deep Research 多步自主检索、跨数百文献综合、语音/白板/视频多模态推理 | 是，且需外部服务 | 基本不能 |

## 三、逐项对标（顶级基线 → 医枢现状 → 判断）

| 能力基线 | 顶级代表做法 | 医枢现状 | 判断 |
|---|---|---|---|
| **可核验引用 / 来源内回答** | Elicit 句子级引用；NotebookLM "strictly grounded"；Deep Research 引用具体句子 | 答案锚定教材页码+原文节选；文献带真实 PMID；PubMed 失败时明确拒答、不编造 | ✅ 已达一流，是核心优势 |
| **拒答 / 证据闸门** | Consensus "search before synthesis，引用绝不虚构" | gate 概念性问题不放行；无教材依据时拒答；PMC 许可闸门 | ✅ 已达一流 |
| **诊断→补救闭环** | Study Mode 支架式反馈；掌握度驱动进度 | `orchestration.loop_step`+`weave_plan` 真实驱动首页计划；FSRS-lite 只有独立迁移题推进稳定度 | ✅ 设计领先，证据纪律比多数产品严谨 |
| **证据分级 / 共识度可视化** | Consensus Meter 2.0（研究一致度+方法学加权）；Elicit 系统综述分级 | 单篇有四项可核验字段（evidence.py），但**缺整批文献的类型构成画像** | ⚠️ **本轮补齐**（见下） |
| **知识图谱 / 引文网络** | Connected Papers、ResearchRabbit、Obsidian 本地图算法 | 无跨知识点图谱；知识点彼此孤立 | ❌ 真实差距，中成本，规则可做 |
| **Socratic 对话导师** | Study Mode/LearnLM 显式行为约束（76% 支架式提问、仅 2% 直接给答案） | 有多轮 tutor 通道，但未配模型时退化为材料摘录 | ⚠️ 骨架在，措辞依赖模型 |
| **自适应难度 / 智能出题** | Learn Your Way 按年级兴趣改编+实时反馈再个性化 | 题目手工编写或规则转换，无 LLM 生成、无难度自适应 | ⚠️ 属 B/C 层，兼收证据纪律取舍 |
| **学习行为可视化** | 掌握度看板、学习路径、进度预测 | 仅近 7 天时长柱状图 + 掌握分布 | ⚠️ 弱，中成本 |
| **长期学习者画像 / 记忆** | mem0 分作用域记忆+三路检索；Lily 记住上次对话 | 按 learner-id 持久化作答/事件，但无结构化画像 | ⚠️ 结构化部分可做 |
| **多模态输入** | Gemini Live 语音+摄像头指题；Audio Overview | 无语音/拍照 | ❌ 强依赖外部服务，暂不做 |
| **Deep Research 多步自主检索** | OpenAI/Perplexity 数百来源多步回溯 | 固定 3 步（gate→检索→读），来源限定 PubMed/PMC | ⚠️ 受限版是刻意取舍，不硬拼 |

## 四、本轮落地：证据类型构成画像（evidence mix）

**对标**：Consensus Meter / Elicit 的"证据分级与共识度可视化"。
**医枢版本（诚实版）**：只按 PubMed 官方 `PublicationType` 统计一批检索结果的类型构成，
每篇仅归一类（指南/共识 → 系统综述/Meta → RCT → 观察性 → 综述 → 病例 → 其他/待核对），
渲染成堆叠条 + 图例 + 描述性汇总。

**刻意不做**（与 evidence.py 的纪律一致）：
- 不给"高/中/低质量"评分，不给推荐等级；
- 不从标题或类型推断证据质量、不替代偏倚风险评估；
- 不产生医学结论；每屏显著标注"不是证据质量评级"。

**改动**：
- `mednexus/evidence.py`：纯函数 `evidence_mix(papers)` + `STUDY_MIX` / `MIX_NOTICE`。
- `mednexus/api/research.py`：`pubmed()` 与 `pubmed_compat()` 输出带 `evidence_mix`（含缓存兼容）。
- `mednexus/web/app.js`：`evidenceMixBar(mix)` + `renderPapers` 顶部注入。
- `mednexus/web/styles.css`：构成条/图例/层级配色。
- 测试：`tests/test_evidence_mix.py`（9 项）、`tests/evidence_mix_render.test.mjs`（3 项）。

## 五、本轮新增：循证研究画布（research trace）

> 更新：2026-11-18。首页罗盘与首页布局保持不变；这一版把差异化做到「文献漫游」内部。

**对标差距**：Elicit 的强项是结构化证据表，Consensus 的强项是把"证据倾向"显式化，
NotebookLM 的强项是来源内回答；顶级产品都让用户看见"问题是怎么变成证据的"。
上一版医枢虽然已有真实 PMID、证据类型构成与摘要四项核对，但结果仍是一列卡片，
用户看不到"疑问 → 检索式 → 证据 → 结论边界"的推理链路。

**医枢版本（诚实版）**：新增纯函数 `research_trace.build_trace()` 与五步画布：

1. **研究疑问**：保留用户原句，并按规则标注问题类型（干预/诊断/机制/预后/测量/探索），只决定核对清单；
2. **检索式**：显示实际提交给 PubMed 的英文式与人工映射说明，绝不把模板冒充逐句翻译；
3. **证据构成**：接已有 `evidence_mix()`，只按 PubMed 官方 Publication Type 归类，显著声明不是质量评级；
4. **逐篇核对**：列出本次真实 PMID，统计摘要里能核对的样本量/随机化/盲法字段，未提到记未提到；
5. **结论边界**：明确"现在能核对什么 / 现在不能推断什么 / 下一步动作"，不写医学结论。

**为什么这是差异化**：它是一个**可点击、可核验、可回放**的研究路线，而不是一段模型独白。
未检索时后三步显示"待完成"，不画假证据；检索失败时错误响应也带同一份部分链路；
所有卡片都能回到输入框、检索式编辑区、PubMed 文献或真实 PMID。

**改动文件**：
- `mednexus/research_trace.py`（纯函数，6 项单测）；
- `mednexus/api/research.py` / `mednexus/api/routing.py`（gate、成功、失败三条路径都带 trace）；
- `mednexus/web/research-trace.js`、`styles.css`、`index.html`、`app.js`（浅色五步画布与点击定位）；
- `mednexus/tests/test_research_trace.py`、`research_trace_render.test.mjs`。

## 六、下一优先级建议（按可落地性）

1. **知识图谱 / 知识点前置关系**（中成本，纯规则）：从教学大纲与考点库抽取知识点前置关系，
   本地算度/中介中心性，给出"先修—后继"可视化与薄弱点上游定位。图结构可复现、不幻觉。
2. **结构化学习者画像**（中成本）：显式 schema（基础/目标/已掌握/错题偏好/更新时间），规则读写，
   带来源与时间戳防"陈旧记忆"；语义抽取作为第二阶段。
3. **Socratic 行为状态机**（低-中成本，措辞需模型）：把"先反问→给提示→自检→再讲解"做成显式状态机，
   固化 Study Mode 那套认知负荷/元认知约束，模型只负责把每步话说自然。
4. **自适应难度 / 智能出题**（依赖 B/C 层）：保持证据门槛，不牺牲可核验性去换题量。

> 不建议投入：Deep Research 全网自由探索、生成式音视频概览——顶级玩家靠端到端强化学习+
> 全网索引，本地应用硬拼不划算。把资源投在"可核验、可拒答、可显示证据分歧"上更有价值。

## 七、来源（一手）

- OpenAI Study Mode: https://openai.com/index/chatgpt-study-mode/
- Google LearnLM / 塞拉利昂 RCT: https://deepmind.google/blog/measuring-the-impact-of-learning-with-ai-in-sierra-leone-and-beyond/
- Google NotebookLM: https://blog.google/technology/google-labs/notebooklm-deep-research-file-types
- Elicit（句子级引用 / 系统综述）: https://elicit.org/
- Consensus Meter 2.0 / Medical Mode: https://consensus.app/home/blog/deep-search/
- Connected Papers: https://connectedpapers.com/
- mem0 记忆基准: https://mem0.ai/blog/state-of-ai-agent-memory-2026
- STORM / Co-STORM: https://arxiv.org/abs/2402.14207
