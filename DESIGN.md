# Design — Enterprise RAG Ingestion Pipeline

## 1. Goal and scope

The assignment asks for a production-oriented ingestion pipeline for heterogeneous enterprise documents. The implementation exposes the requested asynchronous `ingest(...)` service contract and demonstrates the complete path:

```text
parser JSON -> parser adapter -> canonical document model -> structure-aware chunking
           -> content hash -> embeddings -> tenant-scoped vector store
```

The public service accepts the assignment's `file_bytes: bytes` contract. For this take-home, those bytes contain one of the supplied parser JSON shapes so the repository is runnable without Azure/Docling credentials. In production, the same adapter boundary would receive output from the real parser client.

## 2. Architecture

```text
                         +-------------------------+
PDF/DOCX/scanned form -> | parser client / API    |
                         +------------+------------+
                                      |
                         +------------v------------+
                         | ParserAdapter interface |
                         | ADI | Docling | future   |
                         +------------+------------+
                                      |
                            Canonical ParsedDocument
                                      |
                         +------------v------------+
                         | Structure-aware chunker  |
                         | prose + tables + pages   |
                         +------------+------------+
                                      |
                              SHA-256 content hash
                                      |
                         +------------v------------+
                         | EmbeddingProvider        |
                         +------------+------------+
                                      |
                         +------------v------------+
                         | VectorStore              |
                         | Qdrant/pgvector/etc.     |
                         +---------------------------+
```

### Why an adapter layer?

ADI and Docling represent the same source document with different JSON contracts. The adapters translate both into one canonical model (`ParsedDocument`, `Element`, `Table`). Chunking, embedding, and indexing therefore do not contain parser-specific branches. Adding a third parser only requires a new adapter and registration.

## 3. Canonical representation and provenance

Every extracted element retains its parser-derived page/provenance information. Table cells are reconstructed into row/column order before chunking. Chunk payloads include tenant ID, document ID, collection ID, page, filename, parser/schema information, tags, document version, element type, and content hash.

This makes downstream source-grounded retrieval possible and prevents a table cell from becoming detached from its neighboring header/value.

## 4. Chunking strategy

Text is normalized and split on word boundaries with a bounded overlap. Tables use a different strategy: rows are never split across chunks, and the header row is repeated when a large table spans multiple chunks. This is intentional because the assignment calls out missed/malformed tables as a high-impact failure mode.

The demo uses conservative character limits for deterministic local execution. In production I would tune chunking with a retrieval evaluation set rather than assuming one global size is optimal for every document type.

## 5. Incremental and idempotent ingestion

Each normalized chunk receives a SHA-256 content hash. Re-ingesting the same content therefore avoids a second embedding call. If the document changes, new content is embedded and hashes no longer present in the incoming version are deleted from the document's existing records.

This is an important cost and correctness boundary: unchanged chunks should not be recomputed, while removed chunks must not remain retrievable as stale evidence.

## 6. Multi-tenant isolation

Tenant ID is part of every vector payload and every document lookup. The in-memory implementation enforces tenant matching in `get_by_document`; a production vector store must enforce the equivalent tenant filter server-side on every read/write operation and never rely on a caller-provided filter alone.

## 7. Async and scale design

The assignment describes millions of documents across hundreds of tenants. The demo keeps the implementation synchronous at the parser-adapter level but exposes asynchronous service/provider boundaries so remote services can be introduced without changing the public API.

At production scale I would:

1. Persist originals in object storage and metadata/version state in a durable database.
2. Return an ingestion/job ID quickly and process work through a durable queue.
3. Scale stateless workers horizontally by tenant/document workload.
4. Batch embedding and vector upserts.
5. Cache embeddings by content hash.
6. Use idempotency keys and exponential-backoff retries.
7. Send poison documents to a dead-letter queue.
8. Emit metrics for parser failure rate, table extraction failures, embedding latency, vector upsert latency, queue depth, and per-tenant throughput.
9. Add bounded concurrency/backpressure so a large tenant cannot starve others.

## 8. Security and enterprise concerns

Document content may contain regulated or confidential information. Production implementation should:

- authenticate and authorize the tenant before ingestion;
- validate file size/type and parser payload shape;
- avoid logging document bytes or extracted sensitive text;
- encrypt originals and vector payloads at rest and in transit;
- keep secrets outside source control;
- apply retention/deletion policies;
- record parser/schema/document-version changes for auditability;
- enforce tenant filters inside the persistence layer.

## 9. Embeddings and vector store trade-off

The repository intentionally uses a deterministic local embedding implementation and an in-memory vector store. This makes the assessment reproducible with no credentials or external services. Both are behind interfaces so the production implementation can use an approved embedding model/API and Qdrant, pgvector, Weaviate, or another open-source store without changing ingestion orchestration.

## 10. Failure handling

Malformed parser JSON is rejected before indexing. Unsupported parser types fail fast. An unexpected embedding count is treated as an error rather than silently pairing vectors with the wrong chunks. Production workers should add retry classification, circuit breakers, dead-letter handling, and durable status transitions.

## 11. What I would add next

The next production increments would be real ADI/Docling parser clients, Qdrant/pgvector persistence, a durable queue, document/version metadata, retry/DLQ behavior, observability, and retrieval evaluation fixtures covering table fidelity, parser disagreements, malformed documents, version replacement, and cross-tenant access attempts.

## 12. Bonus: second parser adapter

Both parser output formats supplied by the assignment are supported: Azure Document Intelligence and Docling. Each has its own adapter and both feed the same canonical downstream pipeline. The Docling adapter is covered by a unit test, so the bonus does not introduce a second downstream implementation or duplicate ingestion logic.
