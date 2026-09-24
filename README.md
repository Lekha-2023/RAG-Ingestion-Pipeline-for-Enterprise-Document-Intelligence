# Enterprise RAG Ingestion Pipeline

The main goal of the project is to take parser output from different document-processing systems, turn it into one consistent document representation, split it into useful chunks, generate embeddings, and store those chunks in a tenant-aware vector store.

I kept the implementation deliberately modular so that the parser, embedding provider, or vector store can be replaced without rewriting the rest of the pipeline.

## What this project does

The ingestion flow is:

```text
Parser output
     |
     v
Parser adapter
     |
     v
Canonical document model
     |
     v
Structure-aware chunking
     |
     v
Content hashing
     |
     v
Embeddings
     |
     v
Tenant-scoped vector store
```

The service currently supports the two parser formats required for the assessment:

- Azure Document Intelligence (ADI)
- Docling

Both adapters produce the same canonical representation, so everything after parsing is shared.

## Why I designed it this way

The main design decision was to keep parser-specific logic at the edge of the system.

Azure Document Intelligence and Docling can return document information in different shapes. Instead of letting those differences spread through the application, each parser has its own adapter.

Once the data reaches the canonical model, the rest of the pipeline works with the same structure.

That makes the system easier to test and also makes it easier to add another parser later.

## Key features

### 1. Multiple parser adapters

The repository contains separate adapters for:

- Azure Document Intelligence
- Docling

Each adapter converts its parser-specific response into the application's common `ParsedDocument` model.

### 2. Structure-aware chunking

Text and tables are handled differently.

Normal text is normalized and split into bounded chunks with overlap so that related context is not unnecessarily lost.

Tables preserve their row/column relationships. When a table needs to be split across chunks, the table header is retained so values remain meaningful when retrieved independently.

For example:

```text
Service | Your Cost
Primary Care | $20
Specialist   | $40
```

A later chunk can still retain:

```text
Service | Your Cost
Specialist | $40
```

This is important for document Q&A because a value without its column context can easily become ambiguous.

### 3. Incremental and idempotent ingestion

Each normalized chunk gets a SHA-256 content hash.

When the same content is ingested again, the hash allows the pipeline to recognize that the chunk has not changed and avoid unnecessary re-embedding.

The basic behavior is:

```text
Same content   -> reuse
Changed content -> re-embed
New content     -> add
Removed content -> remove stale record
```

This helps reduce unnecessary embedding work and prevents duplicate/stale vector records.

### 4. Tenant isolation

Tenant ID is carried through the ingestion flow and stored with the indexed records.

The vector-store abstraction checks the tenant when records are retrieved, so content from one tenant is not returned for another tenant.

For a production deployment, I would enforce the same tenant filtering directly in the persistent vector database as an additional boundary.

### 5. Pluggable embeddings and vector storage

The embedding and vector-store components are kept behind interfaces.

The take-home uses deterministic local embeddings and an in-memory vector store so the project can be run without external credentials or infrastructure.

The same ingestion service can later be connected to a production embedding API/model and a persistent vector database such as pgvector or Qdrant.

### 6. FastAPI service

The application exposes the ingestion pipeline through a REST API.

Health check:

```text
GET /health
```

Ingestion:

```text
POST /ingest
```

The `/ingest` endpoint accepts the parser JSON as base64-encoded bytes together with document, tenant, collection, type, tags, and metadata.

## Project structure

```text
rag_ingestion/
├── app/
│   ├── adapters/
│   │   ├── adi.py
│   │   ├── base.py
│   │   └── docling.py
│   ├── models/
│   │   └── domain.py
│   ├── services/
│   │   ├── embedding.py
│   │   ├── ingestion.py
│   │   └── vector_store.py
│   └── main.py
├── tests/
│   └── test_ingestion.py
├── DESIGN.md
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
├── pytest.ini
├── run.py
└── README.md
```

## Running locally

### 1. Create a virtual environment

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install the project

```powershell
python -m pip install -e ".[dev]"
```

