# NeuroAgentSystem

**多智能体深度检索医疗辅助系统 (Multi-Agent Deep Retrieval Model)**

本项目是一个基于**流式输出架构（SSE）**的多智能体医疗辅助诊疗健康系统。通过前后端分离以及独立的 AI 模型服务层，实现了基于 RAG（检索增强生成）机制的角色扮演式多智能体患者档案管理、智能问诊对话和医学知识辅助，支持打字机级别的低延迟流式响应。

---

## 🛠 技术栈与项目架构

项目采用典型的三层微服务架构，核心是通过 SSE (Server-Sent Events) 实现模型推理链路向前端的实时推送。

### 1. 前端表现层 (Frontend)
> **医疗 RAG 大语言模型前端项目**
- **核心技术**: Vue 3 (Composition API) + Vite 7 + Pinia (状态持久化) + SCSS
- **功能特性**:
  - 🚀 **流式对话**: 实现基于 `fetch` + `ReadableStream` 的流式问答对话框，支持实时渲染打字机效果。
  - 🔐 **用户体系**: 用户鉴权（登录、注册）、个人资料与头像管理。
  - 📝 **历史记录**: 多轮历史对话记录管理（列表展示、继续对话、删除对话）。
- **组件化**: 使用 Axios 封装 HTTP 请求，配置了完善的 ESLint + Prettier 规范。

### 2. 后端服务层 (Backend / MyServer)
> **基于 Spring Boot 3 的高并发 AI 对话系统**
- **核心技术**: Java 17 + Spring Boot 3 + Spring WebFlux (Project Reactor) + MyBatis-Plus
- **数据库与中间件**: MySQL 8.0 + Redis 6.0 + Redisson (分布式锁与信号量限流)
- **亮点特性**:
  - ⚡ **响应式流式通信**: 全面使用 `WebClient` 与 `Flux`，彻底解决传统 I/O 阻塞问题，保证高并发场景下的极速响应。
  - 🛡️ **双重安全鉴权**: 
    - 基于 Redis 实现 Token 无感保活/自动续期 (`RefreshTokenInterceptor`)。
    - 基于单设备登录的 JTI (JWT ID) 互斥机制，实现“踢人下线”。
  - 🚦 **分布式限流与异步落库**: Redisson `RSemaphore` 控制 AI 模型并发调用量；采用线程池实现流式响应与聊天记录 MySQL 持久化的异步解耦。
  - 🧵 **线程隔离**: 采用 ThreadLocal 传递线程级用户上下文，保证请求数据安全性与开发便捷性。

### 3. 模型推理层 (Model)
> **高效多智能体编排与异步推理引擎**
- **核心技术**: Python 3.11 + FastAPI + 异步 asyncio
- **机制原理**: 
  - 🤖 **医疗智能体系统**: 搭载角色扮演式医疗多智能体系统。为保障 Web 端极致的响应速度，摒弃了冗杂的传统设计模式，采用深度优化的高效智能体编排流程，兼顾高性能与高质量输出。
  - 🌊 **异步事件流**: 通过 `asyncio.Queue` 与 `yield` 迭代器，源源不断地向后端抛出多种类型的 JSON 事件流（包括思考过程 `thinking`、元数据 `meta` 以及最终推理结果 `result`）。

### 🔄 全链路流式数据管道 (SSE Pipeline)
```text
用户提问 ➡️ Java鉴权与限流 ➡️ WebClient ➡️ FastAPI ➡️ Python模型(yield) ➡️ asyncio.Queue ➡️ Java(Flux推送) ➡️ Vue(ReadableStream实时渲染)
```

---

## ✨ 系统核心业务功能

1. 🏥 **医疗智能问答系统 (RAG)**
   - 多轮对话支持与上下文记忆，根据用户描述的症状自动调取后台知识进行深度推理。
   - **思考透明化 (Thinking Step)**: 响应流中实时包含 AI 思考过程，让用户直观了解诊断依据。
2. 📊 **患者档案与风险评估 (EHR)**
   - 支持健康数据（如血压、血糖等）的统一录入与管理。
   - **多维健康画像**: AI 综合分析历史病历和当前检验报告，自动生成风险等级（高/中/低）并给出动态医学建议 (`aiOpinion`)。
   - **对话同步机制**: 允许将用户问诊过程脱敏后，同步到病历系统以修正健康风险评估。
3. 📚 **医疗知识库与教育**
   - 提供供医生和患者学习的医学知识库（如高血压指南），支持按分类检索与展示。
4. 🔐 **统一账户安全体系**
   - 集成基于 JWT 与 Redis 的鉴权机制，支持患者头像文件上传及个人信息变更。

---

## 🚀 架构演进与优化计划

为了提供更加极致和稳定的流式输出体验，系统目前正按以下三个阶段进行重构（详情参考 `docs/流式输出架构改进方案.md`）：

| 阶段 | 核心目标 | 具体内容 | 优先级 |
|------|----------|--------|--------|
| **Phase 1** | 紧急修复与解耦 | 心跳保活机制 (Keep-Alive)、结构化错误码、流数据与 MySQL 持久化彻底异步解耦。 | P0 🔴 |
| **Phase 2** | 稳定性提升与背压 | 引入有界队列控制内存溢出、Thinking 流数据压缩、前端 `parseModelLine` 解析容错处理。 | P1 🟠 |
| **Phase 3** | 体验终极优化 | 断线续传协议支持、端到端 (Trace) 链路追踪。 | P2 🟡 |

---

## 💻 开发者指南

1. **代码规范**：
   - **Java 层**：必须遵守 Spring WebFlux 的响应式编程范式。
   - **Python 层**：遵循 PEP 8 规范，全程使用 `async/await` 处理异步操作。
   - **前端层**：遵循 Vue 3 Composition API 最佳实践，组件采用 PascalCase 命名。
2. **兼容性要求**：所有的改动必须**向后兼容**，绝对不能破坏现有的 SSE 事件通信格式。
3. **本地启动**：
   - 配置 `backend/src/main/resources/application.yml` 中的 MySQL 和 Redis 连接，运行 `MyServerApplication.java`。
   - 进入 `frontend/` 目录执行 `npm install` 与 `npm run dev`，前端默认代理到 `8080` 端口。
