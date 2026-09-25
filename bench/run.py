"""The benchmark. Runs configurations over Spider, scores them, logs to MLflow.

    uv run python -m bench.run --limit 200            # all configs, 200 questions
    uv run python -m bench.run --only baseline
"""

from __future__ import annotations

import argparse
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import mlflow

from askdb import db, index
from askdb.config import REPORTS_DIR
from askdb.execute import is_ordered, rows_match, run
from askdb.graph import ask
from askdb.schema import list_databases
from bench.spider import load_dev


@dataclass(frozen=True)
class Config:
    name: str
    top_k: int = 4
    use_retrieval: bool = True
    include_samples: bool = True
    max_repairs: int = 2


# One-at-a-time from a baseline, not a cross product. The marginal effect of each
# knob is what you can put in a sentence; "config 7 won" is not.
GRID = [
    Config("baseline"),
    Config("no-samples", include_samples=False),      # what do 3 rows buy?
    Config("no-repair", max_repairs=0),               # what does the loop buy?
    Config("no-retrieval", use_retrieval=False),      # does retrieval beat all-tables?
    Config("topk-2", top_k=2),
    Config("topk-8", top_k=8),
]


def score_one(ex, cfg: Config, db_path: Path) -> dict:
    r = ask(ex.question, ex.db_id, str(db_path), top_k=cfg.top_k,
            use_retrieval=cfg.use_retrieval, include_samples=cfg.include_samples,
            max_repairs=cfg.max_repairs)

    correct = False
    if r.executable:
        gold_rows, _, gold_err = run(db_path, ex.gold_sql)
        # A gold query that will not run is a dataset problem, not a model
        # failure. Scoring it as wrong would penalise you for Spider's bugs.
        if gold_err is None:
            correct = rows_match(gold_rows, r.rows, is_ordered(ex.gold_sql))

    return {"db_id": ex.db_id, "question": ex.question, "gold_sql": ex.gold_sql,
            "predicted_sql": r.sql, "correct": correct, "executable": r.executable,
            "blocked": r.blocked, "repairs": r.repairs, "error": r.error,
            "latency_ms": r.latency_ms}


def aggregate(rows: list[dict]) -> dict[str, float]:
    n = max(len(rows), 1)
    repaired_ok = [r for r in rows if r["repairs"] > 0 and r["correct"]]
    return {
        "accuracy": sum(r["correct"] for r in rows) / n,
        "executable_rate": sum(r["executable"] for r in rows) / n,
        "blocked_rate": sum(r["blocked"] for r in rows) / n,
        # The number that justifies LangGraph. If it is ~0, say so.
        "rescued_by_repair": len(repaired_ok) / n,
        "mean_repairs": sum(r["repairs"] for r in rows) / n,
        "p50_latency_ms": sorted(r["latency_ms"] for r in rows)[len(rows) // 2],
    }


def run_config(cfg: Config, examples, dbs) -> dict:
    run_id = f"{cfg.name}-{uuid.uuid4().hex[:8]}"
    with mlflow.start_run(run_name=cfg.name):
        mlflow.log_params({**asdict(cfg), "n_questions": len(examples)})
        rows = []
        for i, ex in enumerate(examples, 1):
            if ex.db_id not in dbs:
                continue
            row = score_one(ex, cfg, dbs[ex.db_id])
            rows.append(row)
            # Autocommit (§14), and no cursor context manager needed --
            # sqlite3.Connection.execute() is a direct shortcut.
            db.conn().execute(
                """INSERT INTO eval_results
                   (run_id, config_name, db_id, question, gold_sql,
                    predicted_sql, correct, executable, blocked, repairs,
                    error, latency_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, cfg.name, row["db_id"], row["question"],
                 row["gold_sql"], row["predicted_sql"], row["correct"],
                 row["executable"], row["blocked"], row["repairs"],
                 row["error"], row["latency_ms"]))
            if i % 50 == 0:
                print(f"    {i}/{len(examples)}")

        agg = aggregate(rows)
        mlflow.log_metrics(agg)
        print(f"    accuracy={agg['accuracy']:.3f}  "
              f"executable={agg['executable_rate']:.3f}  "
              f"rescued={agg['rescued_by_repair']:.3f}")
        return {"name": cfg.name, **agg}


def comparison_table(results: list[dict]) -> str:
    # Plain ASCII, not "Accuracy ↑" -- Windows' default console codepage
    # (cp1252) can't encode U+2191 and print() crashes on it mid-run, right
    # after the expensive part is done. The arrow was decoration; "(higher
    # better)" says the same thing without depending on the terminal's encoding.
    lines = ["| Config | Accuracy (higher better) | Executable (higher better) | Rescued by repair | Blocked | p50 ms |",
             "|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: -x["accuracy"]):
        lines.append(f"| {r['name']} | {r['accuracy']:.3f} | {r['executable_rate']:.3f} "
                     f"| {r['rescued_by_repair']:.3f} | {r['blocked_rate']:.3f} "
                     f"| {r['p50_latency_ms']:.0f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(prog="bench.run")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--only", default=None, help="comma-separated config names")
    a = ap.parse_args()

    mlflow.set_experiment("askdb")
    examples = load_dev(limit=a.limit)
    dbs = list_databases(Path(__file__).resolve().parents[1] / "data" / "spider")
    if not dbs:
        raise SystemExit("no databases -- run `uv run python -m bench.spider` first")
    index.load_model()

    grid = ([c for c in GRID if c.name in a.only.split(",")] if a.only else GRID)
    results = [run_config(c, examples, dbs) for c in grid
               if (print(f"\n=== {c.name} ===") or True)]

    table = comparison_table(results)
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "comparison.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)
    print(f"\nwrote {REPORTS_DIR}/comparison.md")


if __name__ == "__main__":
    main()
