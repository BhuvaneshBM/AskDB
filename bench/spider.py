"""Download Spider and load its questions.

Spider: 10,181 questions over 200 databases in 138 domains, each with the
correct SQL written by hand. Using a public benchmark rather than questions you
wrote yourself is the whole reason the accuracy number means anything -- you did
not choose the questions, so you cannot have chosen easy ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from askdb.config import SEED, SPIDER_DIR


@dataclass(frozen=True)
class Example:
    db_id: str
    question: str
    gold_sql: str


def download(target: Path = SPIDER_DIR) -> Path:
    """Pull the dataset repo, which ships the SQLite databases alongside the
    questions. ~100 MB, once."""
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    if (target / "database").is_dir():
        print(f"already present at {target}")
        return target

    print("downloading Spider (~100 MB) ...")
    snapshot_download(repo_id="xlangai/spider", repo_type="dataset",
                      local_dir=str(target))

    # Some mirrors ship the databases as a zip alongside the JSON.
    for z in target.glob("*.zip"):
        import zipfile
        print(f"  unpacking {z.name}")
        with zipfile.ZipFile(z) as f:
            f.extractall(target)

    if not (target / "database").is_dir():
        raise SystemExit(
            f"no `database/` folder under {target}.\n"
            "Download Spider manually from https://yale-lily.github.io/spider "
            f"and unzip so that {target}/database/<db_id>/<db_id>.sqlite exists.")
    return target


def load_dev(limit: int | None = None, seed: int = SEED) -> list[Example]:
    """The dev split -- 1,034 questions. The test split is held out by the
    benchmark's authors and has no public labels, so dev is what everyone
    reports on."""
    path = SPIDER_DIR / "dev.json"
    if not path.exists():
        raise SystemExit(f"{path} not found -- run `uv run python -m bench.spider` first")

    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = [Example(db_id=r["db_id"], question=r["question"], gold_sql=r["query"])
            for r in raw]

    if limit is not None and limit < len(rows):
        import random
        # Sampled, not sliced. dev.json is grouped by database, so the first N
        # rows would all come from two or three databases and the score would be
        # a property of those, not of the system.
        random.Random(seed).shuffle(rows)
        rows = rows[:limit]
    return rows


if __name__ == "__main__":
    p = download()
    print(f"ready at {p}")
    print(f"{len(load_dev())} dev questions")
