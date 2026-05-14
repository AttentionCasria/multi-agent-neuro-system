

import os
import argparse
import logging
import json
import math
from collections import Counter, defaultdict
import pandas as pd
import matplotlib.pyplot as plt

from datasets import load_dataset, Dataset
from ragas import evaluate
from ragas.metrics.collections import faithfulness, answer_relevancy, context_precision, context_recall

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK-API-KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE")

judge_llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1",
    temperature=0
)

judge_embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    openai_api_key=OPENAI_API_KEY,
    base_url=OPENAI_API_BASE_URL
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MedicalEvaluatorAnalysis")

def safe_text(x):
    if x is None:
        return ""
    if isinstance(x, (list, dict)):
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return str(x)
    return str(x).strip()

GT_FIELD_CANDIDATES = [
    "diagnosis", "final_diagnosis", "label", "answer", "answers", "gold_answer",
    "ground_truth", "groundtruth", "diagnoses", "diagnostic", "结论", "诊断", "病理诊断",
    "诊断结果", "最终诊断", "参考答案", "pathology", "pathologic"
]

def extract_ground_truth(case):
    gt_list = []
    matched_fields = []
    for key in GT_FIELD_CANDIDATES:
        if key in case:
            v = case.get(key)
            if v:
                if isinstance(v, list):
                    for it in v:
                        s = safe_text(it)
                        if s:
                            gt_list.append(s)
                else:
                    s = safe_text(v)
                    if s:
                        gt_list.append(s)
                matched_fields.append(key)
    # 扫描额外键名
    for k in case.keys():
        if k in GT_FIELD_CANDIDATES:
            continue
        low = k.lower()
        if "诊断" in k or "diagnos" in low or "pathol" in low:
            v = case.get(k)
            if v:
                s = safe_text(v)
                if s and s not in gt_list:
                    gt_list.append(s)
                    matched_fields.append(k)
    # 去重
    gt_list = [g for i,g in enumerate(gt_list) if g and g not in gt_list[:i]]
    return gt_list, matched_fields

