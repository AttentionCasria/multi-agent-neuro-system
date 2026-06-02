import logging
import sys
import asyncio
import concurrent.futures
from contextlib import asynccontextmanager
import os
import json
import uuid
import jwt
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
import uvicorn

from app.agents.assistant import MedicalAssistant
from app.agents.bailian.health_risk_analyzer import HealthRiskAnalyzer
from app.services.pubmed_service import PubMedService
from app.agents.orchestrators.qwen_agent import QwenAgent
from app.utils.error_codes import build_error_event, format_error_log
from app.utils.naming_model import NamingModel
from app.rag.retrieve import UnifiedSearchEngine, CONFIG
from app.config.config_loader import (
    get_prompt_manager, 
    get_report_manager,
    get_expert_manager,
    get_validation_manager,
    get_limits_manager
)
from app.services.vision_service import VisionAnalysisService

from langchain_openai import ChatOpenAI
from app.utils.context_summary import ConversationSummaryService


os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"

# 配置日志系统
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)

# 创建性能统计日志
performance_logger = logging.getLogger("performance")
performance_logger.setLevel(logging.INFO)

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
    """初始化所有资源"""
    start_time = time.time()
    logger.info("=" * 80)
    logger.info("🚀 开始初始化系统资源")
    logger.info("=" * 80)
    
    # 步骤1: 加载配置管理器
    logger.info("📋 [1/7] 加载配置管理器...")
    prompt_mgr = get_prompt_manager()
    report_mgr = get_report_manager()
    expert_mgr = get_expert_manager()
    validation_mgr = get_validation_manager()
    limits_mgr = get_limits_manager()
    
    # 显示配置信息
    logger.info(f"  ✅ Prompt管理器: 已加载 {len(prompt_mgr._prompts)} 个prompt模板")
    logger.info(f"  ✅ 报告管理器: 可用模式 {report_mgr.list_modes()}")
    
    # 显示专家配置
    experts = expert_mgr.get_experts()
    logger.info(f"  ✅ 专家配置: 已加载 {len(experts)} 位专家")
    for expert in experts:
        logger.info(f"     - {expert.get('role')} (优先级: {expert.get('priority')})")
    
    # 显示校验配置
    rules = validation_mgr.get_contraindication_rules()
    logger.info(f"  ✅ 校验配置: {len(rules)} 个治疗方式的禁忌症规则")
    logger.info(f"     - 最大反思次数: {validation_mgr.get_max_reflection_count()}")
    logger.info(f"     - 规则引擎: {'启用' if validation_mgr.is_rule_engine_enabled() else '禁用'}")
    logger.info(f"     - LLM反思: {'启用' if validation_mgr.is_llm_reflection_enabled() else '禁用'}")
    
    # 显示参数限制
    logger.info(f"  ✅ 参数限制:")
    logger.info(f"     - 最大子问题数: {limits_mgr.get_max_sub_questions()}")
    logger.info(f"     - 最大证据字符数: {limits_mgr.get_max_evidence_chars()}")
    logger.info(f"     - 最大提案字符数: {limits_mgr.get_max_proposal_chars()}")
    
    # 步骤2: 初始化LLM模型
    logger.info("🤖 [2/7] 初始化大语言模型...")
    _dashscope_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    _dashscope_key = os.getenv("DASHSCOPE_API_KEY")
    
    if not _dashscope_key:
        logger.error("  ❌ 错误: DASHSCOPE_API_KEY 未设置")
        raise ValueError("DASHSCOPE_API_KEY 环境变量未设置")
    
    logger.info(f"  ✅ API密钥: {_dashscope_key[:10]}...{_dashscope_key[-4:]}")
    
    llm_max = ChatOpenAI(model="qwen-max", base_url=_dashscope_base, api_key=_dashscope_key, extra_body={"enable_thinking": False})
    llm_plus = ChatOpenAI(model="qwen-plus", base_url=_dashscope_base, api_key=_dashscope_key, extra_body={"enable_thinking": False})
    llm_turbo = ChatOpenAI(model="qwen-turbo", base_url=_dashscope_base, api_key=_dashscope_key, extra_body={"enable_thinking": False})
    
    logger.info(f"  ✅ 模型加载完成: qwen-max, qwen-plus, qwen-turbo")
    
    # 步骤3: 初始化上下文摘要服务
    logger.info("💬 [3/7] 初始化上下文摘要服务...")
    context_summary = ConversationSummaryService(
        llm=llm_turbo,
        prompt_manager=prompt_mgr
    )
    logger.info("  ✅ 上下文摘要服务初始化完成")
    
    # 步骤4: 初始化检索引擎
    logger.info("🔍 [4/7] 初始化向量检索引擎...")
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
        logger.info(f"  ✅ 检索引擎初始化完成")
        logger.info(f"     - 向量库路径: {CONFIG.get('persist_dir', './chroma_db_unified')}")
        logger.info(f"     - 文档数量: {len(retriever.chunks)} 个片段")
        logger.info(f"     - 文献数量: {len(_loaded_doc_names)} 篇")
        logger.info(f"     - 检索Top-K: {CONFIG.get('top_k_final', 3)}")
    else:
        logger.warning("  ⚠️  本地文档为空，system_role 使用 YAML 静态列表")
    
    # 步骤5: 初始化医疗助手
    logger.info("👨‍⚕️  [5/7] 初始化医疗助手...")
    medical_assistant = MedicalAssistant(
        llm_main=llm_max,
        llm_fast=llm_plus,
        retriever=retriever,
        prompt_manager=prompt_mgr,
        report_manager=report_mgr
    )
    logger.info("  ✅ 医疗助手初始化完成")
    
    # 步骤6: 初始化智能体
    logger.info("🧠 [6/7] 初始化临床推理智能体...")
    agent = QwenAgent(
        llm_proposer=llm_max,
        llm_critic=llm_plus,
        medical_assistant=medical_assistant,
        prompt_manager=prompt_mgr,
        report_manager=report_mgr,
        llm_turbo=llm_turbo,
    )
    logger.info("  ✅ 临床推理智能体初始化完成")
    
    # 步骤7: 初始化其他服务
    logger.info("🔧 [7/7] 初始化其他服务...")
    vision_service = VisionAnalysisService(prompt_manager=prompt_mgr)
    naming_model = NamingModel()
    logger.info("  ✅ 影像识别服务初始化完成")
    logger.info("  ✅ 命名模型初始化完成")
    
    # 统计初始化时间
    init_time = time.time() - start_time
    logger.info("=" * 80)
    logger.info(f"🎉 系统初始化完成！耗时: {init_time:.2f}秒")
    logger.info("=" * 80)
    
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
    """临床推理接口 - 增强日志版本"""
    verify_token(request.token)

    if not resources["model"]:
        raise HTTPException(status_code=503, detail="Model service not ready")

    async def generate():
        req_id = uuid.uuid4().hex[:12]
        start_time = time.time()
        
        try:
            logger.info("=" * 80)
            logger.info(f"🔵 [请求 {req_id}] 开始处理临床推理请求")
            logger.info("=" * 80)
            logger.info(f"📝 问题内容: {request.question[:100]}{'...' if len(request.question) > 100 else ''}")
            logger.info(f"🎯 报告模式: {request.report_mode}")
            logger.info(f"🖼️  影像数量: {len(request.images)}")
            logger.info(f"💬 历史信息: {len(request.all_info) if request.all_info else 0} 字符")
            logger.info(f"🔍 显示思考过程: {request.show_thinking}")
            logger.info("-" * 80)

            loop = asyncio.get_running_loop()
            final_answer_parts = []
            node_start_time = {}
            node_count = 0

            if request.images:
                logger.info(f"🖼️  [节点 {node_count + 1}] 影像分析开始")
                node_start_time["vision"] = time.time()
                
                vision_svc = resources.get("vision_service")
                if not vision_svc:
                    logger.warning("⚠️  影像识别服务未就绪")
                    yield json.dumps({"type": "token", "content": "影像识别服务未就绪，请稍后重试。"}, ensure_ascii=False)
                else:
                    vision_chunk_count = 0
                    async for event in vision_svc.analyze_stream(
                        images=request.images,
                        question=request.question,
                        all_info=request.all_info,
                    ):
                        if event.get("type") == "thinking":
                            logger.info(f"  🤔 影像分析思考: {event.get('title', '正在分析影像...')}")
                            yield json.dumps({
                                "type": "node_start",
                                "node": "vision",
                                "label": event.get("title", "正在分析影像..."),
                            }, ensure_ascii=False)
                        elif event.get("type") == "chunk":
                            content_str = str(event.get("content", ""))
                            if content_str:
                                final_answer_parts.append(content_str)
                                vision_chunk_count += 1
                                yield json.dumps({"type": "token", "content": content_str}, ensure_ascii=False)

                vision_time = time.time() - node_start_time["vision"]
                logger.info(f"✅ 影像分析完成 - 耗时: {vision_time:.2f}秒, 生成: {vision_chunk_count} 个片段")
                
                answer_text = "".join(final_answer_parts).strip()
                total_time = time.time() - start_time
                
                yield json.dumps({
                    "type": "done",
                    "request_id": req_id,
                    "name": "影像分析",
                    "all_info": request.all_info,
                }, ensure_ascii=False)
                
                logger.info(f"🟢 [请求 {req_id}] 完成 - 总耗时: {total_time:.2f}秒")
                logger.info("=" * 80)
                return

            naming_future = None
            if not request.all_info and resources.get("naming_model"):
                logger.info(f"🏷️  [节点 {node_count + 1}] 命名模型推理开始")
                node_start_time["naming"] = time.time()
                naming_future = loop.run_in_executor(
                    resources["executor"],
                    resources["naming_model"].run_naming,
                    request.question,
                )

            logger.info(f"🧠 [节点 {node_count + 1}] 临床推理链开始")
            node_start_time["clinical_reasoning"] = time.time()
            
            current_node = None
            node_chunk_counts = {}

            async for event in resources["model"].run_clinical_reasoning(
                case_text=request.question,
                all_info=request.all_info,
                report_mode=request.report_mode,
                show_thinking=request.show_thinking,
            ):
                if not isinstance(event, dict):
                    continue

                if event.get("type") == "error":
                    logger.error(f"❌ 推理错误: {event.get('content', 'Unknown error')}")
                    yield json.dumps(event, ensure_ascii=False)
                    return

                if event.get("type") == "node_start":
                    node_count += 1
                    current_node = event.get("node")
                    node_label = event.get("label", "")
                    logger.info(f"  🔄 [节点 {node_count}] {current_node}: {node_label}")
                    node_chunk_counts[current_node] = 0

                if event.get("type") == "token":
                    content_str = str(event.get("content", ""))
                    if content_str:
                        final_answer_parts.append(content_str)
                        if current_node:
                            node_chunk_counts[current_node] = node_chunk_counts.get(current_node, 0) + 1

                yield json.dumps(event, ensure_ascii=False)

            reasoning_time = time.time() - node_start_time["clinical_reasoning"]
            logger.info(f"✅ 临床推理链完成 - 耗时: {reasoning_time:.2f}秒")
            logger.info(f"📊 节点统计: {node_count} 个节点")
            for node, count in node_chunk_counts.items():
                logger.info(f"     - {node}: {count} 个片段")

            generated_name = "咨询"
            if naming_future:
                try:
                    generated_name = await naming_future or "咨询"
                    naming_time = time.time() - node_start_time["naming"]
                    logger.info(f"✅ 命名推理完成 - 耗时: {naming_time:.2f}秒, 结果: {generated_name}")
                except Exception as e:
                    logger.warning(f"⚠️  命名推理失败: {e}")

            answer_text = "".join(final_answer_parts).strip()
            updated_all_info = request.all_info

            if answer_text and resources.get("context_summary"):
                logger.info(f"💬 [节点 {node_count + 1}] 上下文摘要更新开始")
                summary_start = time.time()
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
                    summary_time = time.time() - summary_start
                    logger.info(f"✅ 上下文摘要更新完成 - 耗时: {summary_time:.2f}秒")
                    logger.info(f"     原始长度: {len(request.all_info)} 字符")
                    logger.info(f"     更新长度: {len(updated_all_info)} 字符")
                except Exception as summary_error:
                    logger.error(f"❌ 上下文摘要更新失败: {summary_error}")

            total_time = time.time() - start_time
            logger.info("-" * 80)
            logger.info(f"📊 [请求 {req_id}] 性能统计:")
            logger.info(f"     总耗时: {total_time:.2f}秒")
            logger.info(f"     生成文本: {len(answer_text)} 字符")
            logger.info(f"     平均速度: {len(answer_text)/total_time:.1f} 字符/秒")
            logger.info(f"     咨询名称: {generated_name}")
            logger.info("-" * 80)
            logger.info(f"🟢 [请求 {req_id}] 请求处理完成")
            logger.info("=" * 80)

            yield json.dumps({
                "type": "done",
                "request_id": req_id,
                "name": generated_name,
                "all_info": updated_all_info,
            }, ensure_ascii=False)

        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"❌ [请求 {req_id}] 处理失败 - 耗时: {error_time:.2f}秒")
            logger.error(f"     错误类型: {type(e).__name__}")
            logger.error(f"     错误信息: {str(e)}")
            logger.error("=" * 80)
            yield json.dumps(build_error_event(e, talk_id=None), ensure_ascii=False)

    return EventSourceResponse(generate(), ping=15)


