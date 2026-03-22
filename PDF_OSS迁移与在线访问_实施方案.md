# PDF 文档 OSS 迁移与在线访问 —— 实施方案

> 需求对齐日期：2026-03-22
> 项目架构：Python/FastAPI（模型层）+ Java/Spring WebFlux（中间层）+ Vue 3（前端）

---

## 一、需求总结

| 编号 | 需求 | 关键约束 |
|------|------|---------|
| R1 | 将服务器 `/Data/documents` 下的 PDF 上传至 Ali OSS | 服务器原文件保留（RAG 检索依赖）；保持子文件夹分类结构 |
| R2 | "医生学习"页面添加文档浏览入口，支持在线预览和下载 | 仅登录用户可访问；使用 OSS 签名 URL 控制权限 |
| R3 | AI 对话回答中的参考文献变为可点击链接，点击后可预览或下载 | 文献名与 PDF 文件名一致；文献名混在纯文本中，需前端解析 |

---

## 二、技术决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 后端对接层 | Java/Spring 中间层 | 文件资源管理与 AI 推理职责分离；Spring 层已有 JWT 认证 |
| OSS 访问方式 | 私有 Bucket + 签名 URL | 登录可见需求；签名 URL 有效期 30 分钟，过期自动失效 |
| PDF 预览方案 | PDF.js（vue-pdf-embed） | 比 iframe 方案更可控：支持翻页、缩放、搜索、自定义 UI；不依赖浏览器原生 PDF 插件；移动端兼容性更好 |
| 服务器文件处理 | 保留不删 | RAG 系统（Chroma + BM25）依赖本地文件做索引 |

---

## 三、整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Vue 3 前端                            │
│                                                         │
│  ┌──────────────┐   ┌───────────────────────────────┐   │
│  │  医生学习页面  │   │   AI 对话页面                  │   │
│  │              │   │                               │   │
│  │  文档分类列表  │   │  回答正文                      │   │
│  │  ├─ 指南     │   │  ...                          │   │
│  │  ├─ 教材     │   │  参考文献：                     │   │
│  │  └─ 文献     │   │  【文献1】《xxx指南》 ← 可点击   │   │
│  │              │   │  【文献2】《yyy教材》 ← 可点击   │   │
│  │  [预览] [下载]│   │                               │   │
│  └──────┬───────┘   └──────────┬────────────────────┘   │
│         │                      │                         │
│    ┌────▼──────────────────────▼─────┐                   │
│    │    PDF 预览弹窗（vue-pdf-embed） │                   │
│    │    [翻页] [缩放] [下载] [关闭]    │                   │
│    └────────────────┬────────────────┘                   │
└─────────────────────┼───────────────────────────────────┘
                      │ HTTP（携带 JWT）
┌─────────────────────▼───────────────────────────────────┐
│              Java/Spring WebFlux 中间层                   │
│                                                         │
│  GET  /api/documents              → 获取文档列表（含分类）│
│  GET  /api/documents/{id}/url     → 获取签名 URL         │
│  GET  /api/documents/match?name=  → 按文献名匹配文档      │
│                                                         │
│  ┌─────────────────────┐   ┌──────────────────────┐     │
│  │  OssService         │   │  DocumentService     │     │
│  │  - generateSignUrl()│   │  - listByCategory()  │     │
│  │  - uploadFile()     │   │  - matchByName()     │     │
│  └────────┬────────────┘   └──────────────────────┘     │
└───────────┼─────────────────────────────────────────────┘
            │ HTTPS