def build_question_from_case(case, prompt_variant=1):
    title = safe_text(case.get("title", ""))
    description = safe_text(case.get("description", ""))
    extra_parts = []
    for k in ("history", "past_history", "clinical_history", "present_illness", "abstract"):
        if case.get(k):
            extra_parts.append(safe_text(case.get(k)))
    extra_text = "\n".join(extra_parts)
    question_text = f"""你是一名神经内科医生，请根据以下病历做出专业诊断并给出诊断依据。

【病历标题】
{title}

【病史与检查】
{description}
{extra_text}

请给出：
1) 主要诊断（列出诊断名称）
2) 诊断依据（要点式）
3) 如果有推荐的下一步检查或鉴别诊断，也请简要列出。
"""
    return question_text

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def analyze_eval_samples(eval_samples, out_dir="analysis_plots", top_n=20):
    ensure_dir(out_dir)
    n = len(eval_samples)
    analysis = {}
    analysis['n_samples'] = n

    gt_counts = 0
    auto_gt_counts = 0
    gt_field_counter = Counter()
    gt_texts = []
    for s in eval_samples:
        gts = s.get("ground_truth", [])
        if not gts or (len(gts) == 1 and gts[0] == "AUTO_GROUND_TRUTH"):
            if gts and gts[0] == "AUTO_GROUND_TRUTH":
                auto_gt_counts += 1
        else:
            gt_counts += 1
            for gt in gts:
                gt_texts.append(gt)
        if s.get("gt_extracted_from_fields"):
            for f in s["gt_extracted_from_fields"]:
                gt_field_counter[f] += 1

    analysis['gt_found_count'] = gt_counts
    analysis['auto_gt_count'] = auto_gt_counts
    analysis['gt_found_rate'] = gt_counts / n if n else 0
    analysis['auto_gt_rate'] = auto_gt_counts / n if n else 0
    analysis['gt_field_distribution'] = gt_field_counter.most_common()

    token_counter = Counter()
    for t in gt_texts:
        for tok in [x.strip().lower() for x in re_split_tokens(t)]:
            if tok:
                token_counter[tok] += 1
    analysis['top_gt_terms'] = token_counter.most_common(top_n)

    answer_lens = []
    gt_lens = []
    context_counts = []
    context_source_counter = Counter()
    for s in eval_samples:
        ans = safe_text(s.get("answer", ""))
        answer_lens.append(len(ans))
        gts = s.get("ground_truth", [])
        gt_concat = " ".join(gts) if isinstance(gts, list) else safe_text(gts)
        gt_lens.append(len(gt_concat))
        ctxs = s.get("contexts", []) or []
        if isinstance(ctxs, list):
            context_counts.append(len(ctxs))
            for c in ctxs:
                if isinstance(c, dict):
                    for key in ("source", "filename", "doc", "title"):
                        if key in c and c.get(key):
                            context_source_counter[safe_text(c.get(key))] += 1
                            break
                elif isinstance(c, str):
                    pass
        else:
            context_counts.append(0)

    analysis['answer_len_stats'] = numeric_stats(answer_lens)
    analysis['gt_len_stats'] = numeric_stats(gt_lens)
    analysis['context_count_stats'] = numeric_stats(context_counts)
    analysis['top_context_sources'] = context_source_counter.most_common(30)

    if answer_lens:
        plt.figure()
        plt.hist(answer_lens, bins='auto')
        plt.title("agent answer length distribution (chars)")
        plt.xlabel("Length (chars)")
        plt.ylabel("Count")
        p1 = os.path.join(out_dir, "answer_length_hist.png")
        plt.tight_layout()
        plt.savefig(p1)
        plt.close()
        analysis['answer_length_plot'] = p1

    if gt_lens:
        plt.figure()
        plt.hist(gt_lens, bins='auto')
        plt.title("Ground truth length distribution (chars)")
        plt.xlabel("Length (chars)")
        plt.ylabel("Count")
        p2 = os.path.join(out_dir, "gt_length_hist.png")
        plt.tight_layout()
        plt.savefig(p2)
        plt.close()
        analysis['gt_length_plot'] = p2

    if context_counts:
        plt.figure()
        plt.hist(context_counts, bins=range(0, max(context_counts)+2))
        plt.title("Number of contexts retrieved per sample")
        plt.xlabel("Num contexts")
        plt.ylabel("Count")
        p3 = os.path.join(out_dir, "context_count_hist.png")
        plt.tight_layout()
        plt.savefig(p3)
        plt.close()
        analysis['context_count_plot'] = p3

    if analysis['top_gt_terms']:
        keys = [k for k,_ in analysis['top_gt_terms'][:top_n]]
        vals = [v for _,v in analysis['top_gt_terms'][:top_n]]
        plt.figure(figsize=(8, max(3, len(keys)*0.3)))
        plt.barh(range(len(keys))[::-1], vals)
        plt.yticks(range(len(keys))[::-1], keys)
        plt.title("Top GT terms")
        plt.xlabel("Frequency")
        p4 = os.path.join(out_dir, "top_gt_terms.png")
        plt.tight_layout()
        plt.savefig(p4)
        plt.close()
        analysis['top_gt_terms_plot'] = p4

    return analysis

def re_split_tokens(s):
    import re
    toks = re.split(r"[,\s;:/()\\\[\]\{\}<>，。；：、\t\n]+", s)
    toks = [t for t in toks if t]
    return toks

def numeric_stats(lst):
    if not lst:
        return {"count": 0}
    import statistics
    return {
        "count": len(lst),
        "mean": statistics.mean(lst),
        "median": statistics.median(lst),
        "min": min(lst),
        "max": max(lst),
        "stdev": statistics.pstdev(lst) if len(lst) > 1 else 0
    }

