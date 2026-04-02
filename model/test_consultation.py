"""
临时测试脚本：直接调用 qwenAgent，验证 consultation 路径是否能跑通
运行方式：cd /www/wwwroot/Python-backend && python3 test_consultation.py
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

from langchain_openai import ChatOpenAI
from makeData.retrieve import UnifiedSearchEngine, CONFIG
from Agent.qwen.qwen_assistant import MedicalAssistant
from Agent.qwen.qwen_agent import qwenAgent
from config.config_loader import get_prompt_manager, get_report_manager


async def test():
    _base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    _key  = os.getenv("DASHSCOPE_API_KEY")

    llm_max  = ChatOpenAI(model="qwen-max",  base_url=_base, api_key=_key)
    llm_plus = ChatOpenAI(model="qwen-plus", base_url=_base, api_key=_key)

    prompt_mgr = get_prompt_manager()
    report_mgr = get_report_manager()

    retriever = UnifiedSearchEngine(
        persist_dir=CONFIG.get("persist_dir", "./chroma_db_unified"),
        top_k=CONFIG.get("top_k_final", 3)
    )
    assistant = MedicalAssistant(
        llm_main=llm_max,
        llm_fast=llm_plus,
        retriever=retriever,
        prompt_manager=prompt_mgr,
        report_manager=report_mgr,
    )
    agent = qwenAgent(
        llm_proposer=llm_max,
        llm_critic=llm_plus,
        medical_assistant=assistant,
        prompt_manager=prompt_mgr,
        report_manager=report_mgr,
    )

    print("\n=== 开始测试 consultation ===\n")
    async for event in agent.run_clinical_reasoning(
        case_text="患者男性65岁，突发右侧肢体无力伴言语不清2小时",
        all_info="",
        report_mode="emergency",
        show_thinking=True,
    ):
        print(event)

    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    asyncio.run(test())