┌───────────▼─────────────────────────────────────────────┐
│                    Ali OSS（私有 Bucket）                 │
│                                                         │
│  documents/                                              │
│  ├── 指南/                                               │
│  │   ├── 急性缺血性脑卒中诊治指南2024.pdf                  │
│  │   └── ...                                            │
│  ├── 教材/                                               │
│  │   └── ...                                            │
│  └── 文献/                                               │
│      └── ...                                            │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│         服务器 /Data/documents（保留不动）                 │
│         └── RAG 系统（Chroma + BM25）持续使用             │
└─────────────────────────────────────────────────────────┘
```

---

## 四、分步实施计划

### 第一步：OSS 文件迁移（一次性操作）

**操作位置**：宝塔服务器终端

**目标**：将 `/www/wwwroot/Python-backend/Data/documents` 下的所有 PDF（含子目录结构）上传至 OSS。

**工具**：使用阿里云 ossutil 命令行工具，一条命令即可保持目录结构上传。

```bash
# 1. 安装 ossutil（如果尚未安装）
curl -o /usr/local/bin/ossutil64 https://gosspublic.alicdn.com/ossutil/1.7.19/ossutil-v1.7.19-linux-amd64/ossutil64
chmod 755 /usr/local/bin/ossutil64

# 2. 配置 AccessKey
ossutil64 config -e oss-cn-<你的region>.aliyuncs.com -i <AccessKeyId> -k <AccessKeySecret>

# 3. 批量上传，保持目录结构
ossutil64 cp -r /www/wwwroot/Python-backend/Data/documents/ oss://<你的bucket名>/documents/ --include "*.pdf"

# 4. 验证上传结果
ossutil64 ls oss://<你的bucket名>/documents/ -s
```

**注意**：上传完成后服务器上的原文件不要删除，RAG 系统仍然依赖它们。

---

### 第二步：Spring 中间层 —— OSS 接口开发

**目标**：暴露 3 个 API，供前端获取文档列表和签名 URL。

#### 2.1 依赖引入

```xml
<!-- pom.xml -->
<dependency>
    <groupId>com.aliyun.oss</groupId>
    <artifactId>aliyun-sdk-oss</artifactId>
    <version>3.17.4</version>
</dependency>
```

#### 2.2 配置文件

```yaml
# application.yml
aliyun:
  oss:
    endpoint: oss-cn-<你的region>.aliyuncs.com
    access-key-id: ${OSS_ACCESS_KEY_ID}        # 建议通过环境变量注入
    access-key-secret: ${OSS_ACCESS_KEY_SECRET}
    bucket-name: <你的bucket名>
    document-prefix: documents/                  # OSS 中的根路径
    sign-url-expiration: 1800                    # 签名 URL 有效期，单位秒（30分钟）
```

#### 2.3 核心 Service

```java
@Service
public class OssDocumentService {

    private final OSS ossClient;
    private final String bucketName;
    private final String prefix;
    private final long expiration;

    // 获取文档列表（按分类），返回 category → [文件名] 的结构
    public Map<String, List<DocumentVO>> listDocuments() {
        // 使用 ossClient.listObjectsV2() 列出 prefix 下所有 PDF
        // 按子目录（第一级路径）分组作为分类
        // 每个文件返回：id（OSS key 的 Base64 编码）、name（文件名）、category（分类名）、size
    }

    // 根据文档 ID 生成签名 URL
    public String generateSignedUrl(String documentId) {
        // documentId 解码为 OSS key
        // 调用 ossClient.generatePresignedUrl(bucketName, key, expiration)
        // 返回带签名的临时访问 URL
    }

    // 根据文献名模糊匹配文档（供 AI 对话引用使用）
    public DocumentVO matchByName(String referenceName) {
        // 从文档列表中模糊匹配文件名
        // 匹配策略：去掉书名号和扩展名后做 contains 匹配
        // 例如：输入"急性缺血性脑卒中诊治指南" → 匹配到 "急性缺血性脑卒中诊治指南2024.pdf"
    }
}
```

#### 2.4 Controller 接口

```java
@RestController
@RequestMapping("/api/documents")
public class DocumentController {

    // GET /api/documents
    // 返回按分类分组的文档列表
    // 需要 JWT 认证
    @GetMapping
    public Mono<Map<String, List<DocumentVO>>> listDocuments();

