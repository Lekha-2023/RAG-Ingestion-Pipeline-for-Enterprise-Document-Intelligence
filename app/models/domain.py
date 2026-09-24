from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Element:
    element_id: str
    text: str
    element_type: str
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Table:
    table_id: str
    rows: list[list[str]]
    page: int | None = None
    caption: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    elements: list[Element]
    tables: list[Table]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    tenant_id: str
    collection_id: str
    text: str
    page: int | None
    chunk_index: int
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    tenant_id: str
    status: str
    chunk_count: int
    reused_count: int
    indexed_count: int
    skipped_count: int
    parser: str
