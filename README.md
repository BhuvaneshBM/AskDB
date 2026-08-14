# AskDB — Natural Language to SQL

[![python](https://img.shields.io/badge/python-3.11%2B-blue)](#running-it)
[![tests](https://img.shields.io/badge/tests-40%20passing-brightgreen)](#tests)
[![benchmark](https://img.shields.io/badge/benchmark-Spider-orange)](#why-this-is-measurable)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](#license)

Ask a database a question in English. It writes the SQL, runs it, shows you the answer — and when
the SQL is wrong, it reads the database's error message and fixes it.

> **77.0% execution accuracy on the Spider benchmark** (top-8 retrieval) · **2.5% of questions
> needed a repair** · **~2s median latency**

```
$ uv run python -m askdb.cli ask concert_singer "how many singers are from the Netherlands?"

SQL:
  SELECT COUNT(*) FROM singer WHERE Country = 'Netherlands'

COUNT(*)
------------------------------------------------------------
1

1 row(s) in 812 ms
```

---

## Why this is measurable

Most LLM projects report a number you have to take on trust. This one doesn't: **a query either
returns the right rows or it doesn't.**

Scored on **Spider** — 10,181 questions across 200 databases, each with hand-written correct SQL.
The metric is *execution accuracy*: run the gold query, run mine, compare the rows. Not string
comparison, because these are the same query written twice:

```sql
SELECT name FROM singer WHERE age > 30
SELECT T1.name FROM singer AS T1 WHERE T1.age > 30
```

Order matters only when the gold query has `ORDER BY`. Otherwise rows are compared as multisets.

## Results

*200 questions, Groq generator, `uv run python -m bench.run --limit 200`.*

| Config | Accuracy (higher better) | Executable (higher better) | Rescued by repair | Blocked | p50 ms |
|---|---|---|---|---|---|
| topk-8 | 0.770 | 0.995 | 0.005 | 0.000 | 1985 |
| baseline | 0.755 | 0.985 | 0.000 | 0.000 | 1931 |
| no-samples | XX | XX | XX | XX | XX |
| no-repair | XX | XX | XX | XX | XX |
| no-retrieval | XX | XX | XX | XX | XX |
| topk-2 | XX | XX | XX | XX | XX |

*Remaining rows not yet run — `uv run python -m bench.run --limit 200` runs the full grid.*

**"Rescued by repair" is the number that justifies the error loop, and on this run it's close to
zero.** Not because repair is broken — it's wired correctly and does fire — but because baseline
generation is already valid SQL 98.5% of the time. Only 5 of 200 questions ever produced an error
worth repairing, so the loop rarely gets a chance to do anything. Of those 5: 2 stayed genuinely
wrong (a table the model needed wasn't in the retrieved schema), 1 was a plain hallucinated column
name despite the correct one being right there in the prompt, and 2 turned into *valid but
semantically wrong* queries after repair — which the loop can't catch, since it only checks whether
SQL executes, not whether the answer is right.

### The finding

Raising retrieval from top-4 to top-8 tables bought **+1.5 accuracy points** (0.755 → 0.770) by
recovering questions where the one table the question was actually about — `countries`, in a
database dominated by `car_makers`/`car_names`/`model_list` — ranked just outside the cutoff. That's
a real, measured effect, but it's close to the noise floor: re-running the identical baseline config
twice produced 0.750 and then 0.755 on the same 200 questions at `temperature=0.0`, which is Groq
API-side nondeterminism, not a bug in this code. Deltas smaller than ~1 point on a 200-question run
aren't distinguishable from that noise without repeated runs.

---

## How it works

```
"how many singers are from the Netherlands?"
        │
   1. RETRIEVE   embed the question, find the top-k most relevant TABLES
                 (each doc = columns + types + foreign keys + 3 sample rows)
        │
   2. GENERATE   LLM writes SQL from those tables only
        │
   3. VALIDATE   single SELECT? no write verbs? no stacked statements?
   4. EXECUTE    read-only connection, 10s timeout
        │
        ├── rows ──► done
        └── error ─► 5. REPAIR: show the model its SQL and the error,
                        ask for a fix (max 2) ──► back to EXECUTE
```

Retrieval runs against a local **Chroma** index; everything else is plain SQLite. No server process
to start before any of this works.

### Four decisions worth defending

**Retrieval is over tables, not chunks.** A table is the natural unit — splitting a schema mid-column
-list produces a fragment describing nothing. So chunk size, the parameter every RAG tutorial agonises
over, doesn't exist in this project.

**Sample rows go in the prompt.** Three per table. It's what tells the model that `Country` holds
`'Netherlands'` and not `'NL'`. Ablated as one of the experiments, because it's the cheapest accuracy
win in text-to-SQL and the one most people leave out.

**The database's own error is the repair signal.** `no such column: revenue` is precise, free, and
generated by the only authority that matters — better than a second model grading the first. Worth
being honest about its limit, too: repair only knows a query is *invalid*, never that it's
*semantically wrong* — see the two `repairs=1, error=None` rows above.

**Read-only at the connection, not just in the parser.** Validation is a regex and regexes have holes
— one shipped here, in fact: an earlier version of `_WRITE_VERBS` blocked the SQL string function
`REPLACE(...)` because it matched the same keyword used to guard against the `REPLACE INTO` write
statement, even though that statement was already caught by the "must start with SELECT or WITH"
check. `file:db.sqlite?mode=ro` makes the database itself refuse writes regardless, so the hole in
the validator was a false-positive, not a data-loss risk — which is the whole point of layering it
under the read-only connection rather than relying on it alone.

## Safety

The model generates executable statements from untrusted text. Three layers:

| Layer | Stops |
|---|---|
| **Read-only connection** | Everything. The database refuses writes regardless of what got through |
| **Statement validation** | Write verbs, stacked statements (`SELECT 1; DROP TABLE t`), writes hidden behind comments |
| **Query timeout** | `SELECT * FROM a, b, c` — a cross join that never returns. Not malicious, just wrong |

`tests/test_execute.py` covers all three, including `/* SELECT */ DROP TABLE users` and
`REPLACE(col, 'a', 'b')` inside a legal `SELECT` (regression test for the false-positive above).

---

## Running it

```bash
uv sync
cp .env.example .env                    # nothing to provision -- Chroma and SQLite are just files

uv run python -m bench.spider           # download Spider (~100 MB, once)
uv run python -m askdb.cli index        # embed every database's tables
uv run python -m askdb.cli ask concert_singer "how many singers are there?"
```

No API key needed — `GENERATOR=mock` runs the whole pipeline. Set `GENERATOR=groq` and a free key
for real accuracy, hosted. For a fully local, offline path with no key and no rate limit, install
[Ollama](https://ollama.com), pull a model (`ollama pull qwen2.5-coder:7b`), and set
`GENERATOR=ollama` instead — expect lower accuracy than Groq's 70B model, since local models here are
realistically 7-14B.

### Point it at your own database

```bash
uv run python -m askdb.cli ask --sqlite ~/my_app.sqlite "how many users signed up last month?"
```

### The benchmark

```bash
uv run python -m bench.run --limit 200  # all 6 configs
uv run mlflow ui                        # localhost:5000
```

### Ask it about its own results

The project answers questions about SQLite databases. Its own benchmark results live in one too, so
this reuses the exact same query path as every other database it can be pointed at:

```bash
uv run python -m askdb.cli results "which database did I score worst on?"
```

---

## Tests

```bash
uv run pytest -q   # 40 tests, nothing running, no network needed
```

| File | Tests | Guards |
|---|---|---|
| `test_execute.py` | 28 | Safety and scoring — the two things that make the number real |
| `test_schema.py` | 7 | Foreign keys, sample rows, truncation |
| `test_generate.py` | 5 | Fence stripping, the mock floor, the repair prompt |

Four are load-bearing: writes hidden behind comments, the read-only connection working *without* the
validator, multiset (not set) row comparison, and errors returning as data rather than raising.

## Limitations

- **SQLite only.** Spider is SQLite, so dialect handling is untested elsewhere. Postgres would need a
  different validator — its `information_schema` and quoting rules differ.
- **Execution accuracy can be generous.** A wrong query that happens to return the same rows on this
  data scores as correct. Spider's authors acknowledge this; it's the standard metric anyway. One
  observed case: filtering an integer foreign-key column against a string literal returned zero rows
  and executed without error — silently wrong, not caught by anything short of checking the answer.
- **Retrieval is evaluated indirectly.** I measure end accuracy, not whether the right tables were
  retrieved. A separate retrieval-recall metric would isolate that — `top-4 → top-8` recovering
  specific known-missing-table cases is the closest evidence so far, not a direct measurement.
- **Repair only catches invalid SQL, not wrong SQL.** It fixes queries that fail to execute; a query
  that runs cleanly but answers the wrong question gets no signal to correct it.
- **Groq generation isn't perfectly reproducible at `temperature=0.0`.** Two identical runs of the
  same 200 questions produced accuracy figures 0.5 points apart. Small deltas between configs should
  be read with that noise floor in mind.
- **The dev split only.** Spider's test split is held out with no public labels.
- **One model.** Whether these conclusions hold for a smaller or larger model is untested.
- **No multi-turn.** *"and what about 2011?"* needs conversation state.
- **Single writer.** Chroma and the results SQLite file are embedded, not a server — fine for a CLI
  used one question at a time, not a design for concurrent users.

## What I'd do next

1. **Retrieval recall as its own metric** — of the tables the gold query uses, how many were retrieved
2. **A minimal-join hint in the prompt** — one observed failure joined two tables where the answer's
   columns lived on a single table; a line telling the model to prefer the fewest joins is a cheap
   thing to test before assuming it's a model-size problem
3. **Postgres dialect support**, which means a second validator and schema reader
4. **Self-consistency** — generate 3 candidates, run all, keep the answer the majority agree on
5. **BIRD** — harder than Spider, 95 large databases, where retrieval should matter much more
6. **Column-level retrieval** for wide tables where the table fits but 200 columns don't

## License

MIT. Spider is CC BY-SA 4.0 and downloaded at runtime, not redistributed.