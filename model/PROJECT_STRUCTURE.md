# Neuro-Multi-Agent 项目架构与代码文件说明

经过近期的多智能体架构升级、混合特征抽取的检索增强体系（Dual-RAG）重构以及模块化分类，整个项目已完成高度解耦。以下为全项目系统文件所承担的**功能角色说明文档**。

---

## 1. 全局入口与服务层

*   **`app/main.py`**
    *   **作用**：FastAPI 后端服务器入口点。负责注册核心 API 路由（如分析接口、PubMed接口等），加载全局中间件，提供基于 Server-Sent Events (SSE) 的流式打字机输出接口封装。

*   **`.env`** 
    *   环境变量文件（存放 API 密钥、数据库路径、端口等鉴权配置）。
*   **`requirements.txt`** 
    *   核心 Python 第三方依赖包清单。
*   **`README.md` & `MIGRATION_*.md`**
    *   系统使用说明文档及迁移日志信息，指导架构升级流程与重构状态。

---

## 2. RAG (混合检索生成系统) - `app/rag/`

提供系统最底层的“医学知识补全”功能，它将本地医学指南书籍进行向量嵌入和实时检索召回：

*   **`data_loader.py`**
    *   **作用**：文档解析与分块管道。扫描指定目录的 PDF，将其智能切割成合适长度的 Chunk 纯文本片段以备处理。
*   **`qa_generator.py`**
    *   **作用**：数据蒸馏拓展。调用 Qwen大模型对原本“稀疏文本”的内容预先批量化生成问答对（QA Pairs），增强医学术语检索的召回率。
*   **`retrievers.py`**
    *   **作用**：混合检索引擎核心（`UnifiedSearchEngine`）。内含双路召回（BM25 关键词匹配 + 向量嵌入搜索 DashScope Text Embedding），且接入了 `gte-rerank` 进行深度分数重排获取精简的 Top-K 知识条目。
*   **`retrieve.py`**
    *   **作用**：旧版本的单体化检索执行工具（兼容类过渡方案）。

---

## 3. Agents 多智能体决策层 - `app/agents/`

采用 LangGraph 状态机编排模式与 Agentic RAG 思路构建临床辅助系统：

*   **`orchestrators/` (核心决策编排网络)**
    *   **`clinical_graph.py`**: 基于状态机的图推理引擎，把临床询问定义成多个互相校验的节点工作流。
    *   **`nodes/*.py`** (如 `intent_node.py`, `analysis_node.py`, `reason_node.py`): LangGraph 的各个功能节点处理器（意图识别判定、结构化病情拆解、证据批判推理与报告合并等）。
    *   **`qwen_agent.py`**: 基于 Qwen 模型旧版主架构文件或特定场景推理逻辑封装编排。
*   **`qwen/` (Qwen 专业模型适配)**
    *   **`medical_agent.py`**: 新版医疗 Qwen-Turbo 专精大模型智能体引擎类，封装推理对话执行和报告调配。
*   **`bailian/`**
    *   **`health_risk_analyzer.py`**: 调用阿里云大模型环境进行极速健康风险评测的轻量级 Agent。
*   **`pipelines/` & `services/` & `schemas/`**
    *   **`rag_pipeline.py` / `retrieval_service.py` / `query_service.py`**: 实现从“用户原始问句 -> 检索优化问句 -> 统一 RAG 派发查询”的微任务流水线。
    *    **`core/` & `utils/` (Agent 层配套)**
        *   **`result.py`, `schema.py`, `exceptions.py`**: 智能体通讯中的异常捕捉规范及输入输出格式合法性检查。
        *   **`json_parser.py`, `llm_helper.py`, `retry.py`**: 确保模型输出 JSON 稳定性及 API 防抖重试底座。
    *   **`infra/base_reranker.py`**: 定义大模型外接独立重排基类依赖。

---

## 4. 全局辅助工具与第三方整合

*   **`app/services/` (外部数据接驳)**
    *   **`pubmed_service.py`**: 封装请求 PubMed API 进行海外权威医学论文数据库查阅支持的功能。
    *   **`vision_service.py`**: 基于多模态大模型的检验影像/图片报告等视觉识别理解接口支持。
    
*   **`app/config/` (中央配置库)**
    *   **`config_loader.py`**: `ConfigManager` 读取 YAML 和 Env 等环境应用信息。
    *   **`prompts.yaml` & `report_templates.yaml`**: 将长串的角色设定 prompt 与前端模板独立，脱离硬编码，便于迭代微调。
    
*   **`app/utils/` (公共函数)**
    *   **`error_codes.py`**: 前后端错误抛出状态码格式化对照。
    *   **`context_summary.py`**: 上下文滑动窗截断和 Token 摘要瘦身过滤。

---

## 5. 常量数据集与产出目录

*   **`Data/documents/`**: 静态文件池，预置存储了多份《急性缺血性脑卒中管理指南》等权威临床资料 PDF 原文。
*   **`app/chroma_db_unified/`**: ChromaDB 本地化数据卷文件夹（SQL 与向量索引存储于此，保证离线召回能力）。
*   **`data_exports/`**: 业务运行状态下各类缓存（例如 `medical_agent_eval_details.csv`）落盘文件。

---

## 6. 测试与科学评估体系

*   **`tests/` (功能与接口联调测试)**
    *   **`test_rag.py` / `run_search.py`**: 从底层直接跑通文本切割到 QA 切片再到文档召回的“搜集”阶段单元测试。
    *   **`test_api_client.py`**: 完整前端 HTTP 会话模拟脚本验证。用于检查 API `/ai/analyze` 与鉴权加密。
    *   **`test_new_architecture.py`**: 全链路针对图编排等新功能的系统级冒烟集成测试。
    
*   **`evaluation/` (客观质量评估)**
    *   **`getTestData.py`**: 根据指定标注集自动爬取或跑批回看 AI 返回性能。
    *   **`expand_contexts_resume.py`**: 基于 Ragas 等自动化评测框架进行答案“幻觉率”和“准确率”评估与打分断点续传。

