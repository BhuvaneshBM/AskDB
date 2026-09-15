"""Every setting. One place."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

# Reads .env into the process environment. Must happen before any
# os.environ.get() below, and before any other project module runs --
# this is why config.py is imported first in the dependency map (§26.1).
# override=True: .env is the source of truth for this project's settings,
# not whatever a stray `$env:` in the current shell session happens to hold.
load_dotenv(ROOT / ".env", override=True)

CHROMA_DIR = Path(os.environ.get("CHROMA_DIR", ROOT / "data" / "chroma"))
RESULTS_DB = Path(os.environ.get("RESULTS_DB", ROOT / "data" / "eval_results.sqlite"))
SPIDER_DIR = Path(os.environ.get("SPIDER_DIR", ROOT / "data" / "spider"))
REPORTS_DIR = ROOT / "reports"

# --- embedding -------------------------------------------------------------
# In-process, ~5 ms, no key, no network. A hosted embedding API would add a
# second failure domain to decide which of 20 tables to look at.
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

# --- retrieval -------------------------------------------------------------
# How many tables go into the prompt. Too few and the answer needs a table the
# model never saw; too many and the schema buries the question. One of the four
# experiments.
TOP_K_TABLES = int(os.environ.get("TOP_K_TABLES", "4"))

# Three sample rows per table. This is what tells the model that Country holds
# 'Netherlands' and not 'NL' -- the cheapest accuracy win in text-to-SQL, and
# the one most tutorials leave out.
INCLUDE_SAMPLE_ROWS = os.environ.get("INCLUDE_SAMPLE_ROWS", "1") == "1"
N_SAMPLE_ROWS = 3

# --- repair loop -----------------------------------------------------------
# Bounded. Unbounded repair turns one hard question into an unbounded number of
# paid LLM calls, and the model rarely recovers after two failures anyway.
MAX_REPAIRS = int(os.environ.get("MAX_REPAIRS", "2"))

# --- execution safety ------------------------------------------------------
# `SELECT * FROM a, b, c` is a cross join that never returns. Not malicious,
# just wrong -- and without a timeout it hangs the benchmark at question 43.
QUERY_TIMEOUT_S = float(os.environ.get("QUERY_TIMEOUT_S", "10"))
MAX_ROWS = 200

# --- generation ------------------------------------------------------------
# "mock" | "groq" | "ollama" -- see get_generator() in generate.py (§18).
GENERATOR = os.environ.get("GENERATOR", "mock")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
# Local, offline path via Ollama's OpenAI-compatible endpoint. No key, no
# rate limit -- but the model has to already be pulled (`ollama pull
# qwen2.5-coder:7b`) and `ollama serve` has to be running, or every call
# fails to connect.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
GENERATION_TIMEOUT_S = 60.0

SEED = 42