    // GET /api/documents/{id}/url
    // 返回签名 URL（用于预览和下载）
    // 响应示例：{ "previewUrl": "https://...", "downloadUrl": "https://...&response-content-disposition=attachment" }
    @GetMapping("/{id}/url")
    public Mono<DocumentUrlVO> getSignedUrl(@PathVariable String id);

    // GET /api/documents/match?name=急性缺血性脑卒中诊治指南
    // AI 对话中的文献名 → 匹配到具体文档 → 返回文档信息和签名 URL
    @GetMapping("/match")
    public Mono<DocumentUrlVO> matchDocument(@RequestParam String name);
}
```

**关于预览和下载的区分**：同一个签名 URL 可以通过 `response-content-disposition` 参数控制行为：
- 预览 URL：不带该参数，浏览器默认 inline 展示
- 下载 URL：追加 `?response-content-disposition=attachment%3Bfilename%3Dxxx.pdf`，强制下载

---

### 第三步：Vue 前端 —— "医生学习"页面

**目标**：在已有的"医生学习"页面中展示文档列表，支持分类浏览、在线预览和下载。

#### 3.1 安装 PDF 预览组件

```bash
npm install vue-pdf-embed pdfjs-dist
```

#### 3.2 页面结构

```
┌──────────────────────────────────────────────────┐
│  医生学习                                         │
│                                                  │
│  [指南]  [教材]  [文献]     ← 分类 Tab 切换        │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │  📄 急性缺血性脑卒中诊治指南2024.pdf        │    │
│  │     大小：2.3 MB                         │    │
│  │     [在线预览]  [下载]                    │    │
│  ├──────────────────────────────────────────┤    │
│  │  📄 脑出血诊疗规范2024.pdf                │    │
│  │     大小：1.8 MB                         │    │
│  │     [在线预览]  [下载]                    │    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

#### 3.3 PDF 预览弹窗组件（可复用）

创建一个通用的 `PdfPreviewModal.vue` 组件，供"医生学习"页面和 AI 对话页面共同使用：

```
┌──────────────────────────────────────────┐
│  📄 急性缺血性脑卒中诊治指南2024.pdf  [✕] │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │                                  │    │
│  │       PDF 内容渲染区域            │    │
│  │       (vue-pdf-embed)            │    │
│  │                                  │    │
│  └──────────────────────────────────┘    │
│                                          │
│  [上一页] 第 3 / 28 页 [下一页]  [下载]    │
└──────────────────────────────────────────┘
```

核心 props：
- `url`：签名 URL（从后端获取）
- `fileName`：显示名称
- `visible`：控制显示/隐藏

---

### 第四步：Vue 前端 —— AI 对话文献引用可点击

**目标**：将 AI 回复正文中的参考文献纯文本解析为可点击链接，点击后弹出预览/下载选项。

#### 4.1 文献名解析策略

根据你的 AI 回复格式（参见分析报告中的描述），参考文献通常以如下格式出现：

```
【文献1】[来源: 《急性缺血性脑卒中诊治指南2024》 p.12] (相关度:0.87)
```

前端解析步骤：
1. 用正则匹配书名号内的内容：`/《([^》]+)》/g`
2. 提取出文献名后，调用 `GET /api/documents/match?name=文献名`
3. 如果匹配成功，将该文本替换为可点击的链接组件
4. 如果匹配失败（该文献不在 OSS 上），保持原样纯文本显示

#### 4.2 渲染逻辑

```
原始文本：参考文献：【文献1】[来源: 《急性缺血性脑卒中诊治指南2024》 p.12]

渲染后：  参考文献：【文献1】[来源: 《急性缺血性脑卒中诊治指南2024》 p.12]
                                    ↑ 蓝色可点击
                                    点击后弹出：[在线预览] [下载] [取消]
```

#### 4.3 注意事项

