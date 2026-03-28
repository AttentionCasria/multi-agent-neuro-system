① Step1：问题拆解（Analysis层）❌ 根本问题源头

你现在自动生成的问题是：

"questions": [
"醒后卒中患者能否溶栓？",
"是否符合血管内治疗适应证？",
"是否存在M1闭塞？"
]

👉 问题：

用户原问题：

卒中类型 + TOAST分型

你生成的问题：

溶栓 / 取栓 / 血管闭塞

⚠️ 这是任务漂移（task drift）

本质错误：

👉 你把任务从：

🧠 “诊断推理任务”

变成了：

⚡ “治疗决策任务”




三、为什么会“有时候对，有时候错”？

这是关键 insight：

👉 你现在是“非约束式问题生成”

也就是：

LLM自由生成问题 → 决定整个后续路径
导致结果：
情况    结果
LLM刚好生成“病因问题”    ✅ 正确
LLM生成“治疗问题”    ❌ 跑偏

👉 本质：系统不稳定（non-deterministic reasoning path）

四、真正的系统级Bug（不是prompt问题）

你现在的架构：

User Question
↓
LLM 生成子问题（❌无约束）
↓
Retriever
↓
LLM 推理

👉 缺了一个关键模块：

❗ Task Router / Intent Constraint（任务约束器）
五、怎么改（给你工程级方案）
✅ 方案1：加“任务锁定器”（强烈推荐）

在 Step1 后加一层：

🔒 Task Constraint Layer
if user_question 包含:
"TOAST" / "病因分型" / "卒中类型"

→ 强制问题模板：

questions = [
"该患者卒中定位与定性是什么？",
"符合TOAST哪一型？",
"支持与反对证据是什么？"
]

👉 直接禁止生成溶栓问题

✅ 方案2：双轨推理（医疗推荐架构）

把任务拆成两个Agent：

① Diagnostic Agent（你这个case需要的）
只做：
定位
定性
病因（TOAST）
② Treatment Agent（你现在误触发的）
溶栓
取栓
时间窗

👉 关键：

先诊断 → 再治疗
而不是混在一起
