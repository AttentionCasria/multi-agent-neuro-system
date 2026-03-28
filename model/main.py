# main.py

import logging
import sys
import asyncio
import concurrent.futures
from contextlib import asynccontextmanager
import os
import json
import jwt

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from Agent.qwen.qwen_agent import qwenAgent
from services.pubmed_service import PubMedService
from Agent.qwen.qwen_assistant import MedicalAssistant
from utils.naming_model import NamingModel
from makeData.Retrieve import UnifiedSearchEngine, CONFIG
from config.config_loader import get_prompt_manager, get_report_manager
from vision_service import VisionAnalysisService

from langchain_community.chat_models import ChatTongyi
from utils.context_summary import ConversationSummaryService
from error_codes import build_error_event, format_error_log


os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

resources = {"model": None, "naming_model": None, "executor": None, "context_summary": None, "vision_service": None}


class QueryRequest(BaseModel):
    question: str
    round: int = 2
    all_info: str = ""
    token: str
    report_mode: str = "emergency"
    show_thinking: bool = True  # 是否输出中间思考过程
    images: list[str] = []  # Base64 图片列表（新增：影像识别功能），最多 3 张


class AnalyzeRequest(BaseModel):
    patientId: int
    data: str = Field(..., min_length=1)
    all_info: str = ""
    token: str


class AnalyzeResult(BaseModel):
    riskLevel: str
    suggestion: str
    analysisDetails: str


class AnalyzeResponse(BaseModel):
    code: int
    msg: str
    data: AnalyzeResult


