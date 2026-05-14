
from typing import Any, List, Tuple
import csv
import json
import ast
import argparse
import os
import sys
import tempfile
import shutil
import time

POSSIBLE_SOURCE_KEYS = ("source", "filename", "title", "doc", "document", "url", "source_name", "source_title")

def safe_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""

def parse_contexts_field(raw: Any) -> List[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, tuple):
        return list(raw)
    if isinstance(raw, float):
        return []
    s = safe_text(raw).strip()
    if s == "":
        return []
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return parsed
        else:
            return [parsed]
    except Exception:
        pass
    try:
        parsed = ast.literal_eval(s)
        if isinstance(parsed, (list, tuple)):
            return list(parsed)
        else:
            return [parsed]
    except Exception:
        pass
    separators = ["|||", "\n---\n", "\n\n", ";;;"]
    for sep in separators:
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) > 1:
                return parts
    return [s]

def extract_context_source(ctx_item: Any) -> Tuple[str, str]:
    if isinstance(ctx_item, dict):
        text_parts = []
        for k in ("content", "text", "page_content", "snippet", "body"):
            if k in ctx_item and ctx_item[k]:
                text_parts.append(safe_text(ctx_item[k]))
        text = "\n".join(text_parts) if text_parts else json.dumps(ctx_item, ensure_ascii=False)
        src = ""
        for k in POSSIBLE_SOURCE_KEYS:
            if k in ctx_item and ctx_item[k]:
                src = safe_text(ctx_item[k])
                break
        if not src:
            for k in ("meta", "metadata"):
                if k in ctx_item and isinstance(ctx_item[k], dict):
                    for subk in POSSIBLE_SOURCE_KEYS:
                        if subk in ctx_item[k] and ctx_item[k][subk]:
                            src = safe_text(ctx_item[k][subk])
                            break
                    if src:
                        break
        return text, src
    else:
        return safe_text(ctx_item), ""