@app.post("/ai/analyze", response_model=AnalyzeResponse)
async def analyze_patient_health_risk(request: AnalyzeRequest):
    """健康风险分析接口 - 增强日志版本"""
    verify_token(request.token)

    patient_text = request.data.strip()
    if not patient_text:
        raise HTTPException(status_code=422, detail="data cannot be empty")

    start_time = time.time()
    req_id = uuid.uuid4().hex[:12]
    
    logger.info("=" * 80)
    logger.info(f"🏥 [请求 {req_id}] 开始健康风险分析")
    logger.info("=" * 80)
    logger.info(f"👤 患者ID: {request.patientId}")
    logger.info(f"📋 数据长度: {len(patient_text)} 字符")
    logger.info(f"📝 数据内容: {patient_text[:200]}{'...' if len(patient_text) > 200 else ''}")
    logger.info(f"💬 历史信息: {len(request.all_info) if request.all_info else 0} 字符")
    logger.info("-" * 80)

    try:
        result = await HealthRiskAnalyzer().analyze(patient_text)
        analysis_time = time.time() - start_time
        
        logger.info(f"✅ 健康风险分析完成 - 耗时: {analysis_time:.2f}秒")
        logger.info(f"🎯 风险等级: {result.get('riskLevel', 'Unknown')}")
        logger.info(f"💡 建议长度: {len(result.get('suggestion', ''))} 字符")
        logger.info(f"📊 分析详情长度: {len(result.get('analysisDetails', ''))} 字符")
        logger.info("-" * 80)
        logger.info(f"🟢 [请求 {req_id}] 健康风险分析完成")
        logger.info("=" * 80)

        return {
            "code": 1,
            "msg": "success",
            "data": result
        }
    except Exception as e:
        error_time = time.time() - start_time
        logger.error(f"❌ [请求 {req_id}] 健康风险分析失败 - 耗时: {error_time:.2f}秒")
        logger.error(f"     错误类型: {type(e).__name__}")
        logger.error(f"     错误信息: {str(e)}")
        logger.error("=" * 80)
        raise HTTPException(status_code=500, detail=f"健康风险分析失败: {str(e)}")


