基于你提供的项目代码片段、错误日志以及文件结构路径，以下即为专门为你生成的详细 **README.md** 文档。

该文档包含了项目背景、核心流程、技术栈、目录结构、环境配置以及亮点说明。

***

# MedLLM - 基于大模型的智能医疗问答系统

**MedLLM** 是一个基于 **RAG (检索增强生成)** 技术与 **LangChain Agent** 架构的垂直领域医疗问答系统。它利用通义千问 (Qwen-Max) 作为核心推理引擎，结合本地构建的医疗指南知识库，能够针对复杂的医疗问题（如临床指南、用药建议、症状分析）提供基于证据的精准回答。

## 🌟 项目亮点

1.  **ReAct/Tool Calling 智能代理**
    *   抛弃传统的“检索-问答”线性逻辑，采用 Agent 模式。系统能自主判断是否需要查询知识库，甚至能够处理多步推理任务。
    *   使用了 LangChain 最新的 `create_tool_calling_agent` 架构，支持函数调用 (Function Calling)，使模型与工具的交互更稳定。

2.  **严谨的医疗 RAG 流程**
    *   集成 `UnifiedSearchEngine`，针对医疗数据进行了专门的清洗和索引。
    *   配置了 `temperature=0` 的模型参数，最大程度降低大模型的幻觉（Hallucinations），确保医疗建议的严肃性。

3.  **鲁棒的工程实现**
    *   具备完善的错误处理机制 (`handle_parsing_errors=True`)，当模型输出格式异常时能自动修正。
    *   针对检索服务增加了异常防护，防止因检索引擎未启动导致的系统崩溃。

4.  **现代化技术栈**
    *   基于 **FastAPI** 的高性能异步接口服务。
    *   对接阿里 **Qwen-Max (通义千问)** 旗舰模型，中文医疗语义理解能力强。

---

## 🛠️ 技术栈

*   **编程语言**: Python 3.10+
*   **Web 框架**: FastAPI, Uvicorn
*   **LLM 编排**: LangChain Core, LangChain Community
*   **大模型 (LLM)**: Alibaba Tongyi Qwen-Max (`ChatTongyi`)
*   **检索/向量库**: 自研/封装的 `UnifiedSearchEngine` (基于 FAISS 或 Chroma)
*   **开发环境**: PyCharm, Anaconda (Windows)

---

## 📂 项目目录结构

```text
MedLLM/
├── Agent/
│   └── qwen/
│       ├── medicalAgent.py          # (旧) 医疗 Agent 定义
│       ├── medicalAgentExecutor.py  # [核心] 当前使用的 Agent 执行器，集成 Tool Calling
│       └── qwenAssistant.py         # 助手类封装
├── makeData/
│   ├── dataRetrieve.py              # 统一检索引擎 (UnifiedSearchEngine) 实现
│   └── ...                          # 数据处理与向量化脚本
├── main.py                          # FastAPI 入口文件
├── requirements.txt                 # 项目依赖
└── README.md                        # 说明文档
```

---

## 🔄 系统工作流程 (Pipeline)

1.  **用户请求 (Request)**: 用户通过 API 发送医疗问题（例如："帕金森病早期的推荐治疗方案是什么？"）。
2.  **Agent 规划 (Planning)**:
    *   `MedicalAgent` 接收输入。
    *   Prompt System 设定角色为“专业医疗助手”。
    *   LLM (Qwen-Max) 分析意图，判断是否需要调用工具。
3.  **工具调用 (Tool Execution)**:
    *   如果需要外部知识，模型生成调用 `search_medical_guidelines` 的指令。
    *   `UnifiedSearchEngine` 在本地向量库中检索 Top-K 相关文档（如临床试验结论、指南原文）。
4.  **上下文合成 (Synthesis)**:
    *   检索到的证据片段作为 Observation 返回给 Agent。
    *   Agent 将原始问题 + 检索到的证据 + 历史对话 重新整合。