def atomic_write_json(path: str, data: dict):
    """Write JSON atomically (tmp + rename)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_checkpoint(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_checkpoint(path: str, next_row: int):
    data = {"next_row": next_row, "ts": time.time()}
    atomic_write_json(path, data)

def ensure_output_header(out_path: str, fieldnames: List[str], encoding: str = "utf-8-sig"):
    exists = os.path.exists(out_path)
    if not exists:
        with open(out_path, "w", newline="", encoding=encoding) as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

def append_rows(out_path: str, rows: List[dict], fieldnames: List[str], encoding: str = "utf-8-sig"):
    first = not os.path.exists(out_path)
    with open(out_path, "a", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if first:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)

def process_stream(input_csv: str, out_csv: str, contexts_col: str = "contexts",
                   checkpoint_file: str = None, resume: bool = True,
                   checkpoint_interval: int = 100, keep_empty: bool = False,
                   encoding: str = "utf-8-sig", force_restart: bool = False):
    if checkpoint_file is None:
        checkpoint_file = out_csv + ".checkpoint.json"

    if force_restart:
        if os.path.exists(checkpoint_file):
            os.remove(checkpoint_file)
        if os.path.exists(out_csv):
            print(f"[INFO] force_restart: removing existing output {out_csv}")
            os.remove(out_csv)

    start_row = 0
    if resume:
        cp = load_checkpoint(checkpoint_file)
        if cp and "next_row" in cp:
            start_row = int(cp["next_row"])
            print(f"[INFO] Resuming from checkpoint: next_row = {start_row} (from {checkpoint_file})")
        else:
            print("[INFO] No checkpoint found or invalid; starting from row 0")

    out_fields = ["sample_idx", "question", "answer", "ground_truth", "context_idx", "context_text", "context_source"]
    ensure_output_header(out_csv, out_fields, encoding=encoding)

    total_processed = 0
    last_saved_row = start_row
    current_input_idx = -1
    try:
        with open(input_csv, newline="", encoding=encoding) as csvfile:
            reader = csv.DictReader(csvfile)
            # Validate contexts_col
            if contexts_col not in reader.fieldnames:
                print(f"[WARN] contexts column '{contexts_col}' not found in input. Available columns: {reader.fieldnames}")
            for current_input_idx, raw_row in enumerate(reader):
                if current_input_idx < start_row:
                    continue
                sample_idx = current_input_idx
                question = raw_row.get("question", "")
                answer = raw_row.get("answer", "")
                ground_truth = raw_row.get("ground_truth", "")
                raw_contexts = raw_row.get(contexts_col, None) if contexts_col in reader.fieldnames else None

                contexts = parse_contexts_field(raw_contexts)
                out_rows = []
                if contexts:
                    for i, ctx in enumerate(contexts):
                        text, src = extract_context_source(ctx)
                        out_rows.append({
                            "sample_idx": sample_idx,
                            "question": question,
                            "answer": answer,
                            "ground_truth": ground_truth,
                            "context_idx": i,
                            "context_text": text,
                            "context_source": src
                        })
                else:
                    if keep_empty:
                        out_rows.append({
                            "sample_idx": sample_idx,
                            "question": question,
                            "answer": answer,
                            "ground_truth": ground_truth,
                            "context_idx": -1,
                            "context_text": "",
                            "context_source": ""
                        })
                if out_rows:
                    append_rows(out_csv, out_rows, out_fields, encoding=encoding)

                total_processed += 1

                if (total_processed % checkpoint_interval) == 0:
                    next_row = current_input_idx + 1
                    save_checkpoint(checkpoint_file, next_row)
                    last_saved_row = next_row
                    print(f"[INFO] checkpoint saved at next_row={next_row} (processed {total_processed} rows this run)")

    except KeyboardInterrupt:
        next_row = current_input_idx + 1
        save_checkpoint(checkpoint_file, next_row)
        print(f"\n[INTERRUPT] KeyboardInterrupt caught. Checkpoint saved at next_row={next_row}. You can resume with --resume True.")
        return
    except Exception as e:
        next_row = current_input_idx + 1 if current_input_idx >= 0 else start_row
        try:
            save_checkpoint(checkpoint_file, next_row)
            print(f"[ERROR] Exception: {e}. Checkpoint saved at next_row={next_row}. Exiting.")
        except Exception:
            print(f"[ERROR] Exception while saving checkpoint: {e}. Exiting without checkpoint.")
        raise

    final_next = current_input_idx + 1 if current_input_idx >= 0 else start_row
    save_checkpoint(checkpoint_file, final_next)
    print(f"[DONE] Finished processing. Final checkpoint next_row={final_next}. Output: {out_csv}")

def main():
    parser = argparse.ArgumentParser(description="Incremental expand contexts with checkpoint/resume")
    parser.add_argument("input_csv", help="Input CSV path (e.g. medical_agent_eval_details.csv)")
    parser.add_argument("--out", "-o", default="contexts_expanded.csv", help="Output CSV path")
    parser.add_argument("--contexts_col", default="contexts", help="Name of contexts column in input")
    parser.add_argument("--checkpoint-file", default=None, help="Checkpoint file path (default: <out>.checkpoint.json)")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from checkpoint if exists")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not resume even if checkpoint exists")
    parser.add_argument("--checkpoint-interval", type=int, default=100, help="Save checkpoint every N input rows")
    parser.add_argument("--keep-empty", action="store_true", help="Keep rows even if contexts empty (context_idx=-1)")
    parser.add_argument("--encoding", default="utf-8-sig", help="File encoding (default utf-8-sig)")
    parser.add_argument("--force-restart", action="store_true", help="Ignore existing checkpoint and output, start fresh")
    args = parser.parse_args()

    if args.checkpoint_file is None:
        checkpoint_file = args.out + ".checkpoint.json"
    else:
        checkpoint_file = args.checkpoint_file

    # call processor
    process_stream(
        input_csv=args.input_csv,
        out_csv=args.out,
        contexts_col=args.contexts_col,
        checkpoint_file=checkpoint_file,
        resume=args.resume,
        checkpoint_interval=args.checkpoint_interval,
        keep_empty=args.keep_empty,
        encoding=args.encoding,
        force_restart=args.force_restart
    )

if __name__ == "__main__":
    main()
