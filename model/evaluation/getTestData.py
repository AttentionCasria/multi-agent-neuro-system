
import os
import json
import argparse
import logging
import time
import asyncio
import pandas as pd

from datasets import load_dataset, Dataset
from ragas import evaluate
from ragas.llms import llm_factory

# �?修复 deprecation warning
from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)

import openai

OUT_CSV = "medical_agent_eval_details.csv"
PARTIAL_CSV = "medical_agent_eval_details_partial.csv"
CKPT = "getTestData.ckpt.json"  # �?断点文件

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL")

NEURO_KEYWORDS = [
    "�?, "神经", "卒中", "中风", "脑梗", "脑出血", "脑血�?,
    "头痛", "头晕", "眩晕", "昏迷", "意识",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("RAGAS-Neuro")

def load_checkpoint():
    if os.path.exists(CKPT):
        try:
            with open(CKPT, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"next_idx": 0, "written": 0}


def save_checkpoint(next_idx, written):
    with open(CKPT, "w", encoding="utf-8") as f:
        json.dump({
            "next_idx": next_idx,
            "written": written,
            "ts": time.time()
        }, f, ensure_ascii=False, indent=2)


def safe_text(x):
    if x is None:
        return ""
    if isinstance(x, (list, dict)):
        return json.dumps(x, ensure_ascii=False)
    return str(x).strip()


def is_neuro_case(case):
    text = (
            safe_text(case.get('title', '')) +
            safe_text(case.get('description', '')) +
            safe_text(case.get('exam', '')) +
            safe_text(case.get('question', ''))
    ).lower()

    return any(keyword in text for keyword in NEURO_KEYWORDS)


def append_partial_row(row: dict):
    if not os.path.exists(PARTIAL_CSV):
        pd.DataFrame(columns=row.keys()).to_csv(
            PARTIAL_CSV, index=False, encoding="utf-8-sig"
        )
    pd.DataFrame([row]).to_csv(
        PARTIAL_CSV,
        mode="a",
        header=False,
        index=False,
        encoding="utf-8-sig"
    )


def normalize_contexts(contexts):
    if not contexts:
        logger.warning("⚠️ contexts 为空，使用占位文�?)
        return ["未检索到相关神经医学文献"]

    flat = []
    for c in contexts:
        if isinstance(c, dict):
            text = f"{c.get('content', '')} {c.get('text', '')}".strip()
            if text:
                flat.append(text[:500])
        elif isinstance(c, str) and c.strip():
            flat.append(c[:500])

    if not flat:
        return ["未检索到相关神经医学文献"]

    return flat[:5]


def build_question(case):
    """�?简化问题格�?""
    title = safe_text(case.get('title', ''))
    desc = safe_text(case.get('description', ''))
    question = f"{title} {desc}".strip()
    return question[:300]


def extract_reference(case):

    candidates = []

    for key in ["diagnosis", "final_diagnosis", "诊断", "主要诊断"]:
        if case.get(key):
            candidates.append(safe_text(case.get(key)))

    if case.get("explanation"):
        candidates.append(safe_text(case.get("explanation")))

    if case.get("answer"):
        ans = case["answer"]
        if len(ans) == 1 and ans.isalpha():
            option_text = case.get(f"option_{ans}", "")
            if option_text:
                candidates.append(option_text)
        candidates.append(ans)

    for key in ["treatment", "management", "治疗", "处理", "建议"]:
        if case.get(key):
            candidates.append(safe_text(case.get(key)))

    if candidates:
        result = " ".join([c for c in candidates if c])[:300]
        return result if result else "无明确参考答�?

    return "无明确参考答�?


def generate_samples(agent, test_count=5, resume=True, force_restart=False):
    logger.info("📦 开始筛选神经医学病�?..")

    dataset = load_dataset(
        "FreedomIntelligence/CMB",
        "CMB-Clin",
        split="test"
    )

    if force_restart:
        for f in [CKPT, PARTIAL_CSV, OUT_CSV]:
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"🗑�?已删除旧文件: {f}")

    ck = load_checkpoint() if resume else {"next_idx": 0, "written": 0}
    start_idx = int(ck["next_idx"])
    written = int(ck["written"])
    skipped = 0

    logger.info(f"📍 从索�?{start_idx} 继续，已完成 {written} 个样�?)

    for idx in range(start_idx, len(dataset)):
        if written >= test_count:
            logger.info(f"�?已完成目标数�?{test_count} 个样�?)
            break

        case = dataset[idx]

        if not is_neuro_case(case):
            skipped += 1
            save_checkpoint(idx + 1, written)
            continue

        try:
            q = build_question(case)
            logger.info(f"🧠 处理神经病例 {idx}: {q[:50]}...")

            res = agent.run(q)

            if isinstance(res, tuple) and len(res) == 2:
                answer, contexts = res
            else:
                answer = str(res)
                contexts = []
                logger.warning(f"⚠️ agent 未返�?contexts，样�?{idx}")

            contexts = normalize_contexts(contexts)
            answer = safe_text(answer)[:800]

            row = {
                "question": q,
                "answer": answer,
                "contexts": json.dumps(contexts, ensure_ascii=False),
                "reference": extract_reference(case),
                "dataset_idx": idx,
                "ts": int(time.time())
            }

            append_partial_row(row)
            written += 1
            save_checkpoint(idx + 1, written)
            logger.info(f"�?样本 {idx} 完成 (已跳�?{skipped} 个非神经病例)")

        except Exception as e:
            logger.error(f"�?样本 {idx} 失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            save_checkpoint(idx + 1, written)

    if os.path.exists(PARTIAL_CSV):
        pd.read_csv(PARTIAL_CSV).to_csv(
            OUT_CSV, index=False, encoding="utf-8-sig"
        )
        logger.info(f"�?已保�?{written} 条神经医学样本到 {OUT_CSV}")

def prepare_for_ragas(df: pd.DataFrame):
    df = df.rename(columns={
        "question": "user_input",
        "answer": "response",
        "contexts": "retrieved_contexts",
        "reference": "reference"
    })

    def parse_contexts(x):
        try:
            parsed = json.loads(x) if isinstance(x, str) else x
            if isinstance(parsed, list):
                return [str(item)[:500] for item in parsed if item]
            return ["未检索到相关神经医学文献"]
        except:
            return ["未检索到相关神经医学文献"]

    df["retrieved_contexts"] = df["retrieved_contexts"].apply(parse_contexts)
    df["reference"] = df["reference"].astype(str)

    df["user_input"] = df["user_input"].astype(str).str[:300]
    df["response"] = df["response"].astype(str).str[:800]
    df["reference"] = df["reference"].astype(str).str[:200]

    logger.info("�?数据格式化完成，预览:")
    logger.info(df[["user_input", "retrieved_contexts", "reference"]].head(1))

    return Dataset.from_pandas(df)


def run_evaluation(eval_count=5):
    logger.info("⚖️ 开�?RAGAS 评测...")

    if not os.path.exists(OUT_CSV):
        logger.error(f"�?未找到数据文�? {OUT_CSV}")
        return

    df = pd.read_csv(OUT_CSV, dtype=str).tail(eval_count)
    dataset = prepare_for_ragas(df)

    # �?创建 OpenAI client
    client = openai.OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_API_BASE_URL
    )

    # �?使用 llm_factory 创建 LLM
    ragas_llm = llm_factory(
        model="gpt-4o-mini",
        client=client,
        temperature=0,
        max_tokens=8192,
    )
    from ragas.metrics import faithfulness

    metrics = [faithfulness]

    try:
        logger.info("📊 正在计算 Faithfulness 指标（医学答案准确性）...")

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=ragas_llm,
            raise_exceptions=False,
        )

        # �?核心修复：处理列表结�?
        result_df = result.to_pandas()
        faithfulness_scores = result_df['faithfulness'].tolist()
        avg_faithfulness = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0
        min_faithfulness = min(faithfulness_scores) if faithfulness_scores else 0
        max_faithfulness = max(faithfulness_scores) if faithfulness_scores else 0

        print("\n" + "=" * 60)
        print("🎯 神经医学 RAGAS 评测结果")
        print("=" * 60)
        print(f"Faithfulness（医学答案准确性）")
        print(f"  �?平均�? {avg_faithfulness:.4f}")
        print(f"  �?最小�? {min_faithfulness:.4f}")
        print(f"  �?最大�? {max_faithfulness:.4f}")
        print("=" * 60)

        print("\n📊 指标解释:")
        print("- Faithfulness 范围: 0.0 ~ 1.0")
        print("  * 0.0-0.3: 回答严重缺乏依据，存在幻�?)
        print("  * 0.3-0.6: 回答部分正确，但有些观点缺乏证据支持")
        print("  * 0.6-0.8: 回答较为准确，大部分基于检索文�?)
        print("  * 0.8-1.0: 回答完全基于检索文献，准确可靠")

        # �?判断评估等级
        if avg_faithfulness >= 0.8:
            level = "🟢 优秀"
        elif avg_faithfulness >= 0.6:
            level = "🟡 良好"
        elif avg_faithfulness >= 0.4:
            level = "🟠 需改进"
        else:
            level = "🔴 需严重改进"

        print(f"\n总体评估: {level}")

        # 保存结果
        result_df.to_csv(
            "ragas_neuro_results.csv",
            index=False,
            encoding="utf-8-sig"
        )
        logger.info("�?结果已保存到 ragas_neuro_results.csv")

        print("\n" + "=" * 60)
        print("📋 逐样�?Faithfulness 分数详情:")
        print("=" * 60)
        for idx, row in result_df.iterrows():
            score = row['faithfulness']
            if score >= 0.7:
                status = "�?
            elif score >= 0.4:
                status = "⚠️"
            else:
                status = "�?
            print(f"{status} 样本 {idx}: {score:.4f}")

    except Exception as e:
        logger.error(f"�?RAGAS 评测失败: {e}")
        import traceback
        logger.error(traceback.format_exc())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_count", type=int, default=5, help="需要收集的神经病例数量")
    parser.add_argument("--eval_only", action="store_true", help="仅运行评�?)
    parser.add_argument("--resume", action="store_true", help="从断点继�?)
    parser.add_argument("--force_restart", action="store_true", help="强制重新开�?)
    args = parser.parse_args()

    if not args.eval_only:
        from app.agents.qwen.qwenAgent import qwenAgent
        agent = qwenAgent()
        generate_samples(
            agent,
            test_count=args.test_count,
            resume=args.resume,
            force_restart=args.force_restart
        )

    run_evaluation(eval_count=args.test_count)


if __name__ == "__main__":
    main()


