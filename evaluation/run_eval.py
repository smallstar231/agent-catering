# 离线评估运行器（CLI）
# 功能：加载测试集 → 逐条跑 Agent 拿回答 → 打分(exact_match + LLM judge) → 汇总报告
# 用法：
#   python -m evaluation.run_eval                      # 跑内置示例集
#   python -m evaluation.run_eval --dataset data/myds.jsonl --category kb
# 说明：会真实调用 Agent（含模型与工具），耗时较长，适合改 prompt/工具后做回归。

import argparse
import json
import os
import time
import statistics
from utils.logger_handler import logger

from evaluation.dataset import sample_dataset, load_dataset, save_dataset
from evaluation.evaluators import exact_match_score, llm_judge_score


def _answer_agent(query: str, history: list | None = None) -> str:
    """调 Agent 取纯文本回答（复用 execute_stream，丢弃 tool/reasoning 事件）"""
    from agent.react_agent import ReactAgent
    # 惰性建单例，避免重复初始化
    global _AGENT
    if _AGENT is None:
        _AGENT = ReactAgent()
    parts = []
    for event, payload in _AGENT.execute_stream_events(query, history=history or []):
        if event == "text":
            parts.append(payload)
    return "".join(parts).strip()

_AGENT = None


def run_evaluation(dataset_path: str | None = None, category: str | None = None, limit: int | None = None) -> dict:
    """
    执行一轮评估。
    入参：
        dataset_path - 数据集 JSONL 路径；None 用内置示例
        category     - 只评该分类；None 评全部
        limit        - 最多评多少条；None 评全部
    返回：汇总统计 dict + 逐条结果
    """
    # 1) 取数据集
    if dataset_path and os.path.exists(dataset_path):
        samples = load_dataset(dataset_path)
    else:
        # 无指定文件：落一份内置示例到 data/ 便于复用
        if dataset_path:
            samples = sample_dataset()
        else:
            samples = sample_dataset()
    if category:
        samples = [s for s in samples if s.get("category") == category]
    if limit:
        samples = samples[:limit]
    if not samples:
        logger.warning("[eval]没有可评估的样本")
        return {"total": 0}

    logger.info(f"[eval]开始评估 {len(samples)} 条样本...")
    results = []
    em_scores = []
    judge_pass = 0

    for idx, s in enumerate(samples, 1):
        q = s.get("query", "")
        ref = s.get("reference", "")
        logger.info(f"[eval][{idx}/{len(samples)}] 问题：{q}")
        t0 = time.time()
        try:
            answer = _answer_agent(q)
        except Exception as e:
            logger.error(f"[eval]第{idx}条执行失败：{str(e)[:200]}")
            answer = f"[执行错误]{e}"
        cost = time.time() - t0

        em = exact_match_score(answer, ref) if ref else 0.0
        judge = llm_judge_score(q, answer, ref) if ref else "UNSURE"
        em_scores.append(em)
        if judge == "PASS":
            judge_pass += 1

        results.append({
            "query": q, "reference": ref, "answer": answer,
            "exact_match": round(em, 3), "judge": judge, "cost_s": round(cost, 1),
        })
        logger.info(f"[eval]  em={em:.2f} judge={judge} 耗时{cost:.1f}s")

    n = len(results)
    summary = {
        "total": n,
        "avg_exact_match": round(statistics.mean(em_scores), 3) if em_scores else 0,
        "judge_pass_rate": round(judge_pass / n, 3) if n else 0,
    }
    logger.info(f"[eval]汇总：{summary}")
    return {"summary": summary, "results": results}


def _fmt_report(report: dict) -> str:
    """把结果格式化为易读文本"""
    lines = []
    s = report.get("summary", {})
    lines.append("=" * 60)
    lines.append(f"评估完成：共 {s.get('total', 0)} 条")
    lines.append(f"exact_match 均值：{s.get('avg_exact_match', 0)}")
    lines.append(f"LLM-judge PASS 率：{s.get('judge_pass_rate', 0)}")
    lines.append("=" * 60)
    for r in report.get("results", []):
        lines.append(f"[{r['judge']}] em={r['exact_match']}  {r['query']}")
        lines.append(f"    回答：{(r['answer'] or '')[:120]}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="离线评估 Agent")
    parser.add_argument("--dataset", default=None, help="JSONL 数据集路径")
    parser.add_argument("--category", default=None, help="只评某分类")
    parser.add_argument("--limit", type=int, default=None, help="只评前 N 条")
    args = parser.parse_args()

    # 无数据集时先落一份内置示例，方便复用
    if not args.dataset:
        save_dataset(sample_dataset(), os.path.join("data", "eval_dataset.jsonl"))
        args.dataset = os.path.join("data", "eval_dataset.jsonl")

    report = run_evaluation(args.dataset, args.category, args.limit)
    print(_fmt_report(report))

    # 写结果到 data/eval_report_<ts>.txt
    os.makedirs(os.path.join("data"), exist_ok=True)
    out = os.path.join("data", f"eval_report_{int(time.time())}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(_fmt_report(report))
    print(f"\n报告已保存：{out}")


if __name__ == '__main__':
    main()
