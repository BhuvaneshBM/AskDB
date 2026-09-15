"""Small dataclasses passed between stages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass
class Table:
    name: str
    columns: list[Column]
    foreign_keys: list[str] = field(default_factory=list)
    sample_rows: list[tuple] = field(default_factory=list)


@dataclass
class Result:
    """The outcome of one question."""

    question: str
    db_id: str
    sql: str | None = None
    rows: list[tuple] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    error: str | None = None
    blocked: bool = False          # refused by the safety validator
    repairs: int = 0
    latency_ms: int = 0

    @property
    def executable(self) -> bool:
        return self.sql is not None and self.error is None and not self.blocked