If you are working in an environment where editable installation is not available, install the dependencies defined in `pyproject.toml` and run the application directly.

### 3. Run the tests

```powershell
python -m pytest -q
```

The test suite covers the main ingestion behaviors, including parser handling, chunking, table processing, hashing/idempotency, and tenant isolation.

### 4. Start the API

```powershell
python run.py
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Health check:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

FastAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

## Running with Docker

The project includes a Dockerfile and Docker Compose configuration.

Start the service with:

```powershell
docker compose up --build
```

The API is exposed on port `8000`.

You can verify the containerized service with:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

The same `/ingest` endpoint is available through the Dockerized API.

## Example ingestion result

A successful ingestion returns information such as:

```json
{
  "document_id": "doc-001",
  "tenant_id": "tenant-001",
  "status": "completed",
  "chunk_count": 2,
  "reused_count": 0,
  "indexed_count": 2,
  "skipped_count": 0,
  "parser": "azure_document_intelligence"
}
```

This makes it easy for a caller to understand what happened during ingestion rather than receiving only a generic success response.

## Testing the ingestion flow

For local testing, the `/ingest` endpoint accepts a JSON payload with:

```json
{
  "file_bytes_b64": "<base64 encoded parser JSON>",
  "filename": "benefit_summary.json",
  "document_id": "doc-001",
  "tenant_id": "tenant-001",
  "collection_id": "benefits",
  "document_type": "azure_document_intelligence",
  "tags": ["healthcare", "benefits"],
  "metadata": {
    "source": "assessment"
  }
}
```

The parser JSON is intentionally passed as base64-encoded bytes because that is the interface defined by the assessment. It also keeps the service independent of external parser credentials during local testing.

## Production considerations

This repository is intentionally small enough to run locally, but the main interfaces are designed with a larger production system in mind.

For a production deployment, I would move long-running ingestion work to background workers behind a durable queue.

A typical flow would look like:

```text
Upload
  |
  v
Ingestion job
  |
  v
Queue
  |
  +--> Parser workers
  |
  +--> Chunking / embedding workers
  |
  +--> Vector indexing
```

That would allow parser and embedding workloads to scale independently without making the API request wait for the entire document to finish processing.

I would also add:

- durable document and version metadata
- object storage for original documents
- batch embedding and vector upserts
- retries with exponential backoff
- dead-letter handling
- stronger idempotency controls
- metrics and tracing
- queue/backpressure monitoring
- production vector storage
- load testing for large documents and multiple tenants

More detailed architecture decisions and trade-offs are documented in [DESIGN.md](DESIGN.md).

## Security considerations

Enterprise documents can contain sensitive information, so the ingestion service should treat security as part of the design rather than as a later addition.

For production, I would enforce:

- authentication and tenant-level authorization
- file and payload validation
- encryption in transit and at rest
- secure secret management
- controlled logging that does not expose document contents
- retention and deletion policies
- auditable document/version changes
- tenant filtering at the persistence layer

## Bonus implementation

The bonus requirement was implemented by adding the Docling adapter.

The important part is that Docling does not create a second ingestion pipeline. It follows the same path:

```text
Docling
   |
   v
DoclingAdapter
   |
   v
ParsedDocument
   |
   v
Shared chunking
   |
   v
Shared hashing
   |
   v
Shared embeddings
   |
   v
Shared vector store
```

This keeps the bonus feature isolated and makes the architecture easier to extend.

## Assessment validation

The final implementation was validated with:

- unit tests
- local FastAPI execution
- Docker Compose
- `/health` endpoint
- end-to-end `/ingest` request
- parser adapter execution
- chunk creation
- embedding/indexing flow

The Dockerized ingestion flow successfully returned a completed ingestion response with the expected chunk and indexing counts.

## Design documentation

For the reasoning behind the architecture, chunking strategy, idempotency, tenant isolation, scaling approach, security considerations, and production improvements, see:

[DESIGN.md](DESIGN.md)
