"""Extract every source file from DESIGN.md into the working tree.

    uv run scripts/scaffold.py            # write files
    uv run scripts/scaffold.py --check    # report differences, write nothing
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "DESIGN.md"

HEADING = re.compile(r"^#{2,4}\s+(?:\d+\.\s*)?`([^`]+)`(?:\s+[-—].*)?\s*$", re.M)

SUFFIXES = {".py", ".txt", ".toml", ".sql", ".yml", ".yaml", ".json", ".sh",
            ".md", ".example", ".gitignore"}
NAMED = {"Dockerfile", ".gitignore", ".env.example"}

# Match the fence LANGUAGE to the file type rather than taking the first block:
# some sections show a usage example before the code.
LANGS = {
    ".py": {"python", "py"}, ".txt": {"text", "txt"}, ".toml": {"toml"},
    ".sql": {"sql"}, ".yml": {"yaml", "yml"}, ".yaml": {"yaml", "yml"},
    ".json": {"json"}, ".sh": {"bash", "sh"}, ".md": {"markdown", "md"},
    ".example": {"bash", "sh"},
}
NAMED_LANGS = {"Dockerfile": {"dockerfile"}, ".gitignore": {"gitignore"},
               ".env.example": {"bash", "sh"}}

EMPTY_FILES = ["askdb/__init__.py", "bench/__init__.py", "reports/.gitkeep"]


def is_file_heading(name: str) -> bool:
    return name in NAMED or Path(name).suffix in SUFFIXES


def extract(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        m = HEADING.match(lines[i])
        if not m or not is_file_heading(m.group(1)):
            i += 1
            continue
        path = m.group(1)
        want = NAMED_LANGS.get(path) or LANGS.get(Path(path).suffix) or set()

        blocks: list[tuple[str, str]] = []
        j = i + 1
        while j < len(lines):
            if HEADING.match(lines[j]):
                break
            if not lines[j].startswith("```"):
                j += 1
                continue
            fence = "````" if lines[j].startswith("````") else "```"
            lang = lines[j][len(fence):].strip().lower()
            k = j + 1
            body: list[str] = []
            while k < len(lines) and not lines[k].startswith(fence):
                body.append(lines[k])
                k += 1
            blocks.append((lang, chr(10).join(body).rstrip(chr(10)) + chr(10)))
            j = k + 1
            if lang in want:
                break

        if blocks:
            out.append((path, next((b for lang, b in blocks if lang in want),
                                   blocks[0][1])))
        i = j
    return out


def verify(path: str, body: str) -> str | None:
    try:
        if path.endswith(".py"):
            ast.parse(body, filename=path)
        elif path.endswith(".json"):
            json.loads(body)
    except (SyntaxError, ValueError) as e:
        return f"{type(e).__name__}: {e}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not DOC.exists():
        print(f"cannot find {DOC}", file=sys.stderr)
        return 1

    files = extract(DOC.read_text(encoding="utf-8"))
    if not files:
        print("no file blocks found -- has the heading format changed?", file=sys.stderr)
        return 1

    written = changed = same = 0
    problems: list[str] = []

    for path, body in files:
        err = verify(path, body)
        if err:
            problems.append(f"{path}: {err}")
            continue
        dest = ROOT / path
        existing = dest.read_text(encoding="utf-8") if dest.exists() else None
        if existing == body:
            same += 1
            continue
        if args.check:
            print(f"  {'DIFFERS' if existing is not None else 'NEW    '}  {path}")
            changed += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
        print(f"  {'updated' if existing is not None else 'wrote  '}  {path}")
        written += 1

    if not args.check:
        for rel in EMPTY_FILES:
            p = ROOT / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.touch()
                print(f"  wrote    {rel}")

    print(f"\n{len(files)} file blocks | {written} written | {same} unchanged"
          + (f" | {changed} would change" if args.check else ""))
    if problems:
        print("\nPROBLEMS -- these were NOT written:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    if not args.check:
        print("\nnext:  uv sync && cp .env.example .env && uv run python -m bench.spider")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