- **按需请求**：不要在 AI 回答渲染时立即为所有文献批量请求签名 URL。应在用户点击时才请求，避免浪费签名 URL 配额。
- **缓存机制**：同一会话中，已请求过的文献名→签名 URL 映射可缓存在前端内存中（Map 结构），30 分钟内复用，避免重复请求。
- **匹配容错**：模糊匹配时需考虑文献名可能带年份、不带年份、简称等情况。后端 matchByName 应做 contains 匹配而非完全相等。

---

## 五、接口汇总

| 方法 | 路径 | 用途 | 请求参数 | 响应 |
|------|------|------|---------|------|
| GET | `/api/documents` | 获取文档列表 | 无 | `{ "指南": [{id, name, size}], "教材": [...] }` |
| GET | `/api/documents/{id}/url` | 获取签名 URL | `id`（路径参数） | `{ previewUrl, downloadUrl }` |
| GET | `/api/documents/match` | 按文献名匹配 | `name`（查询参数） | `{ id, name, previewUrl, downloadUrl }` 或 `404` |

所有接口均需 JWT 认证，未登录返回 `401`。

---

## 六、文件修改清单

### Spring 中间层（新增）

| 文件 | 操作 | 说明 |
|------|------|------|
| `pom.xml` | 修改 | 添加 aliyun-sdk-oss 依赖 |
| `application.yml` | 修改 | 添加 OSS 配置项 |
| `OssConfig.java` | 新建 | OSS Client Bean 配置 |
| `OssDocumentService.java` | 新建 | OSS 操作封装（列表、签名、匹配） |
| `DocumentController.java` | 新建 | 3 个 REST 接口 |
| `DocumentVO.java` | 新建 | 文档信息 VO |
| `DocumentUrlVO.java` | 新建 | 签名 URL 响应 VO |

### Vue 前端（新增 + 修改）

| 文件 | 操作 | 说明 |
|------|------|------|
| `api/documents.js` | 新建 | 文档相关 API 调用封装 |
| `components/PdfPreviewModal.vue` | 新建 | 通用 PDF 预览弹窗（vue-pdf-embed） |
| `views/DoctorLearning.vue` | 修改 | 添加文档列表、分类 Tab、预览/下载按钮 |
| `components/ChatMessage.vue`（或类似） | 修改 | 添加文献名解析逻辑和点击交互 |
| `utils/referenceParser.js` | 新建 | 正则解析 AI 回复中的文献名工具函数 |

### 服务器（一次性操作）

| 操作 | 说明 |
|------|------|
| 安装 ossutil 并上传 PDF | 见第一步 |
| 原文件保留不动 | RAG 系统继续使用 |

---

## 七、给 Claude Code 的 Prompt（直接复制使用）

以下 prompt 分三段，建议按顺序在 Claude Code 中执行：

### Prompt 1：Spring 后端 OSS 接口

```
请帮我在 Spring WebFlux 中间层中添加 Ali OSS 文档访问功能。

项目背景：
- 辅助诊疗网页应用，架构为 FastAPI（AI 推理层）+ Spring WebFlux（中间层）+ Vue 3（前端）
- 已有 Ali OSS Bucket（私有权限），PDF 文件已上传至 documents/ 路径下，按子文件夹分类
- 需要通过 Spring 层暴露接口，供前端获取文档列表和签名 URL
- 所有接口需要 JWT 认证

请你：
1. 在 pom.xml 中添加 aliyun-sdk-oss 依赖
2. 在 application.yml 中添加 OSS 配置项（endpoint、accessKeyId、accessKeySecret、bucketName、documentPrefix、signUrlExpiration），敏感信息用环境变量占位
3. 创建 OssConfig.java 配置类，初始化 OSS Client Bean
4. 创建 OssDocumentService.java，实现三个方法：
   - listDocuments()：列出 documents/ 下所有 PDF，按第一级子目录分组为分类
   - generateSignedUrl(documentId)：根据文档 ID 生成预览 URL 和下载 URL（下载 URL 带 response-content-disposition=attachment）
   - matchByName(referenceName)：按文献名模糊匹配（去掉书名号和扩展名后做 contains 匹配）
5. 创建 DocumentController.java，暴露三个接口：
   - GET /api/documents → 返回分类文档列表
   - GET /api/documents/{id}/url → 返回签名 URL
   - GET /api/documents/match?name=xxx → 按文献名匹配并返回签名 URL

请先阅读现有项目结构，了解 JWT 认证的实现方式，确保新接口复用已有的认证机制。
```

