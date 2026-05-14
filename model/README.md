# MedLLM / NeuroMultiAgentSystem
**多智能体深度检索医疗辅助系统 (Multi-Agent Deep Retrieval Model)**

**MedLLM** (NeuroMultiAgentSystem) 是一个面向脑卒中临床场景的智能医疗辅助系统，旨在通过人工智能技术提升临床辅助决策支持能力。系统以大语言模型为核心，融合检索增强生成（RAG）、多智能体推理与医学知识库，实现了从症状输入到辅助分析与建议输出的完整闭环。

与传统通用问答系统不同，本项目并非简单依赖模型生成结果，而是以权威医学文献与临床指南为知识底座，通过“检索—重排—推理—评估”的结构化流程，使每一次回答都具备明确证据来源与逻辑依据。系统强调**“证据先行、过程可解释、结果可验证”**，在保证智能化水平的同时，显著提升了医学场景下的可靠性与安全性。

## 🌟 项目亮点与创新

1.  **证据驱动的医学推理范式与定制 RAG**
    *   将证据获取前置，实现了从“模型主导”向“证据主导”的转变，降低幻觉风险。基于混合检索（向量 + BM25）策略，优先返回权威指南与最新文献。强化对脑卒中时间窗、溶栓/取栓指征等关键信息的提取。
2.  **多智能体协同的安全推理机制 (Proposer-Critic-Integrator)**
    *   **Proposer (生成智能体)**：基于证据生成初步诊疗方案。
    *   **Critic (审查智能体)**：独立执行风险审查，识别临床高风险点（如时间窗陷阱、禁忌症）。
    *   **Integrator (整合反思智能体)**：融合反思生成最终安全结论。模拟“提出方案→上级把关→最终复盘”的真实流程。
3.  **大模型高级 QA 自建引擎与重排优化**
    *   在知识库层引入批处理扩写：系统精读医疗 PDF 并自动提炼生成高质量 QA 对。结合阿里 `gte-rerank` 进行深度语境打分与证据压缩，并在引用中进行文献与页码明确溯源。
4.  **工程化生态与全链路流式推送 (SSE Pipeline)**
    *   拥有可见的思考过程（Thinking Step）推理展示以及动态多路分发机制。
    *   **架构闭环**：结合了基于 WebFlux 与 Redis 并发控制的后台以及 Vue3 流式渲染界面。

---

## 🛠️ 技术栈与全链路架构

本项目采用典型的前后端分离与模型服务独立部署的三层架构，构成了极具扩展性的 CDSS（临床决策支持系统）原型：

*   **模型服务核心 (Python层 - 本仓库涉及主体)**: 高并发 FastAPI, LangChain Agent 架构, Qwen-Max大模型, Chroma/BM25 混合向量检索
*   **后端服务层**: Java 17 + Spring Boot 3 + Spring WebFlux 响应式框架, MySQL 8.0, Redis + Redisson 分布式控制与 JWT 鉴权
*   **前端展示层**: Vue 3 (Composition API), Vite, Pinia, 以及流式数据的实时图文响应渲染
*   **📡 数据流向管道**: 用户提问 ➡️ Java鉴权与请求隔离 ➡️ WebClient 异步 ➡️ FastAPI ➡️ Python Agent 流式产出(yield) ➡️ asyncio.Queue ➡️ Java(Flux持续推送) ➡️ Vue(ReadableStream实时渲染) 

---

## 📂 项目目录结构

```text
D:\pycharmProject\neuro-multi-agent
├── Agent/               # [核心模型能力]：各模块的大语言模型推理链路（Qwen、Bailian）
├── config/              # [配置中心]：存放统一规则 Prompt 的 YAML 与配置加载器
├── Data/                # [数据资产]：如 ./documents 存放需要进行 RAG 识别的原版医疗 PDF 讲义与指南
├── makeData/            # [知识加工]：文档切割、QA片段生成扩展和统一向量建立中心 (retrievers.py 等)
├── services/            # [外部/专用服务]：如 PubMed 文章搜索服务、视觉大模型识别服务 (vision_service.py)
├── utils/               # [工具库]：各类基础通用工具，如报错标准化 (error_codes.py)、token计算、命名归纳等
├── evaluation/          # 🌟[评测专区]：跑分机制与造出来的上下文片段都放在这独立运行
├── data_exports/        # 🌟[实验归档]：存放所有系统在评测与处理后生成的实验对照记录 `.csv` 结果合集
├── tests/               # 🌟[测试验证]：如测试 RAG (test_rag.py) 和测试接口流式输出 (test_api_client.py)
│
├── chroma_db_unified/   # ChromaDB 向量本地化持久存储端
├── requirements.txt     # Python 环境依赖清单
├── .env                 # 您的本地环境安全密钥记录配置
└── main.py              # 🚀[入口网关]：全局 FastAPI 路由以及启动主程序入口
```

