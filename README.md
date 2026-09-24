# Enterprise RAG Ingestion Pipeline

Production-oriented Python reference implementation for the take-home assignment.

## What is included

- Async `ingest(...)` service matching the requested contract.
- Azure Document Intelligence parser adapter.
- **Docling parser adapter (bonus).**
- Canonical document model shared by both adapters.
- Structure-aware prose chunking with overlap.
- Table-aware chunking that preserves rows and repeats headers when a table spans chunks.
- Page/provenance metadata and SHA-256 content hashes.
- Idempotent re-ingestion and stale-chunk removal.
- Tenant-scoped vector-store boundary.
- Pluggable embedding and vector-store interfaces.
- Deterministic offline embedding + in-memory vector store for credential-free execution.
- Unit tests covering tables, idempotency, updates, tenant isolation, both adapters, and long-table chunking.
- Docker/local run path.

## Why parser JSON is accepted locally

The assignment provides parser output examples but does not require external credentials. To keep the submission deterministic, `file_bytes` contains the supplied parser JSON shape in the local demo. In production, the parser-client layer would turn the original PDF/DOCX/image into that JSON before calling the same adapter boundary.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
python run.py
```

Open `http://localhost:8000/docs`.

## Run with Docker

```bash
docker compose up --build
```

## Ingestion contract

The core service exposes:

```python
async def ingest(
    file_bytes: bytes,
    filename: str,
    document_id: str,
    tenant_id: str,
    collection_id: str,
    document_type: str | None,
    tags: list[str],
    metadata: dict,
) -> IngestResult
```

The HTTP endpoint accepts the same fields with `file_bytes` represented as base64 for transport.

## Architecture

See [`DESIGN.md`](DESIGN.md) for architecture, parser abstraction, table handling, scale strategy, tenant isolation, security, trade-offs, and production next steps.
