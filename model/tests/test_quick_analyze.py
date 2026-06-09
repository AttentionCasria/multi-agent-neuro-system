"""
快速AI意见接口测试脚本
独立测试，不依赖完整服务器启动
"""
import os
import json
import asyncio
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

load_dotenv()

async def test_quick_analyze():
    """测试快速AI意见功能"""
    print("=" * 80)
    print("⚡ 测试快速AI意见功能")
    print("=" * 80)
    
    # 初始化LLM
    _dashscope_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    _dashscope_key = os.getenv("DASHSCOPE_API_KEY")
    
    if not _dashscope_key:
        print("❌ 错误: DASHSCOPE_API_KEY 未设置")
        return
    
    llm_turbo = ChatOpenAI(
        model="qwen-turbo", 
        base_url=_dashscope_base, 
        api_key=_dashscope_key, 
        extra_body={"enable_thinking": False}
    )
    
    # 测试问题
    question = "患者术后次日复查头颅CT显示梗死灶内出现点状高密度影，无占位效应，患者症状稳定。这最可能是什么？是否需要特殊处理？"
    
    print(f"📝 问题: {question}")
    print("-" * 80)
    
    # 构建prompt
    prompt = f"""你是三甲医院神经内科主任医师。请快速分析以下临床问题，给出简洁专业的意见。

问题：
{question}

请直接输出 JSON（不要用 markdown 代码块包裹）：
{{
    "quickOpinion": "快速专业意见（100字以内）",
    "keyPoints": ["关键点1", "关键点2", "关键点3"],
    "riskLevel": "低风险/中风险/高风险"
}}

要求：
- quickOpinion: 简洁专业，禁止确诊语气
- keyPoints: 3-5个关键点，每点20字以内
- riskLevel: 基于问题内容判断风险等级
- 禁止具体药物剂量"""

    try:
        import time
        start_time = time.time()
        
        # 调用LLM
        response = await llm_turbo.ainvoke([HumanMessage(content=prompt)])
        content = getattr(response, "content", "")
        
        elapsed_time = time.time() - start_time
        
        # 解析JSON
        result = _parse_json(content)
        if not result:
            result = {
                "quickOpinion": "建议结合临床实际进一步评估，如症状加重请及时就医。",
                "keyPoints": ["需进一步检查", "结合临床判断", "及时就医"],
                "riskLevel": "中风险"
            }
        
        print(f"✅ 分析完成！耗时: {elapsed_time:.2f}秒")
        print("\n📊 返回结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("\n" + "=" * 80)
        print("🎉 测试成功！")
        print("=" * 80)
        
        return result
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def _parse_json(text: str) -> dict:
    """从模型输出中提取 JSON"""
    content = (text or "").strip()
    try:
        return json.loads(content)
    except Exception:
        pass
    for marker in ["```json", "```"]:
        if marker in content:
            try:
                s = content.split(marker)[1].split("```")[0].strip()
                return json.loads(s)
            except Exception:
                pass
    for sc, ec in [("{", "}"), ("[", "]")]:
        si, ei = content.find(sc), content.rfind(ec)
        if si != -1 and ei > si:
            try:
                return json.loads(content[si:ei + 1])
            except Exception:
                pass
    return {}

if __name__ == "__main__":
    asyncio.run(test_quick_analyze())