class PubMedSearchRequest(BaseModel):
    query: str
    max_results: int = 5


@app.post("/model/pubmed/search")
async def pubmed_search(request: PubMedSearchRequest):
    """PubMed文献检索接口 - 增强日志版本"""
    query = request.query.strip()
    if not query:
        logger.info("🔍 PubMed检索: 查询为空，返回空结果")
        return {"code": 1, "msg": "success", "data": {"papers": []}}

    start_time = time.time()
    req_id = uuid.uuid4().hex[:12]
    
    logger.info("=" * 80)
    logger.info(f"📚 [请求 {req_id}] 开始PubMed文献检索")
    logger.info("=" * 80)
    logger.info(f"🔍 查询关键词: {query}")
    logger.info(f"📊 最大结果数: {request.max_results}")
    logger.info("-" * 80)

    svc = PubMedService()
    try:
        papers = await svc.search_papers(query, max_results=request.max_results)
        search_time = time.time() - start_time
        
        logger.info(f"✅ PubMed检索完成 - 耗时: {search_time:.2f}秒")
        logger.info(f"📊 检索结果: {len(papers)} 篇文献")
        
        if papers:
            for i, paper in enumerate(papers[:3], 1):  # 只显示前3篇
                title = paper.get('title', 'Unknown')
                logger.info(f"     [{i}] {title[:60]}{'...' if len(title) > 60 else ''}")
            if len(papers) > 3:
                logger.info(f"     ... 还有 {len(papers) - 3} 篇文献")
        
        logger.info("-" * 80)
        logger.info(f"🟢 [请求 {req_id}] PubMed检索完成")
        logger.info("=" * 80)
        
    except Exception as e:
        error_time = time.time() - start_time
        logger.error(f"❌ [请求 {req_id}] PubMed检索失败 - 耗时: {error_time:.2f}秒")
        logger.error(f"     错误类型: {type(e).__name__}")
        logger.error(f"     错误信息: {str(e)}")
        logger.error("=" * 80)
        papers = []

    return {"code": 1, "msg": "success", "data": {"papers": papers}}