def main_eval(test_count=3, keywords=None, dataset_name="FreedomIntelligence/CMB", subset="CMB-Clin",
              allow_no_gt=False, debug_save_raw=0, do_analysis=True):
    logger.info("初始化 qwenAgent ...")
    try:
        from app.agents.qwen.qwenAgent import qwenAgent
    except Exception as e:
        logger.error("无法导入 qwenAgent: %s", e)
        raise
    agent = qwenAgent()

    logger.info("加载数据集: %s / %s", dataset_name, subset)
    raw_ds = load_dataset(dataset_name, subset, split="test")
    logger.info("数据集样本数 (test split) = %d", len(raw_ds))

    if keywords is None or len(keywords) == 0:
        keywords = ["神经", "脑", "卒中", "帕金森", "癫痫", "瘫痪"]

    eval_samples = []
    skipped_debug = []
    processed = 0

    if debug_save_raw and debug_save_raw > 0:
        raw_list = [dict(raw_ds[i]) for i in range(min(len(raw_ds), debug_save_raw))]
        with open("raw_samples_debug.json", "w", encoding="utf-8") as f:
            json.dump(raw_list, f, ensure_ascii=False, indent=2)
        logger.info("已保存 raw_samples_debug.json (%d 条)", len(raw_list))

    for idx, case in enumerate(raw_ds):
        if processed >= test_count:
            break

        title = safe_text(case.get("title", ""))
        description = safe_text(case.get("description", ""))
        blob = (title + " " + description).strip()
        if not any(k in blob for k in keywords):
            skipped_debug.append({
                "dataset_idx": idx,
                "reason": "keyword_filter",
                "title": title,
                "description_snippet": description[:200]
            })
            continue

        if case.get("QA"):
            qas = case.get("QA") or []
            for qa in qas:
                if processed >= test_count: break
                q_text = safe_text(qa.get("question"))
                question_text = f"病历背景：{description}\n问题：{q_text}"
                logger.info("QA 模式: dataset idx %d | 问题: %s", idx, q_text[:80])
                try:
                    res_tuple = agent.run(question_text)
                    if isinstance(res_tuple, tuple) and len(res_tuple) >= 2:
                        res, sum_res = res_tuple[0], res_tuple[1]
                    else:
                        res = res_tuple; sum_res = []
                except Exception as e:
                    skipped_debug.append({"dataset_idx": idx, "reason": f"agent_error: {e}", "qa_question": q_text})
                    continue
                ground_truth, matched_fields = extract_ground_truth(case)
                if not ground_truth:
                    if allow_no_gt:
                        ground_truth = ["AUTO_GROUND_TRUTH"]
                    else:
                        skipped_debug.append({"dataset_idx": idx, "reason": "no_ground_truth", "qa_question": q_text})
                        continue
                eval_samples.append({
                    "question": question_text,
                    "answer": res,
                    "contexts": sum_res,
                    "ground_truth": ground_truth,
                    "gt_extracted_from_fields": matched_fields
                })
                processed += 1
            continue

        question_text = build_question_from_case(case, prompt_variant=1)
        logger.info("Case 模式: dataset idx %d | 准备运行 agent (第 %d 题)", idx, processed + 1)
        try:
            res_tuple = agent.run(question_text)
            if isinstance(res_tuple, tuple) and len(res_tuple) >= 2:
                res, sum_res = res_tuple[0], res_tuple[1]
            else:
                res = res_tuple; sum_res = []
        except Exception as e:
            skipped_debug.append({"dataset_idx": idx, "reason": f"agent_error: {e}"})
            continue

        ground_truth, matched_fields = extract_ground_truth(case)
        if not ground_truth:
            if allow_no_gt:
                ground_truth = ["AUTO_GROUND_TRUTH"]
            else:
                skipped_debug.append({
                    "dataset_idx": idx,
                    "reason": "no_ground_truth",
                    "title": title,
                    "description_snippet": description[:200],
                    "detected_keys": list(case.keys())[:40]
                })
                continue

        eval_samples.append({
            "question": question_text,
            "answer": res,
            "contexts": sum_res,
            "ground_truth": ground_truth,
            "gt_extracted_from_fields": matched_fields
        })
        processed += 1

    if not eval_samples:
        logger.error("❌ 未提取到有效测试数据（eval_samples 为空）。将保存 debug 输出以便排查。")
        if skipped_debug:
            pd.DataFrame(skipped_debug).to_csv("skipped_samples_debug.csv", index=False, encoding="utf-8-sig")
            logger.info("已保存 skipped_samples_debug.csv (%d 条记录)", len(skipped_debug))
        else:
            logger.info("skipped_debug 为空，说明关键词过滤可能过滤掉了全部样本，请检查 keywords 或 dataset。")
        return

    logger.info("使用 Ragas 对 %d 条样本进行自动化评分...", len(eval_samples))
    eval_dataset = Dataset.from_pandas(pd.DataFrame(eval_samples))
    try:
        result = evaluate(
            dataset=eval_dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            llm=judge_llm,
            embeddings=judge_embeddings
        )
    except Exception as e:
        logger.error("Ragas evaluate 出错: %s", e)
        raise

    try:
        if hasattr(result, "to_pandas"):
            df_result = result.to_pandas()
        else:
            df_result = pd.DataFrame(eval_samples)
        out_details = "medical_agent_eval_details.csv"
        df_result.to_csv(out_details, index=False, encoding="utf-8-sig")
        logger.info("已保存 %s", out_details)
    except Exception as e:
        logger.error("保存 CSV 出错: %s", e)

    if skipped_debug:
        pd.DataFrame(skipped_debug).to_csv("skipped_samples_debug.csv", index=False, encoding="utf-8-sig")
        logger.info("已保存 skipped_samples_debug.csv (%d 条)", len(skipped_debug))

    if do_analysis:
        logger.info("开始数据分析...")
        analysis = analyze_eval_samples(eval_samples, out_dir="analysis_plots", top_n=30)
        with open("analysis_summary.json", "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        logger.info("已保存 analysis_summary.json")
        md_lines = []
        md_lines.append("# Evaluator Analysis Report\n")
        md_lines.append(f"- 样本数: **{analysis.get('n_samples',0)}**")
        md_lines.append(f"- GT 被提取（非 AUTO）样本数: **{analysis.get('gt_found_count',0)}**")
        md_lines.append(f"- 自动 GT (AUTO_GROUND_TRUTH) 样本数: **{analysis.get('auto_gt_count',0)}**")
        md_lines.append(f"- GT 提取率: **{analysis.get('gt_found_rate',0):.2%}**")
        md_lines.append("\n## GT 字段命中分布（Top）")
        for f,c in analysis.get('gt_field_distribution', [])[:30]:
            md_lines.append(f"- `{f}`: {c}")
        md_lines.append("\n## Top GT terms")
        for k,v in analysis.get('top_gt_terms', [])[:30]:
            md_lines.append(f"- {k} — {v}")
        md_lines.append("\n## 数值统计")
        md_lines.append("### Answer length")
        md_lines.append(str(analysis.get('answer_len_stats', {})))
        md_lines.append("### GT length")
        md_lines.append(str(analysis.get('gt_len_stats', {})))
        md_lines.append("### Context count")
        md_lines.append(str(analysis.get('context_count_stats', {})))
        md_lines.append("\n## 生成的图表")
        for key in ["answer_length_plot", "gt_length_plot", "context_count_plot", "top_gt_terms_plot"]:
            if analysis.get(key):
                md_lines.append(f"- ![]({analysis.get(key)})")
        with open("analysis_report.md", "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        logger.info("已保存 analysis_report.md")

    logger.info("全部流程结束。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_count", type=int, default=3)
    parser.add_argument("--keywords", type=str, default=None)
    parser.add_argument("--allow_no_gt", type=lambda s: s.lower() in ("true","1","yes"), default=False)
    parser.add_argument("--debug_save_raw", type=int, default=0, help="保存原始样本前 N 条到 raw_samples_debug.json")
    parser.add_argument("--do_analysis", type=lambda s: s.lower() in ("true","1","yes"), default=True)
    args = parser.parse_args()

    kw = None
    if args.keywords:
        kw = [k.strip() for k in args.keywords.split(",") if k.strip()]

    main_eval(test_count=args.test_count, keywords=kw, allow_no_gt=args.allow_no_gt,
              debug_save_raw=args.debug_save_raw, do_analysis=args.do_analysis)
