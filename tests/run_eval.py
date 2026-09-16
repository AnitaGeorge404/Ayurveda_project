"""
Computes the evaluation metrics requested by the spec against
tests/test_data/questions.json, using the FakeGraphStore (no live Neo4j
needed -- this measures the retrieval/evidence/grounding logic itself).

Run: python tests/run_eval.py
Writes: tests/eval_report.json and prints a human-readable summary.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph_store import FakeGraphStore
from app.normalization import EntityIndex
from app.pipeline import answer_question

ROOT = Path(__file__).resolve().parent.parent


def main():
    with open(ROOT / "tests" / "test_data" / "questions.json", encoding="utf-8") as f:
        cases = json.load(f)

    store = FakeGraphStore()
    index = EntityIndex(store)

    results = []
    latencies = []
    for case in cases:
        t0 = time.perf_counter()
        resp = answer_question(store, index, case["question"])
        latencies.append(time.perf_counter() - t0)
        correct = resp.status.value == case["expected_status"]
        results.append({
            "question": case["question"],
            "category": case["category"],
            "expected_status": case["expected_status"],
            "actual_status": resp.status.value,
            "correct": correct,
            "answer": resp.answer,
        })

    total = len(results)
    correct = sum(r["correct"] for r in results)

    should_refuse = [r for r in results if r["expected_status"] != "ANSWERABLE"]
    correctly_refused = [r for r in should_refuse if r["actual_status"] == r["expected_status"]]
    abstention_accuracy = len(correctly_refused) / len(should_refuse) if should_refuse else None

    should_answer = [r for r in results if r["expected_status"] == "ANSWERABLE"]
    correctly_answered = [r for r in should_answer if r["actual_status"] == "ANSWERABLE"]
    answer_accuracy = len(correctly_answered) / len(should_answer) if should_answer else None

    # Hallucination rate proxy: an ANSWERABLE response whose text is not
    # grounded would be caught by app.grounding before reaching the user, so
    # a true positive-and-ungrounded answer should never appear here. We
    # measure the closest observable proxy: ANSWERABLE responses returned for
    # questions expected to be refused (a wrong-but-not-necessarily-fabricated
    # answer) -- 0 in a correct system.
    false_answers = [r for r in should_refuse if r["actual_status"] == "ANSWERABLE"]
    hallucination_rate = len(false_answers) / len(should_refuse) if should_refuse else 0.0

    report = {
        "total_questions": total,
        "answer_accuracy_overall": correct / total,
        "answer_accuracy_on_answerable": answer_accuracy,
        "abstention_accuracy_on_should_refuse": abstention_accuracy,
        "hallucination_rate_wrongly_answered": hallucination_rate,
        "avg_latency_seconds": sum(latencies) / len(latencies),
        "p95_latency_seconds": sorted(latencies)[int(0.95 * len(latencies)) - 1],
        "by_category": {},
        "failures": [r for r in results if not r["correct"]],
    }

    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], {"total": 0, "correct": 0})
        by_cat[r["category"]]["total"] += 1
        by_cat[r["category"]]["correct"] += int(r["correct"])
    report["by_category"] = {
        cat: {"total": v["total"], "correct": v["correct"], "accuracy": v["correct"] / v["total"]}
        for cat, v in by_cat.items()
    }

    out_path = ROOT / "tests" / "eval_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Total questions: {total}")
    print(f"Overall accuracy: {report['answer_accuracy_overall']:.2%}")
    print(f"Answer accuracy (on answerable questions): {answer_accuracy:.2%}" if answer_accuracy is not None else "n/a")
    print(f"Abstention accuracy (correctly refused): {abstention_accuracy:.2%}" if abstention_accuracy is not None else "n/a")
    print(f"Hallucination rate (wrongly answered when should refuse): {hallucination_rate:.2%}")
    print(f"Avg latency: {report['avg_latency_seconds']*1000:.2f} ms")
    print("\nBy category:")
    for cat, v in report["by_category"].items():
        print(f"  {cat}: {v['correct']}/{v['total']} ({v['accuracy']:.0%})")
    if report["failures"]:
        print("\nFailures:")
        for f in report["failures"]:
            print(f"  - {f['question']!r}: expected {f['expected_status']}, got {f['actual_status']}")
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