@app.post("/admin/reload_config")
async def reload_config():
    """配置热更新接口 - 增强日志版本"""
    start_time = time.time()
    req_id = uuid.uuid4().hex[:12]
    
    logger.info("=" * 80)
    logger.info(f"🔄 [请求 {req_id}] 开始配置热更新")
    logger.info("=" * 80)
    
    try:
        logger.info("📋 重新加载Prompt配置...")
        get_prompt_manager().reload()
        logger.info("✅ Prompt配置重新加载完成")
        
        logger.info("📋 重新加载报告配置...")
        get_report_manager().reload()
        logger.info("✅ 报告配置重新加载完成")
        
        logger.info("📋 重新加载专家配置...")
        get_expert_manager().reload()
        logger.info("✅ 专家配置重新加载完成")
        
        logger.info("📋 重新加载校验配置...")
        get_validation_manager().reload()
        logger.info("✅ 校验配置重新加载完成")
        
        logger.info("📋 重新加载参数限制配置...")
        get_limits_manager().reload()
        logger.info("✅ 参数限制配置重新加载完成")
        
        reload_time = time.time() - start_time
        logger.info("-" * 80)
        logger.info(f"✅ 所有配置重新加载完成 - 耗时: {reload_time:.2f}秒")
        logger.info(f"🟢 [请求 {req_id}] 配置热更新完成")
        logger.info("=" * 80)
        
        return {"status": "ok", "message": "配置已热更新"}
    except Exception as e:
        error_time = time.time() - start_time
        logger.error(f"❌ [请求 {req_id}] 配置热更新失败 - 耗时: {error_time:.2f}秒")
        logger.error(f"     错误类型: {type(e).__name__}")
        logger.error(f"     错误信息: {str(e)}")
        logger.error("=" * 80)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/report_modes")
async def list_report_modes():
    """获取可用报告模式接口 - 增强日志版本"""
    req_id = uuid.uuid4().hex[:12]
    
    logger.info(f"📋 [请求 {req_id}] 获取可用报告模式")
    
    mgr = get_report_manager()
    modes = mgr.list_modes()
    
    logger.info(f"✅ 可用报告模式: {modes}")
    
    return {"modes": modes}
    return {
        "modes": [
            {"key": m, "name": mgr.get_template_name(m)}
            for m in modes
        ]
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)