5.  **生成回答 (Response)**:
    *   LLM 基于事实证据生成最终回答，并在前端返回。

---

## 🚀 快速开始

### 1. 环境准备

确保已安装 Anaconda 或 Python 环境。

```bash
# 创建虚拟环境
conda create -n Medllm python=3.10
conda activate Medllm

# 安装依赖 (建议根据报错补充具体版本，尤其是 langchain-community)
pip install langchain langchain-core langchain-community dashscope fastapi uvicorn
```

### 2. 配置 API Key

需要在环境变量中配置通义千问的 API Key。
*   **Windows Powershell**: `$env:QWEN-API-KEY="sk-xxxxxxxx"`
*   或者在代码根目录创建 `.env` 文件。

### 3. 代码修正说明

针对日志中出现的 `NotImplementedError` (bind_tools 错误)，请确保 `Agent/qwen/medicalAgentExecutor.py` 使用了正确的导入（如当前代码片段所示），并且 `langchain-community` 包已更新到最新版本，因为旧版本的 `ChatTongyi` 可能不支持 `bind_tools`。

### 4. 启动服务

在项目根目录下运行：

```bash
python main.py
```
或者使用 uvicorn 直接启动：
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📝 API 接口示例

### 1. 流式临床推理

**POST** `/model/get_result`

```json
{
  "question": "患者突发言语不清伴右侧肢体无力2小时",
  "all_info": "",
  "token": "your-jwt-token",
  "report_mode": "emergency",
  "show_thinking": true
}
```

### 2. AI 分析病人健康风险

**POST** `/ai/analyze`

```json
{
  "patientId": 1,
  "data": "男，68岁，既往高血压、糖尿病。今日突发头晕伴右侧肢体乏力3小时，血压180/110mmHg。",
  "all_info": "",
  "token": "your-jwt-token"
}
```

**响应：**

```json
{
  "code": 1,
  "msg": "success",
  "data": {
    "riskLevel": "高风险",
    "suggestion": "建议尽快完善相关检查并由专科医生进一步评估，密切监测病情变化。",
    "analysisDetails": "血压显著升高，伴突发神经功能缺损表现，结合既往高血压和糖尿病病史，提示存在较高脑血管事件风险。"
  }
}
```

- `patientId`：病人 ID，仅用于业务侧关联。
- `data`：病人主诉、病史、体征、检查结果等文本。
- `all_info`：可选的历史上下文补充信息。
- `token`：必填 JWT，用于和 `/model/get_result` 保持一致的鉴权策略。
- 返回字段 `riskLevel` 固定为：`低风险` / `中风险` / `高风险`。

### 3. 旧示例

**POST** `/chat`

```json
{
  "query": "ropinirole与rotigotine在帕金森早期治疗中的副作用对比",
  "history": []
}
```

**响应:**

```json
{
  "response": "根据临床证据显示，在帕金森早期治疗中：\n1. Ropinirole 在改善运动功能方面可能比 Rotigotine 更有效... \n2. 在副作用导致的停药率方面，两者没有显著差异..."
}
```

---

## ⚠️ 常见问题排查 (Troubleshooting)

1.  **`NotImplementedError` via `bind_tools`**:
    *   原因：`ChatTongyi` 类在旧版 LangChain 中未实现工具绑定接口。
    *   解决：`pip install --upgrade langchain-community dashscope`。

2.  **`search_clinical_guidelines` 报错**:
    *   如果日志显示 "Got unknown type content"，这是 Agent 解析检索内容时的格式问题。当前代码已通过 `handle_parsing_errors=True` 缓解此问题。

3.  **OpenAI 风格代理错误**:
    *   请务必使用 `create_tool_calling_agent` 而非 `create_openai_functions_agent`，因为 Qwen 的工具调用协议与 OpenAI 不完全兼容，通用工具代理更适配。
