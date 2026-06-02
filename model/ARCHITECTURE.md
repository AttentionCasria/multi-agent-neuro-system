# 临床推理系统架构详解

## 📋 目录
- [系统概述](#系统概述)
- [核心架构](#核心架构)
- [节点详解](#节点详解)
- [数据流转](#数据流转)
- [硬编码分析](#硬编码分析)
- [优化建议](#优化建议)

---

## 系统概述

### 设计理念
本系统采用**多层架构**设计，模拟真实医院的会诊流程：
- **前层**：信息收集与预处理（意图识别、病例分析、证据检索）
- **中层**：多专家协作推理（全科、专科、药师）
- **后层**：质量控制与安全审查（规则引擎、LLM反思）

### 核心特色
1. **证据驱动**：所有建议基于权威医学文献，降低幻觉风险
2. **多专家协作**：三位专家并行推理，避免单一视角偏差
3. **双层校验**：规则引擎+LLM反思，确保医疗建议安全性
4. **反思循环**：支持基于反馈的重新推理，最多3次机会
5. **人工干预**：报告生成前支持人工审批，增强可控性

---

## 核心架构

### 系统流程图

```
用户输入
    ↓
[意图识别] ←───┐
    ↓          │
[路由决策]     │
    ↓          │
┌───┴──────────┴────┐
│                  │
↓                  ↓
[临床问诊]      [知识问答]
↓                  ↓
[病例分析]        直接回答
↓
[证据检索]
↓
[多专家推理] ←───┐
↓                │
[结果校验] ──────┘ (反思循环，最多3次)
↓
[报告生成]
↓
输出结果
```

### 技术栈
- **框架**：LangGraph（状态图编排）
- **模型**：Qwen系列（Max/Plus/Turbo）
- **检索**：ChromaDB + BM25混合检索
- **存储**：MemorySaver（状态持久化）
- **接口**：FastAPI + SSE流式输出

---

## 节点详解

### 1. 意图识别节点 (IntentNode)

**文件位置**：`app/agents/orchestrators/nodes/intent_node.py`

**职责**：
- 识别用户输入类型（问诊/知识/无关）
- 为后续处理提供路由决策依据
- 过滤无关输入，提高系统效率

**工作流程**：
1. 接收用户输入文本
2. 通过LLM判断输入类型
3. 返回意图类型用于路由决策

**输入状态**：
- `case_text`: 用户输入的文本内容

**输出状态**：
- `intent_type`: 意图类型（consultation/knowledge/irrelevant）

**路由规则**：
- `consultation` → 进入完整临床推理流程
- `knowledge` → 直接回答知识问题
- `irrelevant` → 拒绝处理

**硬编码问题**：
- ❌ 意图分类prompt硬编码在代码中
- ❌ 分类规则固定，难以扩展

---

### 2. 病例分析节点 (AnalysisNode)

**文件位置**：`app/agents/orchestrators/nodes/analysis_node.py`

**职责**：
- 结构化病例信息
- 生成临床子问题用于检索
- 识别关键风险和复杂度

**工作流程**：
1. 分析病例文本，提取结构化信息
2. 根据病例类型生成针对性的子问题
3. 评估病例复杂度和关键风险

**输入状态**：
- `case_text`: 患者病例文本
- `all_info`: 历史上下文信息

**输出状态**：
- `context`: 结构化的病例信息
- `clinical_questions`: 临床子问题列表
- `key_risks`: 关键风险列表
- `complexity`: 病例复杂度（low/medium/high/critical）

**特色功能**：
- 智能问题生成：根据病例类型（诊断/治疗/预后）生成针对性问题
- 关键词过滤：避免生成与当前方向冲突的问题

**硬编码问题**：
- ❌ 诊断关键词硬编码：`_DIAGNOSTIC_KW`、`_TREATMENT_KW`等
- ❌ 问题数量限制硬编码：`MAX_SUB_QUESTIONS = 3`

---

### 3. 证据检索节点 (RetrieveNode)

**文件位置**：`app/agents/orchestrators/nodes/retrieve_node.py`

**职责**：
- 基于临床子问题检索医学文献
- 返回相关证据用于后续推理

**工作流程**：
1. 接收临床子问题列表
2. 调用医学助理进行并行检索
3. 返回检索到的证据文本

**输入状态**：
- `clinical_questions`: 临床子问题列表

**输出状态**：
- `evidence`: 检索到的医学证据

**检索策略**：
- 混合检索：向量检索 + BM25关键词检索
- 并行检索：多个子问题同时检索，提高效率
- 证据压缩：限制返回字符数，避免上下文过长

**硬编码问题**：
- ❌ 证据字符数限制硬编码：`MAX_EVIDENCE_CHARS = 2000`

---

### 4. 多专家推理节点 (ReasonNode) ⭐核心节点

**文件位置**：`app/agents/orchestrators/nodes/reason_node.py`

**职责**：
- 协调多专家并行推理
- 综合多专家意见生成最终提案
- 识别潜在风险并提供批判性意见

**工作流程**：
1. 构建完整的病例上下文信息（包含历史反馈）
2. 并行调用三位专家进行推理
3. 综合专家意见生成最终提案和批判
4. 返回结构化结果

**三位专家角色**：

| 专家角色 | 专业领域 | 核心职责 |
|---------|---------|---------|
| **全科医生** | 基础医学 | 初步分诊、病情稳定性评估、基础维生建议 |
| **神经专科医生** | 神经内科 | 定性定位诊断、急诊专科处置（介入/溶栓） |
| **临床药师** | 药物治疗 | 用药禁忌症审查、药物相互作用、剂量范围 |

**输入状态**：
- `case_text`: 患者病例文本
- `all_info`: 历史上下文信息
- `evidence`: 检索到的医学证据
- `validation_feedback`: 之前的校验反馈（用于反思）

**输出状态**：
- `generalist_advice`: 全科医生建议
- `specialist_advice`: 神经专科医生建议
- `pharmacist_advice`: 临床药师建议
- `proposal`: 综合治疗提案
- `critique`: 风险批判意见

**设计模式**：
- **并行执行模式**：三位专家同时推理，提高效率
- **意见综合模式**：通过LLM统筹多专家意见，避免简单拼接
- **反思机制**：支持基于校验反馈的重新推理

**硬编码问题**：
- ❌ 专家角色硬编码：全科、专科、药师固定
- ❌ 专家数量固定：无法动态增减专家
- ❌ 专家职责写死：难以调整专家的专业领域

---

### 5. 结果校验节点 (ValidateNode)

**文件位置**：`app/agents/orchestrators/nodes/validate_node.py`

**职责**：
- 静态规则引擎检查：硬编码禁忌症规则匹配
- 动态LLM反思：深层次的医学逻辑审查
- 决定推理结果是否通过或需要重新推理

**工作流程**：
1. 静态规则引擎检查禁忌症
2. 如果规则检查通过，进行LLM动态反思
3. 根据校验结果决定是否通过或需要重新推理

**双层校验机制**：

**第一层：静态规则引擎**
- 快速匹配硬编码的禁忌症规则
- 结构：`{治疗方式: [禁忌症列表]}`
- 优点：快速、准确、可解释
- 缺点：覆盖范围有限，难以应对复杂情况

**第二层：动态LLM反思**
- 通过LLM进行深层次的医学逻辑审查
- 识别规则引擎无法覆盖的复杂情况
- 优点：灵活、智能、覆盖面广
- 缺点：可能存在幻觉，需要规则引擎兜底

**输入状态**：
- `case_text`: 患者病例文本
- `proposal`: 综合治疗提案
- `evidence`: 检索到的医学证据
- `reflection_count`: 当前反思次数

**输出状态**：
- `validation_passed`: 是否通过校验
- `validation_feedback`: 校验反馈信息
- `reflection_count`: 更新后的反思次数

**校验策略**：
- 静态规则：快速匹配硬编码禁忌症
- 动态反思：LLM深层次医学逻辑审查
- 反思循环：最多3次反思机会
- 安全兜底：异常情况下默认放行，避免阻塞

**硬编码问题**：
- ❌ 禁忌症规则硬编码：`contraindication_rules`字典
- ❌ 反思次数硬编码：最多3次
- ❌ 校验逻辑固定：难以调整校验策略

---

### 6. 报告生成节点 (ReportNode)

**文件位置**：`app/agents/orchestrators/nodes/report_node.py`

**职责**：
- 基于推理结果生成最终临床报告
- 支持多种报告模式（急诊、门诊等）
- 流式输出，提升用户体验

**工作流程**：
1. 检查是否有用户明确问题
2. 根据报告模式选择模板
3. 填充模板内容并生成报告
4. 流式输出报告内容

**输入状态**：
- `context`: 结构化的病例信息
- `all_info`: 历史上下文信息
- `evidence`: 检索到的医学证据
- `proposal`: 综合治疗提案
- `critique`: 风险批判意见
- `user_questions`: 用户明确的问题列表
- `report_mode`: 报告模式

**输出状态**：
- `report`: 最终生成的临床报告

**报告模式**：
- `emergency`: 急诊模式（快速、简洁）
- `outpatient`: 门诊模式（详细、全面）
- `followup`: 随访模式（关注康复和预防）

**硬编码问题**：
- ❌ 提案字符数限制硬编码：`MAX_PROPOSAL_CHARS = 3000`
- ❌ 批判字符数限制硬编码：`MAX_CRITIQUE_CHARS = 3000`

---

## 数据流转

### ClinicalState 数据结构

**文件位置**：`app/agents/core/schema.py`

```python
class ClinicalState(BaseModel):
    # 基础信息
    case_text: str = ""              # 患者病例文本
    all_info: str = ""               # 历史上下文信息
    report_mode: str = "emergency"   # 报告模式
    
    # 意图识别
    intent_type: str = ""            # 意图类型
    
    # 病例分析
    context: Dict = Field(default_factory=dict)           # 结构化病例信息
    clinical_questions: List[str] = Field(default_factory=list)  # 临床子问题
    key_risks: List[str] = Field(default_factory=list)    # 关键风险
    complexity: str = "high"        # 病例复杂度
    
    # 证据检索
    evidence: str = ""               # 检索到的医学证据
    
    # 多专家推理
    generalist_advice: str = ""      # 全科医生建议
    specialist_advice: str = ""      # 专科医生建议
    pharmacist_advice: str = ""      # 药师建议
    proposal: str = ""               # 综合治疗提案
    critique: str = ""               # 风险批判意见
    
    # 结果校验
    validation_passed: bool = True   # 是否通过校验
    validation_feedback: str = ""    # 校验反馈
    reflection_count: int = 0        # 反思次数
    
    # 用户问题
    user_questions: List[str] = Field(default_factory=list)  # 用户明确问题
    
    # 最终输出
    report: str = ""                 # 最终报告
```

### 数据流转图

```
用户输入
    ↓
case_text: "患者男，65岁，突发左侧肢体无力3小时..."
    ↓
[意图识别]
    ↓
intent_type: "consultation"
    ↓
[病例分析]
    ↓
context: {基本信息, 起病方式, 主要症状, ...}
clinical_questions: ["急性缺血性卒中溶栓时间窗", "溶栓禁忌症"]
key_risks: ["大血管闭塞", "出血转化风险"]
complexity: "critical"
    ↓
[证据检索]
    ↓
evidence: "根据《中国急性缺血性卒中诊治指南2023》..."
    ↓
[多专家推理]
    ↓
generalist_advice: "患者病情危重，建议立即转诊..."
specialist_advice: "考虑大血管闭塞，建议血管内治疗..."
pharmacist_advice: "无明确用药禁忌，可考虑抗血小板..."
proposal: "综合建议：立即评估血管内治疗指征..."
critique: "需注意出血转化风险，建议密切监测..."
    ↓
[结果校验]
    ↓
validation_passed: True
validation_feedback: ""
reflection_count: 0
    ↓
[报告生成]
    ↓
report: "【急诊评估】患者男，65岁，突发左侧肢体无力3小时..."
```

---

## 硬编码分析

### 🔴 严重硬编码（必须优化）

| 位置 | 硬编码内容 | 影响 | 优先级 |
|-----|----------|------|-------|
| `intent_node.py:18-32` | 意图分类prompt | 难以调整分类规则 | 高 |
| `reason_node.py:27-29` | 专家角色和职责 | 无法动态配置专家 | 高 |
| `validate_node.py:15-19` | 禁忌症规则 | 难以扩展规则库 | 高 |
| `clinical_graph.py:139` | 反思次数限制（3次） | 无法调整反思策略 | 中 |
| `analysis_node.py:23-24` | 诊断关键词列表 | 难以扩展关键词 | 中 |
| `clinical_graph.py:110` | 拒绝消息文本 | 无法自定义回复 | 低 |

### 🟡 中等程度硬编码（建议优化）

| 位置 | 硬编码内容 | 影响 | 优先级 |
|-----|----------|------|-------|
| `constants.py` | 各种字符数限制 | 影响输出长度控制 | 中 |
| `main.py:68-70` | LLM模型配置 | 难以切换模型 | 中 |
| `clinical_graph.py:99` | 中断点配置 | 无法调整人工干预点 | 低 |

### 🟢 良好设计（无需优化）

- ✅ Prompt模板：大部分在`prompts.yaml`中，支持热更新
- ✅ 报告模板：在`report_templates.yaml`中，可配置
- ✅ Schema定义：数据结构清晰，易于扩展

---

## 优化建议

### 1. 配置化改造

**目标**：将硬编码内容移至配置文件

**实施方案**：
```yaml
# config/expert_config.yaml
experts:
  - role: "全科医生"
    instruction: "请综合患者各项基础概况与生命体征..."
    system_prompt: "你是专业的全科医生"
  
  - role: "神经专科医生"
    instruction: "请深挖神经系统查体与发病经过..."
    system_prompt: "你是专业的神经专科医生"
  
  - role: "临床药师"
    instruction: "请审查患者用药史并发症情况..."
    system_prompt: "你是专业的临床药师"

# config/validation_config.yaml
contraindication_rules:
  溶栓:
    - "近期大手术"
    - "活动性出血"
    - "血小板<100"
    - "血压超180/110"
    - "头颅CT高密度"
  
  抗凝:
    - "出血倾向"
    - "活动性溃疡"
  
  双抗:
    - "既往脑出血史"

validation_settings:
  max_reflection_count: 3
  enable_rule_engine: true
  enable_llm_reflection: true

# config/intent_config.yaml
intent_classification:
  prompt_template: "你是意图分类专家..."
  categories:
    - name: "consultation"
      description: "具体患者问诊或病例分析"
    - name: "knowledge"
      description: "脑卒中通用知识询问"
    - name: "irrelevant"
      description: "非脑卒中医疗相关"
```

### 2. 动态专家配置

**目标**：支持动态添加/删除专家

**实施方案**：
```python
# 优化后的ReasonNode
class ReasonNode(BaseNode):
    def __init__(self, llm, expert_config=None):
        self.llm = llm
        self.expert_config = expert_config or self._load_default_config()
    
    def _load_default_config(self):
        """从配置文件加载专家配置"""
        config_path = "config/expert_config.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    async def run(self, state: ClinicalState) -> Dict:
        # 动态创建专家任务
        tasks = [
            self._ask_expert(
                expert['role'],
                expert['instruction'],
                case_info
            )
            for expert in self.expert_config['experts']
        ]
        
        results = await asyncio.gather(*tasks)
        
        # 动态综合意见
        return await self._synthesize_expert_opinions(results)
```

### 3. 规则引擎优化

**目标**：支持动态规则管理和复杂规则

**实施方案**：
```python
# 优化后的ValidateNode
class ValidateNode(BaseNode):
    def __init__(self, llm, rule_config=None):
        self.llm = llm
        self.rule_engine = RuleEngine(rule_config)
    
    async def run(self, state: ClinicalState) -> Dict:
        # 使用规则引擎进行检查
        rule_violations = self.rule_engine.check(state)
        
        if rule_violations:
            return self._fail_state(state, rule_violations)
        
        # LLM反思
        return await self._llm_reflection(state)

# 新增规则引擎
class RuleEngine:
    def __init__(self, config):
        self.rules = self._load_rules(config)
    
    def check(self, state):
        """执行所有规则检查"""
        violations = []
        for rule in self.rules:
            if rule.match(state):
                violations.append(rule.get_violation_message())
        return violations
```

### 4. 参数化配置

**目标**：将硬编码的参数移至配置文件

**实施方案**：
```yaml
# config/limits_config.yaml
limits:
  max_sub_questions: 3
  max_evidence_chars: 2000
  max_evidence_per_question: 600
  max_proposal_chars: 3000
  max_critique_chars: 3000

# config/keywords_config.yaml
diagnostic_keywords:
  - "TOAST"
  - "分型"
  - "病因"
  - "定位"
  - "定性"
  - "鉴别"
  - "卒中类型"
  - "发病机制"
  - "卒中原因"

treatment_keywords:
  - "溶栓"
  - "取栓"
  - "抗凝"
  - "降压"
  - "手术"
  - "时间窗"
  - "剂量"
  - "适应证"
  - "禁忌"
```

---

## 总结

### 系统优势
1. ✅ **架构清晰**：多层架构设计，职责分明
2. ✅ **安全可靠**：双层校验机制，确保医疗建议安全性
3. ✅ **可解释性强**：每个节点都有明确的输入输出
4. ✅ **扩展性好**：基于LangGraph，易于添加新节点

### 主要问题
1. ❌ **硬编码过多**：专家角色、规则、参数等硬编码在代码中
2. ❌ **配置分散**：部分配置在YAML中，部分在代码中
3. ❌ **灵活性不足**：难以动态调整专家、规则等

### 优化方向
1. 🔧 **配置化改造**：将硬编码内容移至配置文件
2. 🔧 **动态专家配置**：支持动态添加/删除专家
3. 🔧 **规则引擎优化**：支持动态规则管理和复杂规则
4. 🔧 **参数化配置**：将硬编码参数移至配置文件

通过以上优化，可以显著提升系统的灵活性和可维护性，使其更容易适应不同的医疗场景和需求。