### Prompt 2：Vue 前端"医生学习"页面

```
请帮我修改 Vue 3 前端的"医生学习"页面，添加 PDF 文档浏览功能。

前置条件：
- 后端已提供 GET /api/documents（文档列表）和 GET /api/documents/{id}/url（签名 URL）接口
- 需要安装 vue-pdf-embed 和 pdfjs-dist 用于 PDF 预览

请你：
1. 先安装依赖：npm install vue-pdf-embed pdfjs-dist
2. 创建 api/documents.js，封装三个接口调用
3. 创建通用组件 PdfPreviewModal.vue：
   - props：url（PDF 签名 URL）、fileName（显示名称）、visible（显示/隐藏）
   - 功能：翻页、显示当前页码、下载按钮、关闭按钮
   - 样式：全屏模态弹窗，半透明背景遮罩
4. 修改"医生学习"页面：
   - 顶部添加分类 Tab 切换（从接口返回的分类 key 动态生成）
   - 文档列表展示文件名和大小
   - 每个文档提供"在线预览"和"下载"两个按钮
   - "在线预览"打开 PdfPreviewModal
   - "下载"直接 window.open(downloadUrl)

请先阅读现有项目中"医生学习"页面的代码和路由结构，在此基础上添加功能。
```

### Prompt 3：AI 对话文献引用可点击

```
请帮我修改 AI 对话页面，让回答中的参考文献变为可点击链接。

背景：
- AI 回复的纯文本中包含书名号格式的文献名，例如：【文献1】[来源: 《急性缺血性脑卒中诊治指南2024》 p.12]
- 这些文献名与 OSS 上的 PDF 文件名一致
- 后端已提供 GET /api/documents/match?name=xxx 接口，可按文献名模糊匹配并返回签名 URL
- PdfPreviewModal.vue 组件已存在，可直接复用

请你：
1. 创建 utils/referenceParser.js 工具函数：
   - 输入：AI 回复的原始文本
   - 用正则 /《([^》]+)》/g 提取所有书名号内的文献名
   - 输出：解析后的结构化数据，标记哪些部分是普通文本、哪些是文献引用
2. 修改聊天消息渲染组件：
   - 对 AI 回复内容调用 referenceParser 解析
   - 文献名部分渲染为蓝色可点击文本
   - 点击后调用 /api/documents/match 获取签名 URL
   - 获取成功后弹出选项：[在线预览] [下载]
   - 在线预览打开 PdfPreviewModal，下载直接 window.open
   - 匹配失败则提示"未找到对应文档"
3. 添加缓存：同一会话中已匹配过的文献名→URL 映射缓存在 Map 中，30 分钟内复用

请先阅读现有的聊天消息渲染组件代码，了解当前 AI 回复是如何渲染的（Markdown 渲染 / 纯文本 / 自定义组件），然后在现有渲染流程中插入文献解析逻辑。
```

---

## 八、注意事项

1. **OSS CORS 配置**：在 OSS 控制台中为你的 Bucket 添加跨域规则，允许前端域名访问，否则 PDF.js 无法加载文件
2. **AccessKey 安全**：永远不要将 AccessKey 硬编码在代码中或提交到 Git，使用环境变量注入
3. **签名 URL 有效期**：建议 30 分钟，过长有安全风险，过短影响用户体验（阅读长文档时 URL 可能过期）
4. **PDF.js Worker**：vue-pdf-embed 需要配置 pdfjs worker 文件路径，否则可能报错，注意在 vite.config.js 中处理
5. **后续可选优化**：文档列表可以写入数据库并加入搜索功能；可以给 PDF 添加缩略图预览；可以记录医生的阅读进度
