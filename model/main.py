
import logging
import sys
import asyncio
import concurrent.futures
from contextlib import asynccontextmanager
import os
import json
import uuid
import jwt

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
import uvicorn

from Agent.qwen.qwen_agent import qwenAgent
from Agent.bailian.health_risk_analyzer import HealthRiskAnalyzer
from services.pubmed_service import PubMedService
from Agent.qwen.qwen_assistant import MedicalAssistant
from utils.naming_model import NamingModel
from makeData.retrieve import UnifiedSearchEngine, CONFIG
from config.config_loader import get_prompt_manager, get_report_manager
from vision_service import VisionAnalysisService

from langchain_openai import ChatOpenAI
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
    show_thinking: bool = True
    images: list[str] = []


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

    _dashscope_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    _dashscope_key  = os.getenv("DASHSCOPE_API_KEY")
    _no_thinking = {"extra_body": {"enable_thinking": False}}
    llm_max   = ChatOpenAI(model="qwen-max",   base_url=_dashscope_base, api_key=_dashscope_key, model_kwargs=_no_thinking)
    llm_plus  = ChatOpenAI(model="qwen-plus",  base_url=_dashscope_base, api_key=_dashscope_key, model_kwargs=_no_thinking)
    llm_turbo = ChatOpenAI(model="qwen-turbo", base_url=_dashscope_base, api_key=_dashscope_key, model_kwargs=_no_thinking)
    context_summary = ConversationSummaryService(
        llm=llm_turbo,
        prompt_manager=prompt_mgr
    )

    retriever = UnifiedSearchEngine(
        persist_dir=CONFIG.get("persist_dir", "./chroma_db_unified"),
        top_k=CONFIG.get("top_k_final", 3)
    )

    if retriever.chunks:
        _loaded_doc_names = sorted(set(
            chunk.metadata["source"].removesuffix(".pdf").removesuffix(".PDF")
            for chunk in retriever.chunks
            if chunk.metadata.get("source")
        ))
        report_mgr.update_doc_list(_loaded_doc_names)
    else:
        logging.warning("[文献列表] 本地文档为空，system_role 使用 YAML 静态列表")

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
        report_manager=report_mgr,
        llm_turbo=llm_turbo,
    )

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
        req_id = uuid.uuid4().hex[:12]
        try:
            logging.info(f"[{req_id}] === 开始处理请求 ===")
            logging.info(f"[{req_id}] 问题: {request.question[:100]}")
            logging.info(f"[{req_id}] report_mode: {request.report_mode}, images: {len(request.images)}")

            loop = asyncio.get_running_loop()
            final_answer_parts = []

            if request.images:
                vision_svc = resources.get("vision_service")
                if not vision_svc:
                    yield json.dumps({"type": "token", "content": "影像识别服务未就绪，请稍后重试。"}, ensure_ascii=False)
                else:
                    async for event in vision_svc.analyze_stream(
                        images=request.images,
                        question=request.question,
                        all_info=request.all_info,
                    ):
                        if event.get("type") == "thinking":
                            yield json.dumps({
                                "type": "node_start",
                                "node": "vision",
                                "label": event.get("title", "正在分析影像..."),
                            }, ensure_ascii=False)
                        elif event.get("type") == "chunk":
                            content_str = str(event.get("content", ""))
                            if content_str:
                                final_answer_parts.append(content_str)
                                yield json.dumps({"type": "token", "content": content_str}, ensure_ascii=False)

                answer_text = "".join(final_answer_parts).strip()
                yield json.dumps({
                    "type": "done",
                    "request_id": req_id,
                    "name": "影像分析",
                    "all_info": request.all_info,
                }, ensure_ascii=False)
                return

            naming_future = None
            if not request.all_info and resources.get("naming_model"):
                naming_future = loop.run_in_executor(
                    resources["executor"],
                    resources["naming_model"].run_naming,
                    request.question,
                )

            async for event in resources["model"].run_clinical_reasoning(
                case_text=request.question,
                all_info=request.all_info,
                report_mode=request.report_mode,
                show_thinking=request.show_thinking,
            ):
                if not isinstance(event, dict):
                    continue

                if event.get("type") == "error":
                    yield json.dumps(event, ensure_ascii=False)
                    return

                if event.get("type") == "token":
                    content_str = str(event.get("content", ""))
                    if content_str:
                        final_answer_parts.append(content_str)

                yield json.dumps(event, ensure_ascii=False)

            generated_name = "咨询"
            if naming_future:
                try:
                    generated_name = await naming_future or "咨询"
                except Exception:
                    pass

            answer_text    = "".join(final_answer_parts).strip()
            updated_all_info = request.all_info

            if answer_text and resources.get("context_summary"):
                try:
                    summary_result = await loop.run_in_executor(
                        resources["executor"],
                        resources["context_summary"].update_all_info,
                        request.all_info,
                        request.question,
                        answer_text,
                        0.4,
                    )
                    updated_all_info = summary_result.get("updated_all_info", request.all_info)
                except Exception as summary_error:
                    logging.error(f"[{req_id}] all_info 更新失败: {summary_error}")

            yield json.dumps({
                "type":       "done",
                "request_id": req_id,
                "name":       generated_name,
                "all_info":   updated_all_info,
            }, ensure_ascii=False)
            logging.info(f"[{req_id}] === 请求处理完成 ===")

        except Exception as e:
            logging.error(f"[{req_id}] generate() 外层异常 | {format_error_log(e)}")
            yield json.dumps(build_error_event(e, talk_id=None), ensure_ascii=False)

    return EventSourceResponse(generate(), ping=15)


@app.post("/ai/analyze", response_model=AnalyzeResponse)
async def analyze_patient_health_risk(request: AnalyzeRequest):
    verify_token(request.token)

    patient_text = request.data.strip()
    if not patient_text:
        raise HTTPException(status_code=422, detail="data cannot be empty")

    logging.info("=== 开始健康风险分析请求（HealthRiskAnalyzer）===")
    logging.info(f"patientId: {request.patientId}")
    logging.info(f"data: {patient_text[:200]}")

    # 独立的分析模块，不依赖主推理链
    result = await HealthRiskAnalyzer().analyze(patient_text)

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