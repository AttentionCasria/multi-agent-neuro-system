# NeuroAgentSystem — AI 模型层深度分析报告

> 分析日期：2026-03-21
> 分析范围：`model/` 目录下全部 Python 代码
> 分析视角：模型架构、技术选型、数据流、推理流程、潜在问题与改进建议

---

## 目录

1. [整体架构概述](#1-整体架构概述)
2. [模型与技术选型](#2-模型与技术选型)
3. [RAG Pipeline 详解](#3-rag-pipeline-详解)
4. [推理流程：两条接口链路](#4-推理流程两条接口链路)
5. [Agent 状态机详解](#5-agent-状态机详解)
6. [Prompt 工程体系](#6-prompt-工程体系)
7. [评估体系](#7-评估体系)
8. [潜在问题与改进建议](#8-潜在问题与改进建议)

---

## 1. 整体架构概述

### 1.1 模块依赖关系

```
┌─────────────────────────────────────────────────────┐
│               FastAPI 服务层 (main.py)               │
│   POST /model/get_result (SSE 流式)                  │
│   POST /ai/analyze       (同步 JSON)                 │
│   POST /admin/reload_config                          │
└──────────────────┬──────────────────────────────────┘
                   │
          ┌────────┴─────────┐
          ▼                  ▼
   ┌─────────────┐    ┌──────────────┐
   │  qwenAgent  │    │  NamingModel │
   │  (推理引擎)  │    │ (会话标题生成)│
   └──────┬──────┘    └──────────────┘
          │
          ├── SimpleGraph 状态机（自实现，无 LangGraph）
          ├── TokenAggregator（thinking 流聚合）
          │
          ├── MedicalAssistant (qwen_assistant.py)
          │   ├── fast_parallel_retrieve（并行检索）
          │   └── stream_final_report（流式报告生成）
          │       └── MedicalReActAgent (medical_agent.py)
          │           └── UnifiedSearchEngine (Retrieve.py)
          │               ├── Chroma 向量库
          │               ├── BM25Retriever（关键词）
          │               └── BGEReranker（重排序）
          │
          ├── ConversationSummaryService（多轮对话摘要）
          └── PromptManager + ReportTemplateManager（配置热加载）
```

### 1.2 各模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **FastAPI 服务层** | `main.py` | JWT 认证、SSE 流控、all_info 更新、心跳机制 |
| **推理引擎** | `qwen_agent.py` | SimpleGraph 状态机、意图分类、多题 MCQ 并行、proposer+critic 双轨推理 |
| **医学助手** | `qwen_assistant.py` | 并行检索聚合、流式报告生成 |
| **检索代理** | `medical_agent.py` | 检索词生成、证据合成、限流重试 |
| **RAG 系统** | `makeData/Retrieve.py` | PDF 加载、文本切分、向量化、混合检索、缓存 |
| **配置管理** | `config/config_loader.py` | Prompt 热加载、4 种报告模板管理 |
| **上下文管理** | `utils/context_summary.py` | 对话价值评分、摘要压缩、all_info 累积 |
| **会话命名** | `utils/naming_model.py` | 首轮对话后异步生成会话标题 |
| **错误处理** | `error_codes.py` | 结构化错误码（E1xxx）、SSE 双写兼容 |
| **Token 聚合** | `token_aggregator.py` | 连续 thinking 事件合并，降低 SSE 推送频率 |

---

## 2. 模型与技术选型

### 2.1 LLM 选型

| 角色 | 模型 | 用途 |
|------|------|------|
| `llm_proposer` (llm_max) | `qwen-max` | 主推理：临床推理生成、集成答案、最终报告流式输出 |
| `llm_critic` (llm_plus) | `qwen-plus` | 辅助推理：意图分类、批判性审查、JSON 解析 |
| `naming_llm` | `deepseek-chat` | 会话标题生成（线程池异步，timeout=25s） |

> **为何双模型？** proposer 用 qwen-max 保证推理质量，critic 用 qwen-plus 降低成本——同等任务质量下，批判性审查、结构化提取对模型能力要求低于生成完整推理。

### 2.2 Embedding 与 Reranker

| 组件 | 模型 | 用途 |
|------|------|------|
| Embedding | `text-embedding-v2` (DashScope) | 文档向量化、Chroma 向量库索引 |
| Reranker | `gte-rerank` (DashScope) | 混合检索结果重排，最终取 top_k=3 |

### 2.3 向量数据库

- **Chroma**（持久化到 `./chroma_db_unified`）
- 配套 BM25 关键词检索（`langchain_community.retrievers.BM25Retriever`）
- 两路结果去重合并后送 Reranker

### 2.4 框架依赖

| 框架 | 版本/用途 |
|------|----------|
| FastAPI + uvicorn | HTTP 服务、SSE 流式响应 |
| LangChain | LLM 封装、Document、TextSplitter |
| Ragas | RAG 评估（faithfulness / answer_relevancy / context_precision / context_recall） |
| PyJWT | JWT 认证 |
| DashScope SDK | 调用通义千问、Embedding、Reranker |

---

## 3. RAG Pipeline 详解

### 3.1 离线索引（服务启动时执行一次）

```
PDF 文件 (docs/)
    │
    ▼ PyPDFLoader
原始 Document（含 source、page 元数据）
    │
    ▼ clean_text()
    │   ├─ 去除 \n 和多余空格
    │   ├─ 去重复标点（，，→，，。。→。）
    │   └─ 过滤 < 50 字符的页面
    │
    ▼ RecursiveCharacterTextSplitter
    │   chunk_size=512, chunk_overlap=128
    │   separators: ["\n\n", "。", "；", "\n", " ", ""]
    │
    ├─► Chroma 向量库（DashScope text-embedding-v2）
    └─► BM25Retriever（内存索引）
```

### 3.2 在线检索（每次推理时触发）

```
用户问题 / clinical_questions
    │
    ▼ 检索缓存检查（MD5 key）
    ├─ 命中 → 直接返回缓存结果
    │
    └─ 未命中 →
        ├─ 向量检索：Chroma（k=8）
        ├─ 关键词检索：BM25（k=8）
        ├─ 去重合并（最多 8-16 条候选）
        ▼
        BGEReranker（gte-rerank，top_k=3）
        │   失败降级 → 直接返回前 top_k 条
        ▼
        3 条 Document（含 relevance_score）
        │
        ▼ 格式化
        "【文献1】[来源: 《xxx》 p.N] (相关度:0.87)\n内容前400字..."
```

### 3.3 关键参数汇总

```yaml
top_k_per_store:       4     # 单路召回（已弃用）
top_k_final:           3     # 最终返回条数
reranker_initial_k:    8     # Reranker 输入候选数
chunk_size:            512   # 文本切分块大小
chunk_overlap:         128   # 块重叠字符数
batch_size（写库）:    32    # 向量库批量写入
max_doc_content:       400   # 每条文献的最大截取字符
```

---

## 4. 推理流程：两条接口链路

### 4.1 接口一：`POST /model/get_result`（SSE 流式问诊）

```
QueryRequest
  question / all_info / round / report_mode / show_thinking / token

    │
    ├─ [并行 Task] naming_model.run_naming(question)  ← 仅首轮，deepseek-chat
    │
    └─ qwenAgent.run_clinical_reasoning()
           │
           ▼
    ┌──────────────────────────────────────────────────────┐
    │  TokenAggregator 包装层                               │
    │  （max_tokens=20, max_wait_ms=100 批量聚合 thinking）  │
    └──────────────────────┬───────────────────────────────┘
                           │
                    _run_clinical_reasoning_core()
                           │
           ┌───────────────▼──────────────────┐
           │  Step 0: 预分类（1 次 LLM）         │
           │  _classify_and_detect_intent()    │
           │  输出：is_multi_mcq / intent_type  │
           └───────────────┬──────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         MCQ 路径     知识问答路径    问诊完整路径
              │            │            │
    并行拆题求解   直接流式回答    ↓
    asyncio.gather   llm.astream()   Step 1: 病例分析
    每题独立推理                       _unified_analysis()
    合并格式化输出                      1次LLM → 提取：
                                      structured_context
                                      complexity
                                      key_risks
                                      clinical_questions（3个）
                                      user_questions
                                          │
                                       Step 2: 并行证据检索
                                       ThreadPoolExecutor(3)
                                       每个 clinical_question
                                       → fast_retrieve()
                                       → Chroma+BM25+Reranker
                                          │
                                       Step 3: 临床推理
                                       _parallel_propose_and_critique()
                                          │
                                   ┌──────┴──────┐
                              user_questions    标准路径
                              非空（快速路径）    │
                              1次LLM直接答题    Task1+Task2 并行
                                              proposer.ainvoke()
                                              critic.ainvoke()
                                              → Task3 集成
                                              proposer.ainvoke()
                                                   │
                                               Step 4: 流式报告
                                               stream_final_report()
                                               llm.astream()
                                               → yield chunk 事件
    │
    └─ 流结束后
        ├─ 等待 naming_future → 会话标题
        ├─ context_summary.update_all_info()（线程池）
        └─ yield done 事件（含 all_info_update）
```

**SSE 事件序列：**

| 事件类型 | 说明 |
|----------|------|
| `heartbeat` | 10s 无响应时的保活心跳 |
| `thinking` | 分步推理过程（聚合后发送） |
| `chunk` | 报告正文的流式分块 |
| `meta` | 中间元数据（complexity、report_mode、key_risks） |
| `result` | MCQ 路径的最终完整答案 |
| `error` | 结构化错误（含 E1xxx 错误码、retryable 字段） |
| `done` | 流结束信号（含 result、summary、name） |

---

### 4.2 接口二：`POST /ai/analyze`（同步健康风险分析）

```
AnalyzeRequest
  patientId / data / all_info / token

    │
    ▼
analyze_patient_risk(patient_data, all_info)
    │
    ├─ Step 1: _unified_analysis()  ← 1次 LLM（llm_critic）
    │   输入：patient_data
    │   输出：structured_context / complexity / key_risks / clinical_questions
    │   ⚠️  全程无检索，纯参数化知识
    │
    └─ Step 2: _RISK_API_PROMPT_TEMPLATE 格式化
        输入：患者数据 + Step1 结构化结果
        LLM 输出（llm_critic）：
        ⚠️  全程无检索，纯参数化知识
        │
        ▼
    {
      "riskLevel": "低风险/中风险/高风险",
      "suggestion": "一句干预建议（可执行）",
      "analysisDetails": "风险依据简述"
    }
```

> **核心问题**：`clinical_questions` 在 Step 1 被生成，注释明确写"用于检索医学文献"，但这些问题 **从未真正触发 RAG**，而是直接作为上下文传给 Step 2 的 LLM，等于让模型自问自答。

---

## 5. Agent 状态机详解

### 5.1 SimpleGraph 结构（自实现，替代 LangGraph）

```python
节点：
  intent    → _node_intent()      意图分类（已内联进 _classify_and_detect_intent）
  analysis  → _node_analysis()    病例结构化
  retrieve  → _node_retrieve()    证据检索
  reason    → _node_reason()      临床推理

路由：
  intent ──[consultation]──► analysis ──► retrieve ──► reason
         ──[knowledge]──────► END（直接流式回答）
         ──[irrelevant]─────► END

ClinicalState 字段：
  case_text / all_info / report_mode / show_thinking
  intent_type / knowledge_response
  context / clinical_questions / key_risks / complexity
  evidence / proposal / critique / user_questions
```

### 5.2 各节点 LLM 调用次数

| 路径 | LLM 调用次数 | 说明 |
|------|------------|------|
| MCQ 多题 | 1（拆题） + N×1（每题） | N = 题目数，全部并行 |
| 知识问答 | 1 | 直接流式输出 |
| 问诊（user_questions 非空） | 1（分析） + 1（推理） | 快速通道，跳过 critic |
| 问诊（标准路径） | 1（分析） + 3（推理：proposer+critic+集成） | 全链路 |

---

## 6. Prompt 工程体系

### 6.1 Prompt 管理架构

- `config/prompts.yaml` — 所有 User Prompt 模板，支持运行时热加载（`/admin/reload_config`）
- `config/report_templates.yaml` — 4 种报告模板（emergency / outpatient / consultation / fast）
- 代码内 Fallback Prompt — 配置文件不存在时的兜底模板

### 6.2 报告模式

| 模式 | 场景 |
|------|------|
| `emergency` | 急诊/卒中紧急处置 |
| `outpatient` | 门诊常规评估 |
| `consultation` | 会诊意见 |
| `fast` | 快速简要报告 |

### 6.3 System Prompt 核心约束

推理系统采用**强制推理框架**，体现在 `proposer` Prompt 中：

```
⚠ 强制推理顺序（不允许跳步）：
定位 → 定性 → 卒中类型分层 → 病因优先级 → 机制闭环 →
风险权重排序 → 冲突权衡 → 决策建议 → 不确定性声明

安全卫栏：
- 禁止确诊语气
- 禁止具体药物剂量
- 关键信息缺失必须标注"不足以支持"
- 风险不明优先保守策略
```

### 6.4 CoT 设计

`qwen_agent.py` 内嵌 **3-shot CoT 示例**，全部基于神经急诊场景（急性卒中分诊、影像解读、后循环卒中），引导模型以"让我们一步步思考"的方式输出结构化推理。

---

## 7. 评估体系

### 7.1 评估工具链

| 文件 | 用途 |
|------|------|
| `run_eval.py` | 基础 Ragas 评估（已弃用，仅供参考） |
| `getTestData.py` | 神经医学专项评估，支持断点续传 |
| `getTestData_analysis.py` | 增强版评估 + 数据分析 + 可视化 |
| `expand_contexts_resume.py` | 将 contexts 列展开为逐行 CSV（调试工具） |

### 7.2 评估指标

| 指标 | 含义 | 阈值参考 |
|------|------|---------|
| **Faithfulness** | 答案是否基于检索文本（无幻觉） | ≥0.8 优秀，<0.4 危险 |
| **Answer Relevancy** | 答案与问题的相关度 | — |
| **Context Precision** | 检索到的文献都是有用的 | — |
| **Context Recall** | 有用的文献都被检索到了 | — |

### 7.3 评估数据集

- 来源：CMB-Clin 临床医学数据集
- 筛选关键词：`脑 / 神经 / 卒中 / 中风 / 脑梗 / 脑出血 / 头痛 / 头晕 / 眩晕 / 昏迷 / 意识`
- 评估 LLM：`gpt-4o-mini`（通过 OpenAI 兼容接口）

### 7.4 数据分析输出

`getTestData_analysis.py` 会生成：
- `analysis_summary.json` — 统计汇总（答案长度、GT 长度、检索文献数分布）
- `analysis_report.md` — Markdown 报告
- `analysis_plots/*.png` — 直方图可视化
- `skipped_samples_debug.csv` — 被过滤的样本（调试用）

---

## 8. 潜在问题与改进建议

### 8.1 【P0 - 高危】`/ai/analyze` 完全不走 RAG

**问题描述：**

`analyze_patient_risk()` 的两次 LLM 调用均不触发检索，`clinical_questions` 被生成后直接传给下一个 LLM 自答，等于让模型**识别出自己的知识盲区却不去填补**。

`suggestion` 字段要求输出"可执行的干预建议"，但没有任何文献支撑，在医疗场景中幻觉风险最高。

**改进方向：**

| 方案 | 成本 | 效果 |
|------|------|------|
| 加轻量检索（不走 Reranker，只取 top_1） | 低 | 有文献依据 |
| 强制在 `analysisDetails` 中注明"无文献依据"免责声明 | 极低 | 风险披露 |
| 将 `riskLevel` 改为规则化评分（NIHSS/ABCD²），不依赖 LLM | 中 | 彻底消除幻觉 |

---

### 8.2 【P0 - 高危】数据清洗过于简单

**现状：**

```python
def clean_text(text: str) -> str:
    text = text.replace("\n", "").replace(" ", "")
    text = text.replace("，，", "，").replace("。。", "。")
    return text.strip()
```

**缺失的清洗步骤：**

| 问题 | 影响 |
|------|------|
| PDF OCR 乱码、残破公式未过滤 | 污染 chunk，降低检索质量 |
| 页眉/页脚/目录/参考文献列表混入正文 | 检索时召回无用内容 |
| 跨页表格被切断成无意义片段 | 降低文献有效利用率 |
| 同一指南不同版本重复入库 | 重复 chunk 浪费向量库空间 |
| `chunk_size=512` 按字符切，可能截断医学术语 | 降低语义完整性 |

**改进建议：**

```python
def clean_text(text: str) -> str:
    # 1. 去除页眉页脚（正则匹配页码模式）
    text = re.sub(r'\d+\s*$', '', text, flags=re.MULTILINE)
    # 2. 过滤纯数字行（页码、表格序号）
    text = '\n'.join(l for l in text.splitlines() if not re.match(r'^\s*\d+\s*$', l))
    # 3. 合并连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 4. 去除乱码（非中英文数字标点字符）
    text = re.sub(r'[^\u4e00-\u9fff\u0020-\u007e\uff00-\uffef\n]', '', text)
    return text.strip()
```

---

### 8.3 【P1 - 中等】文献内容截断 400 字符过激进

**现状：**

```python
content = doc.page_content[:400]  # medical_agent.py:85
```

**问题：** 指南的推荐等级（如"I 类推荐，A 级证据"）和具体阈值（如"发病 4.5 小时内"）往往在段落后半段，400 字符截断后 LLM 只能凭参数记忆推断。

**建议：** 改为 600-800 字符，或根据 chunk 的实际句子边界截断。

---

### 8.4 【P1 - 中等】all_info 更新阻塞最终响应

**现状：**

```python
# main.py - generate()
summary_result = await loop.run_in_executor(
    resources["executor"],
    resources["context_summary"].update_all_info,
    ...
)
# ↑ 这里要等 LLM 完成摘要更新才能 yield done 事件
```

用户已看完完整报告，却要等后台 LLM 摘要更新（可能 5-10s）才能收到 `done` 事件。

**建议：** 先发 `done`，再后台异步更新 all_info：

```python
# 先返回 done，提升用户体验
yield json.dumps({"type": "done", "result": answer_text, ...}) + "\n"

# 后台任务异步更新，不阻塞响应
asyncio.create_task(
    loop.run_in_executor(resources["executor"], update_all_info_fn, ...)
)
```

---

### 8.5 【P1 - 中等】Reranker 限流后的异常传播

**现状：**

```python
# medical_agent.py
def _search_with_retry(self, query, top_k, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            return self.retriever.search(query, top_k)
        except Exception as e:
            if "RateQuota" in str(e):
                time.sleep(1.0 * (attempt + 1))
                continue
            raise  # ← 重试耗尽后抛出异常
    return []
```

`fast_retrieve()` 没有 try-except 包裹，限流异常会沿调用栈向上传播，导致整个 `fast_parallel_retrieve()` 失败，进而推理流程中止。

**建议：** 在 `fast_retrieve()` 最外层加 try-except，失败时返回空字符串并记录日志，让推理继续（无文献依据总好过整个请求失败）。

---

### 8.6 【P1 - 中等】TokenAggregator 跨步骤元数据丢失

**问题：** 若连续两个不同 `step` 的 thinking 事件进入同一聚合窗口，flush 时只保留第一个事件的元数据，第二个事件的 `step/title` 会被丢弃。

**影响：** 前端 ThinkingPanel 显示的步骤标题可能不准确。

**建议：** TokenAggregator 按 `(step, title)` 分组聚合，相同步骤合并内容，不同步骤强制 flush。

---

### 8.7 【P2 - 低危】Prompt 注入风险

**现状：**

```python
knowledge_prompt = f"""你是三甲医院神经内科主任医师。
{case_text}
..."""
```

用户输入 `case_text` 直接插入 Prompt，未做任何转义。虽然 Qwen 模型对 Jailbreak 有一定防御，但仍存在风险。

**建议：** 对用户输入添加明确边界标记：

```python
prompt = f"""你是三甲医院神经内科主任医师。

<用户输入>
{case_text}
</用户输入>

请基于上述输入回答..."""
```

---

### 8.8 【P2 - 低危】意图分类粒度不足

**现状：** 意图仅分三类：`consultation / knowledge / irrelevant`

**缺失的意图类型：**

| 意图 | 示例 | 当前处理 |
|------|------|---------|
| 多轮跟进（follow-up） | "那这种情况需要溶栓吗？" | 被归入 consultation |
| 要求第二意见 | "你之前说X，但我看到Y，哪个对？" | 被归入 consultation |
| 自我诊断 | "我觉得我有脑梗" | 被归入 consultation，可能产生危险建议 |

**建议：** 至少增加 `follow_up` 和 `self_diagnosis` 的识别，后者需要强制触发安全免责声明。

---

### 8.9 【P2 - 低危】评估体系仅测 `/model/get_result`

`run_eval.py` 和 `getTestData.py` 均测试 `agent.run()` 路径，未覆盖 `/ai/analyze`（`analyze_patient_risk`）。

该接口完全不走 RAG，Faithfulness 分数必然偏低，但没有评估数据可以证实。

**建议：** 为 `/ai/analyze` 建立独立的评估集，重点测量 `riskLevel` 的准确率和 `suggestion` 的临床合理性。

---

## 总结

NeuroAgentSystem 的模型层是一个工程质量较高、设计思路清晰的医学 AI 推理系统。主要亮点：

- **SimpleGraph 自实现状态机**：避免 LangGraph 依赖，逻辑透明
- **proposer + critic 双轨制**：用低成本模型做批判性审查，兼顾质量与成本
- **完善的流式工程**：心跳机制、Token 聚合、SSE 双写兼容
- **神经医学专项评估体系**：Ragas 指标 + 数据可视化

核心改进方向按优先级：

1. **P0**：`/ai/analyze` 接入 RAG 或加免责声明（幻觉风险直接影响医疗安全）
2. **P0**：增强数据清洗 pipeline（污染数据会持续降低检索质量）
3. **P1**：文献截断字符从 400 提升至 600-800
4. **P1**：`done` 事件与 all_info 更新解耦（用户体验）
5. **P1**：Reranker 异常在 `fast_retrieve()` 层 catch，防止推理中止
