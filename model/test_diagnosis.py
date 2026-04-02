"""
诊断脚本：逐层排查 consultation 卡死根因
运行方式：cd /www/wwwroot/Python-backend && python3 test_diagnosis.py

测试顺序：
  Case 1 — 单次 ainvoke（验证 DashScope 本身是否正常）
  Case 2 — 两次并行 ainvoke，不经过 LangGraph（验证 asyncio.gather 是否正常）
  Case 3 — 直接调用 _parallel_propose_and_critique，不经过 LangGraph（验证三步推理本身）
  Case 4 — 通过 run_clinical_reasoning 完整跑（经过 LangGraph astream_events）
"""
import asyncio
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_KEY  = os.getenv("DASHSCOPE_API_KEY")

CASE_TEXT = "患者男性65岁，突发右侧肢体无力伴言语不清2小时"


def make_llms():
    _no_thinking = {"extra_body": {"enable_thinking": False}}
    llm_max   = ChatOpenAI(model="qwen-max",   base_url=_BASE, api_key=_KEY, model_kwargs=_no_thinking)
    llm_plus  = ChatOpenAI(model="qwen-plus",  base_url=_BASE, api_key=_KEY, model_kwargs=_no_thinking)
    llm_turbo = ChatOpenAI(model="qwen-turbo", base_url=_BASE, api_key=_KEY, model_kwargs=_no_thinking)
    return llm_max, llm_plus, llm_turbo


# ─────────────────────────────────────────────────────────
# Case 1：单次 ainvoke，验证 DashScope 连通性和响应速度
# ─────────────────────────────────────────────────────────
async def case1_single_ainvoke():
    logger.info("=" * 60)
    logger.info("Case 1：单次 ainvoke（qwen-plus，短提示）")
    logger.info("=" * 60)

    llm_max, llm_plus, llm_turbo = make_llms()
    t0 = time.time()
    resp = await llm_plus.ainvoke([HumanMessage(content="用一句话描述脑卒中的定义。")])
    logger.info(f"Case 1 完成，耗时 {time.time()-t0:.1f}s，响应长度 {len(resp.content)}")
    logger.info(f"内容预览：{resp.content[:100]}")
    return True


# ─────────────────────────────────────────────────────────
# Case 2：两次 ainvoke 并行 gather，不经过 LangGraph
# ─────────────────────────────────────────────────────────
async def case2_parallel_gather():
    logger.info("=" * 60)
    logger.info("Case 2：两次并行 ainvoke（qwen-max，不经过 LangGraph）")
    logger.info("=" * 60)

    llm_max, llm_plus, llm_turbo = make_llms()
    prompt1 = f"你是神经内科专家，请分析以下病例：{CASE_TEXT}，给出初步诊断思路（200字内）。"
    prompt2 = f"你是临床质控专家，请针对以下病例识别潜在风险：{CASE_TEXT}（200字内）。"

    t0 = time.time()
    logger.info("开始 gather...")
    resp1, resp2 = await asyncio.gather(
        llm_max.ainvoke([HumanMessage(content=prompt1)]),
        llm_max.ainvoke([HumanMessage(content=prompt2)]),
    )
    logger.info(f"Case 2 完成，耗时 {time.time()-t0:.1f}s")
    logger.info(f"  proposer 长度：{len(resp1.content)}")
    logger.info(f"  critic   长度：{len(resp2.content)}")
    return True


