"""
Picks the relevance cutoff from an eval report instead of by hand (Fase 14.2/14.3).

    .venv/Scripts/python.exe -m evals.rag.calibrate evals/reports/<stamp>-rag-current-....json

Run the eval with the gate wide open first (e.g. --option min_rerank_score=-100
or --option max_distance=2), so every candidate carries its score; then this
replays the gate at each threshold over the recorded candidates and prints
hit@5 (answers found) against no_answer_accuracy (questions with no answer in
the corpus correctly left empty). The chosen value maximizes their harmonic
mean — both failure modes cost: a missed answer sends the user to a ticket, an
irrelevant passage is what a model confidently builds a wrong answer on.

Approximation: identifier matches (which always pass the real gate) are not
marked in the report, so a threshold is judged a little pessimistically.
"""
import json
import sys

from .metrics import Hit, hit_at


def sweep(report: dict, top_k: int = 5) -> list[dict]:
    rows = []
    scores = sorted({h["score"] for r in report["results"] for h in r["candidates"] if h["score"] is not None})
    for threshold in scores[:: max(1, len(scores) // 200)] + [scores[-1] + 1e-6]:
        found, answerable, empty_ok, unanswerable = 0, 0, 0, 0
        for r in report["results"]:
            kept = [Hit(**h) for h in r["candidates"] if h["score"] is not None and h["score"] >= threshold][:top_k]
            if r["targets"]:
                answerable += 1
                found += hit_at(kept, r["targets"], top_k)
            else:
                unanswerable += 1
                empty_ok += not kept
        recall = found / answerable if answerable else 0.0
        rejection = empty_ok / unanswerable if unanswerable else 0.0
        balance = 2 * recall * rejection / (recall + rejection) if recall + rejection else 0.0
        rows.append({"threshold": round(threshold, 4), "hit@5": round(recall, 3),
                     "no_answer_accuracy": round(rejection, 3), "balance": round(balance, 3)})
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    report = json.load(open(sys.argv[1], encoding="utf-8"))
    rows = sweep(report)
    best = max(rows, key=lambda r: (r["balance"], r["hit@5"]))
    for row in rows:
        if row["balance"] >= best["balance"] - 0.05:
            print(row)
    print("best:", best)


if __name__ == "__main__":
    main()