---

## 🔄 系统核心链路流程

1.  **用户提问触发**：前台发来病理文本（甚至带图片）。鉴权通过（JWT 校验）后建立 SSE 长连接。
2.  **诊断与智能分发**：系统评估请求的 `question` 和 `all_info`(病史上下文)。利用 Naming 模型并发启动对该次聊天的病种标记。
3.  **大混合双重检索 (Hybrid RAG)**：调用 `makeData/retrievers.py` 中的 `UnifiedSearchEngine` 从本地检索与当前体征关联度高的《临床指南指南》段落或提前做好的 QA 衍生库片段。
4.  **大模型思考与推测**：医学助理 Agent 汇集所有的精准片段作为 `background_info` 给到 Qwen-Max 进行多步严谨推演，将有价值的思考块 `thinking` 逐步以串流发送至前台。
5.  **总结反刍更新**：流式推送完结论后，再启动后台打杂小模型总结这次对话重点更新回 `all_info`，为用户的多轮就诊做足铺垫。

---

## 🚀 快速接入

### 1. 环境准备与依赖安装

建议通过 Anaconda 新建虚拟环境屏蔽本机干扰。

```bash
conda create -n neuro-model python=3.10
conda activate neuro-model

pip install -r requirements.txt
```

### 2. 本地秘钥 `.env` 配置

在根目录新建或者修改 `.env` 文件，加入阿里云百炼 API 的密钥和 JWT 认证种子：

```env
DASHSCOPE_API_KEY="sk-您自己在阿里云百炼平台申请的秘钥"
SECRET_KEY="您自定义防止用户越权访问后端的随机字符串"
```

### 3. 数据知识库建设 (RAG 核心底座)

把医疗领域的临床指南等 PDF 文件统一放入 `Data/documents/` 文件夹。

**启动时的大模型打底入库过程揭秘**：
当您第一次启动系统或更换了新一批文档时，系统底层的 `makeData/retrievers.py` 会做以下一系列重量级操作：
1. **自动递归分块 (Recursive Chunking)**：程序会采用 512 字长配 128 字重叠的规则，跨层级用段落、句号作为自然分割符将几十个 PDF `split_documents` 切成上千条长块。
2. **大模型 QA 衍生 (AI Batch QA Generation)**：为防止干涩长段落不易被召回，如果启用了 `"enable_qa_generation": True`，系统会将这上千页纯文本块每10条打包发送给底层的 Qwen-Turbo，用模型独有的归纳能力从里头“反向做题”，提取出几百条 `Q: ...? A: ...` 并打上原文页码标签！
3. **混合双索引编织 (Dual-Indexing)**：最后将上述数千条“原生块”+“造出的 QA”进行向量化放进独立的 ChromaDB，另外在内存挂载高频词组的 BM25 索引。这样庞大的底座就造好了！

### 4. 启动与测试

首选在终端 `A` 拉起总网关服务：
```bash
python main.py
# 服务会默认监听 0.0.0.0:8000
```
待其控制台输出初始化组装就绪后，新开终端 `B` 进行各类子项目测试：
```bash
# 测试核心多智能体和临床指南 RAG 推测的流式问诊能力 
python tests/test_api_client.py 

# 跳过网络直接测本地向量数据库召回水平的独立脚本
python tests/test_rag.py
```

---

## 📝 核心 API

### 主要推理流：`/model/get_result`
- 特性：结合多智能体与RAG对重症、急诊情况分析。
- 协议：SSE
- 参数包含：`question` (当前新症状), `all_info` (历史上下文拼接), `report_mode` (诊断模式) 等。

### 独立风险归纳：`/ai/analyze`
- 特性：不需要进行检索，专注于独立分析大段病历评估急用风险。
- 返回：包括 `riskLevel`, `suggestion`, `analysisDetails` 格式明确的结果。

### 外部补充抓取：`/model/pubmed/search`
- 特性：连接国家生化信息中心的 API 直接根据症状抓取相关最新外文文章列表。

---