# ─────────────────────────────────────────────────────────
# Case 3：直接调用 _parallel_propose_and_critique，不经过 LangGraph
# ─────────────────────────────────────────────────────────
async def case3_direct_propose_critique():
    logger.info("=" * 60)
    logger.info("Case 3：直接调用 _parallel_propose_and_critique（不经过 LangGraph）")
    logger.info("=" * 60)

    from makeData.retrieve import UnifiedSearchEngine, CONFIG
    from Agent.qwen.qwen_assistant import MedicalAssistant
    from Agent.qwen.qwen_agent import qwenAgent
    from config.config_loader import get_prompt_manager, get_report_manager

    llm_max, llm_plus, llm_turbo = make_llms()
    prompt_mgr = get_prompt_manager()
    report_mgr = get_report_manager()
    retriever  = UnifiedSearchEngine(
        persist_dir=CONFIG.get("persist_dir", "./chroma_db_unified"),
        top_k=CONFIG.get("top_k_final", 3)
    )
    assistant = MedicalAssistant(
        llm_main=llm_max, llm_fast=llm_plus,
        retriever=retriever,
        prompt_manager=prompt_mgr, report_manager=report_mgr,
    )
    agent = qwenAgent(
        llm_proposer=llm_max, llm_critic=llm_plus,
        medical_assistant=assistant,
        prompt_manager=prompt_mgr, report_manager=report_mgr,
        llm_turbo=llm_turbo,
    )

    context = {"原始病例": CASE_TEXT, "主诉": "右侧肢体无力伴言语不清2小时"}
    t0 = time.time()
    logger.info("开始调用 _parallel_propose_and_critique ...")
    proposal, critique = await agent._parallel_propose_and_critique(
        context=context,
        evidence="未检索到相关证据",
        all_info="",
        user_questions=[],
    )
    logger.info(f"Case 3 完成，耗时 {time.time()-t0:.1f}s")
    logger.info(f"  proposal 长度：{len(proposal)}")
    logger.info(f"  critique 长度：{len(critique)}")
    return True


# ─────────────────────────────────────────────────────────
# Case 4：完整走 run_clinical_reasoning（经过 LangGraph astream_events）
# ─────────────────────────────────────────────────────────
async def case4_full_langgraph():
    logger.info("=" * 60)
    logger.info("Case 4：完整 run_clinical_reasoning（经过 LangGraph astream_events）")
    logger.info("=" * 60)

    from makeData.retrieve import UnifiedSearchEngine, CONFIG
    from Agent.qwen.qwen_assistant import MedicalAssistant
    from Agent.qwen.qwen_agent import qwenAgent
    from config.config_loader import get_prompt_manager, get_report_manager

    llm_max, llm_plus, llm_turbo = make_llms()
    prompt_mgr = get_prompt_manager()
    report_mgr = get_report_manager()
    retriever  = UnifiedSearchEngine(
        persist_dir=CONFIG.get("persist_dir", "./chroma_db_unified"),
        top_k=CONFIG.get("top_k_final", 3)
    )
    assistant = MedicalAssistant(
        llm_main=llm_max, llm_fast=llm_plus,
        retriever=retriever,
        prompt_manager=prompt_mgr, report_manager=report_mgr,
    )
    agent = qwenAgent(
        llm_proposer=llm_max, llm_critic=llm_plus,
        medical_assistant=assistant,
        prompt_manager=prompt_mgr, report_manager=report_mgr,
        llm_turbo=llm_turbo,
    )

    t0 = time.time()
    event_count = 0
    async for event in agent.run_clinical_reasoning(
        case_text=CASE_TEXT,
        all_info="",
        report_mode="emergency",
        show_thinking=True,
    ):
        event_count += 1
        logger.info(f"  [event #{event_count}] {event}")

    logger.info(f"Case 4 完成，耗时 {time.time()-t0:.1f}s，共 {event_count} 个事件")
    return True


# ─────────────────────────────────────────────────────────
# 主流程：逐 Case 执行，某个失败/卡死直接可以 Ctrl+C 定位
# ─────────────────────────────────────────────────────────
async def main():
    cases = [
        ("Case 1 - 单次 ainvoke",            case1_single_ainvoke),
        ("Case 2 - 并行 gather（无LangGraph）", case2_parallel_gather),
        ("Case 3 - 直接调 propose+critique",  case3_direct_propose_critique),
        ("Case 4 - 完整 LangGraph 流",        case4_full_langgraph),
    ]

    for name, fn in cases:
        logger.info(f"\n>>> 开始 {name}")
        t0 = time.time()
        try:
            ok = await asyncio.wait_for(fn(), timeout=300)  # 单个 case 最多等 5 分钟
            logger.info(f">>> {name} ✅ 通过，耗时 {time.time()-t0:.1f}s\n")
        except asyncio.TimeoutError:
            logger.error(f">>> {name} ❌ 超时（>5分钟），卡死在这里，后续 case 跳过")
            break
        except Exception as e:
            logger.error(f">>> {name} ❌ 异常：{e}")
            import traceback
            traceback.print_exc()
            break


if __name__ == "__main__":
    asyncio.run(main())