def init_all_resources():
    logging.info(">>> 开始组装模型依赖链...")

    prompt_mgr = get_prompt_manager()
    report_mgr = get_report_manager()
    logging.info(f">>> 可用报告模式: {report_mgr.list_modes()}")

    llm_max = ChatTongyi(model_name="qwen-max", streaming=True)
    llm_plus = ChatTongyi(model_name="qwen-plus", streaming=True)
    context_summary = ConversationSummaryService(
        llm=llm_plus,
        prompt_manager=prompt_mgr
    )

    retriever = UnifiedSearchEngine(
        persist_dir=CONFIG.get("persist_dir", "./chroma_db_unified"),
        top_k=CONFIG.get("top_k_final", 3)
    )

    medical_assistant = MedicalAssistant(
        llm_main=llm_max,
        llm_fast=llm_plus,
        retriever=retriever,
        prompt_manager=prompt_mgr,
        report_manager=report_mgr
    )

    agent = qwenAgent(
        llm_proposer=llm_max,
        llm_critic=llm_plus,
        medical_assistant=medical_assistant,
        prompt_manager=prompt_mgr,
        report_manager=report_mgr
    )

    # 初始化影像分析服务（VL 模型懒加载，首次调用时连接 DashScope）
    vision_service = VisionAnalysisService(prompt_manager=prompt_mgr)

    naming_model = NamingModel()
    return agent, naming_model, context_summary, vision_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info(">>> 正在初始化资源及加载模型...")
    resources["executor"] = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    loop = asyncio.get_running_loop()

    try:
        agent, naming, context_summary, vision_service = await loop.run_in_executor(
            resources["executor"], init_all_resources
        )
        resources["model"] = agent
        resources["naming_model"] = naming
        resources["context_summary"] = context_summary
        resources["vision_service"] = vision_service
        logging.info(">>> 所有模型组装完成，服务已就绪")
    except Exception as e:
        logging.error(f"!!! 模型初始化严重失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        raise

    yield

    logging.info("<<< 正在释放资源...")
    if resources["executor"]:
        resources["executor"].shutdown()


app = FastAPI(lifespan=lifespan)


def verify_token(token: str):
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/model/get_result")
async def get_model_result(request: QueryRequest):
    verify_token(request.token)

    if not resources["model"]:
        raise HTTPException(status_code=503, detail="Model service not ready")

    async def generate():
        try:
            logging.info(f"=== 开始处理请求 ===")
            logging.info(f"请求问题: {request.question}")
            logging.info(f"请求all_info: {request.all_info}")
            logging.info(f"请求report_mode: {request.report_mode}")
            logging.info(f"请求show_thinking: {request.show_thinking}")
            logging.info(f"请求图片数量: {len(request.images)}")

            loop = asyncio.get_running_loop()
            final_answer_parts = []

            # ===== 影像识别分支：有图片时直接走 vision_service，跳过 Agent 推理 =====
            if request.images:
                vision_svc = resources.get("vision_service")
                if not vision_svc:
                    yield json.dumps({"type": "chunk", "content": "影像识别服务未就绪，请稍后重试。"}, ensure_ascii=False) + "\n"
                else:
                    async for event in vision_svc.analyze_stream(
                        images=request.images,
                        question=request.question,
                        all_info=request.all_info,
                    ):
                        if event.get("type") == "thinking":
                            yield json.dumps({
                                "type": "thinking",
                                "step": event.get("step", ""),
                                "title": event.get("title", ""),
                                "content": event.get("content", ""),
                            }, ensure_ascii=False) + "\n"
                        elif event.get("type") == "chunk":
                            content_str = str(event.get("content", ""))
                            if content_str:
                                final_answer_parts.append(content_str)
                                yield json.dumps({"type": "chunk", "content": content_str}, ensure_ascii=False) + "\n"

                answer_text = "".join(final_answer_parts).strip()
                yield json.dumps({
                    "type": "done",
                    "content": "",
                    "result": answer_text,
                    "summary": request.all_info,
                    "name": "影像分析",
                    "all_info": request.all_info,
                }, ensure_ascii=False) + "\n"
                return

            # 并行启动命名任务（首轮对话时生成会话标题，sync 函数放入线程池）
            naming_future = None
            if not request.all_info and resources.get("naming_model"):
                naming_future = loop.run_in_executor(
                    resources["executor"],
                    resources["naming_model"].run_naming,
                    request.question
                )

            generated_name = None

            # 直接迭代异步生成器
            # 心跳用 asyncio.wait({task}, timeout) 而非 wait_for：
            # wait_for 超时会取消 task 并向 generator 注入 CancelledError，导致 generator 损坏；
            # asyncio.wait 超时只是"还没好"，task 继续运行，下次循环复用同一个 task。
            async_gen = resources["model"].run_clinical_reasoning(
                case_text=request.question,
                all_info=request.all_info,
                report_mode=request.report_mode,
                show_thinking=request.show_thinking
            )

            pending_task = None
            while True:
                if pending_task is None:
                    pending_task = asyncio.ensure_future(async_gen.__anext__())

                done, _ = await asyncio.wait({pending_task}, timeout=10.0)

                if not done:
                    # 超时：发心跳，task 继续在后台等 LLM，下次循环复用
                    logging.debug("异步流空闲超时，发送 SSE 心跳事件")
                    yield json.dumps({"type": "heartbeat", "talkId": None}, ensure_ascii=False) + "\n"
                    continue

                # task 已完成，取结果并重置，下次循环创建新 task
                pending_task = None
                try:
                    event = done.pop().result()
                except StopAsyncIteration:
                    break
                except Exception as e:
                    yield json.dumps(build_error_event(e, talk_id=None), ensure_ascii=False) + "\n"
                    return

                if not isinstance(event, dict):
                    continue

                # 顺带检查命名任务是否已完成
                if naming_future and naming_future.done() and not generated_name:
                    try:
                        generated_name = naming_future.result()
                    except Exception:
                        generated_name = "咨询"

                chunk_type = event.get("type", "")

                if chunk_type == "error":
                    # 透传完整结构化错误事件后终止流
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                    return

                elif chunk_type == "chunk":
                    # 打字机效果：逐块转发，同时累计到 final_answer_parts
                    content_str = str(event.get("content", ""))
                    if content_str:
                        final_answer_parts.append(content_str)
                        yield json.dumps({"type": "chunk", "content": content_str}, ensure_ascii=False) + "\n"

                elif chunk_type == "result":
                    content = event["content"]
                    if hasattr(content, "content"):
                        content = content.content
                    content_str = str(content)
                    final_answer_parts.append(content_str)
                    yield json.dumps({"type": "result", "content": content_str}, ensure_ascii=False) + "\n"

                elif chunk_type == "thinking":
                    yield json.dumps({
                        "type": "thinking",
                        "step": event.get("step", ""),
                        "title": event.get("title", ""),
                        "content": str(event.get("content", ""))
                    }, ensure_ascii=False) + "\n"

                elif chunk_type == "meta":
                    yield json.dumps({"type": "meta", "content": event["content"]}, ensure_ascii=False) + "\n"

            # 流正常结束：等待命名任务，然后生成 meta + done
            if not generated_name and naming_future:
                try:
                    generated_name = await naming_future
                except Exception:
                    generated_name = "咨询"
            generated_name = generated_name or "咨询"

            answer_text = "".join(final_answer_parts).strip()
            updated_summary = request.all_info
            summary_meta = {
                "score": 0.0,
                "is_valuable": False,
                "reason": "no final answer",
                "summary": updated_summary,
                "all_info": updated_summary
            }

            if answer_text and resources.get("context_summary"):
                try:
                    summary_result = await loop.run_in_executor(
                        resources["executor"],
                        resources["context_summary"].update_all_info,
                        request.all_info,
                        request.question,
                        answer_text,
                        0.4
                    )
                    updated_summary = summary_result.get("updated_all_info", request.all_info)
                    summary_meta = {
                        "score": summary_result.get("score", 0.0),
                        "is_valuable": summary_result.get("is_valuable", False),
                        "reason": summary_result.get("reason", ""),
                        "summary": updated_summary,
                        "all_info": updated_summary
                    }
                except Exception as summary_error:
                    logging.error(f"all_info 更新失败: {summary_error}")
                    summary_meta["reason"] = f"summary failed: {summary_error}"

            summary_meta["name"] = generated_name

            # 标准格式：meta 事件携带 all_info 更新信息
            yield json.dumps({"type": "meta", "content": {"all_info_update": summary_meta}}, ensure_ascii=False) + "\n"
            # done 事件：标志流结束，携带汇总信息
            yield json.dumps({
                "type": "done",
                "content": "",
                "result": answer_text,
                "summary": updated_summary,
                "name": generated_name,
                "all_info": updated_summary
            }, ensure_ascii=False) + "\n"

        except Exception as e:
            # 记录含完整堆栈的错误日志
            logging.error(f"generate() 外层异常 | {format_error_log(e)}")
            # 构造结构化错误事件并 yield（双写 content 字段保持旧前端兼容）
            yield json.dumps(build_error_event(e, talk_id=None), ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*"
        }
    )


