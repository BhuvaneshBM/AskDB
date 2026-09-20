"""The repair loop, as a LangGraph state machine.

WHY LANGGRAPH AND NOT A WHILE LOOP
----------------------------------
Because this has a CYCLE:

    retrieve -> generate -> execute ─┬─ ok    -> END
                                     └─ error -> repair -> execute

A chain is a DAG and cannot express that. What LangGraph adds over a hand-rolled
loop is that the transitions are declared rather than implied -- the exit
conditions live in one `decide` function instead of being spread through a body,
and adding a node does not mean re-reading the whole thing to work out when it
runs.

If this were linear, LangGraph would be ceremony and a plain function would be
better. The cycle is what justifies it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph

from . import index
from .config import INCLUDE_SAMPLE_ROWS, MAX_REPAIRS, TOP_K_TABLES
from .execute import run, validate
from .generate import get_generator
from .models import Result


class State(TypedDict, total=False):
    question: str
    db_id: str
    db_path: str
    top_k: int
    use_retrieval: bool
    include_samples: bool
    max_repairs: int

    schema_docs: list[str]
    sql: str
    rows: list
    columns: list[str]
    error: str | None
    blocked: bool
    repairs: int


def build_graph():
    gen = get_generator()

    def node_retrieve(state: State) -> State:
        if state.get("use_retrieval", True):
            docs = index.retrieve(state["db_id"], state["question"],
                                  k=state.get("top_k", TOP_K_TABLES),
                                  include_samples=state.get("include_samples", True))
        else:
            docs = index.retrieve_all(state["db_id"],
                                      include_samples=state.get("include_samples", True))
        return {"schema_docs": docs}

    def node_generate(state: State) -> State:
        return {"sql": gen.generate(state["question"], state["schema_docs"]),
                "repairs": 0}

    def node_execute(state: State) -> State:
        reason = validate(state["sql"])
        if reason:
            # A blocked statement is NOT sent to the repair loop. The model wrote
            # something dangerous, not something wrong, and asking it to try
            # again is how you end up looping on a prompt injection.
            return {"blocked": True, "error": f"blocked: {reason}",
                    "rows": [], "columns": []}
        rows, cols, err = run(Path(state["db_path"]), state["sql"])
        return {"rows": rows, "columns": cols, "error": err, "blocked": False}

    def node_repair(state: State) -> State:
        return {"sql": gen.repair(state["question"], state["schema_docs"],
                                  state["sql"], state["error"] or ""),
                "repairs": state.get("repairs", 0) + 1}

    def decide(state: State) -> Literal["repair", "done"]:
        if state.get("blocked"):
            return "done"
        if not state.get("error"):
            return "done"
        if state.get("repairs", 0) >= state.get("max_repairs", MAX_REPAIRS):
            return "done"
        return "repair"

    g = StateGraph(State)
    g.add_node("retrieve", node_retrieve)
    g.add_node("generate", node_generate)
    g.add_node("execute", node_execute)
    g.add_node("repair", node_repair)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "execute")
    g.add_conditional_edges("execute", decide, {"repair": "repair", "done": END})
    g.add_edge("repair", "execute")
    return g.compile()


_compiled = None


def ask(question: str, db_id: str, db_path: str, top_k: int = TOP_K_TABLES,
        use_retrieval: bool = True, include_samples: bool = INCLUDE_SAMPLE_ROWS,
        max_repairs: int = MAX_REPAIRS) -> Result:
    global _compiled
    if _compiled is None:
        _compiled = build_graph()

    t0 = time.perf_counter()
    state = _compiled.invoke({
        "question": question, "db_id": db_id, "db_path": db_path,
        "top_k": top_k, "use_retrieval": use_retrieval,
        "include_samples": include_samples, "max_repairs": max_repairs,
        "repairs": 0,
    })
    return Result(
        question=question, db_id=db_id, sql=state.get("sql"),
        rows=list(state.get("rows") or []), columns=list(state.get("columns") or []),
        error=state.get("error"), blocked=bool(state.get("blocked")),
        repairs=state.get("repairs", 0),
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