@app.post("/ai/analyze", response_model=AnalyzeResponse)
async def analyze_patient_health_risk(request: AnalyzeRequest):
    verify_token(request.token)

    if not resources["model"]:
        raise HTTPException(status_code=503, detail="Model service not ready")

    patient_text = request.data.strip()
    if not patient_text:
        raise HTTPException(status_code=422, detail="data cannot be empty")

    logging.info("=== 开始健康风险分析请求 ===")
    logging.info(f"patientId: {request.patientId}")
    logging.info(f"data: {patient_text[:200]}")
    logging.info(f"all_info: {request.all_info[:200] if request.all_info else ''}")

    # 修改为调用新的快速专用函数（完全独立，不影响对话路径）
    result = await resources["model"].analyze_patient_risk_fast(patient_text)

    return {
        "code": 1,
        "msg": "success",
        "data": result
    }


class PubMedSearchRequest(BaseModel):
    query: str
    max_results: int = 5


@app.post("/model/pubmed/search")
async def pubmed_search(request: PubMedSearchRequest):
    """
    PubMed 独立检索接口，供「医生学习 - 学习资料」板块调用。
    与 AI 问答管线解耦，直接返回 JSON，不走 SSE 流。
    """
    query = request.query.strip()
    if not query:
        return {"code": 1, "msg": "success", "data": {"papers": []}}

    svc = PubMedService()
    try:
        papers = await svc.search_papers(query, max_results=request.max_results)
    except Exception as e:
        logging.error(f"PubMed 检索失败: {e}")
        papers = []

    return {"code": 1, "msg": "success", "data": {"papers": papers}}


@app.post("/admin/reload_config")
async def reload_config():
    try:
        get_prompt_manager().reload()
        get_report_manager().reload()
        return {"status": "ok", "message": "配置已热更新"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/report_modes")
async def list_report_modes():
    mgr = get_report_manager()
    modes = mgr.list_modes()
    return {
        "modes": [
            {"key": m, "name": mgr.get_template_name(m)}
            for m in modes
        ]
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)