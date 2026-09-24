# Design — Enterprise RAG Ingestion Pipeline

## 1. Goal and scope

The goal of this assessment is to build a small but production-oriented ingestion pipeline for enterprise documents that may come from different parsers.

The main idea is to keep the pipeline simple and modular:

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

For the assessment, the service accepts the provided parser JSON through the `file_bytes_b64` field. This keeps the project runnable without Azure or Docling credentials. In a production environment, the real parser clients would sit in front of the same adapter layer, so the downstream pipeline would not need to change.

## 2. Architecture

```text
PDF / DOCX / scanned document
             |
             v
   +-----------------------+
   | Parser client / API   |
   +-----------+-----------+
               |
               v
   +-----------------------+
   | ParserAdapter          |
   | ADI | Docling | ...   |
   +-----------+-----------+
               |
               v
   +-----------------------+
   | ParsedDocument         |
   | common representation  |
   +-----------+-----------+
               |
               v
   +-----------------------+
   | Structure-aware       |
   | chunking              |
   +-----------+-----------+
               |
               v
        SHA-256 hash
               |
               v
   +-----------------------+
   | EmbeddingProvider     |
   +-----------+-----------+
               |
               v
   +-----------------------+
   | VectorStore            |
   | Qdrant / pgvector /   |
   | other vector DB       |
   +-----------------------+
```

I intentionally separated the parser layer from the rest of the pipeline. Azure Document Intelligence and Docling describe documents differently, but the ingestion service should not have to know those differences.

Each adapter converts its parser-specific response into the same `ParsedDocument` model. From that point onward, chunking, hashing, embedding, and indexing are shared.

This also makes adding another parser relatively straightforward: add an adapter rather than adding parser-specific conditions throughout the ingestion service.

## 3. Canonical representation and provenance

The canonical model is the point where I want to make the document structure consistent before doing anything with embeddings.

The extracted elements retain useful provenance such as:

- document ID
- page number
- section information
- filename
- parser/schema information
- element type
- document version
- tags and tenant information

For tables, cells are reconstructed using their row and column positions before chunking. This is important because a value such as `$20` is not very useful by itself if the relationship to its column header, such as `Your Cost`, has been lost.

The resulting chunks therefore carry enough metadata to trace retrieved content back to the original document and its location.

## 4. Chunking strategy

I use different handling for normal text and tables.

For normal text, the content is normalized and split on word boundaries with a bounded overlap. The goal is to keep chunks large enough to preserve meaning while avoiding unnecessarily large embedding inputs.

For tables, I do not treat the table as ordinary paragraph text. Rows stay together, and when a table is too large for one chunk, the header is repeated in subsequent chunks.

For example:

```text
Service | Your Cost
Primary Care | $20
Specialist   | $40
```

If the table has to be split, the later chunks keep the header:

```text
Service | Your Cost
Specialist | $40
```

I chose this because the assessment specifically calls out table fidelity as an important failure mode. In a real system, I would tune the chunk size and overlap using retrieval/evaluation data instead of assuming one fixed value works equally well for every document type.

## 5. Incremental and idempotent ingestion

One of the things I wanted to avoid was re-embedding the same content every time a document is uploaded.

For that reason, each normalized chunk gets a SHA-256 content hash.

The behavior is then straightforward:

```text
Same chunk content
       |
       +--> same hash --> reuse existing embedding

Changed chunk
       |
       +--> new hash --> create a new embedding

Removed chunk
       |
       +--> hash no longer exists --> remove stale record
```

This gives us two benefits: it reduces unnecessary embedding cost and prevents old content from remaining in the vector store after a document is updated.

The same approach also makes repeated ingestion idempotent for unchanged content.

## 6. Multi-tenant isolation

Tenant isolation is treated as part of the data model rather than something handled only by the API layer.

Tenant ID is carried with every vector/document record and is used when retrieving records for a document.

The in-memory implementation used for the assessment enforces the tenant match during lookup. In production, I would also enforce the tenant filter inside the vector database or persistence layer itself.

The important point is that tenant isolation should not depend only on a caller remembering to supply the right filter. The storage layer should enforce it as well.

## 7. Async processing and scaling

The assignment describes a much larger environment than this take-home implementation, so I kept the demo intentionally small and deterministic.

For a production deployment handling millions of documents, I would move the heavier work out of the request path.

A typical flow would be:

```text
Upload
  |
  v
Create ingestion job
  |
  v
Durable queue
  |
  +----> Parser workers
  |
  +----> Chunking / embedding workers
  |
  +----> Vector indexing
```

This would allow workers to scale independently and would prevent a large document or large tenant from blocking API requests.

Other changes I would make at that scale include:

1. Store original documents in durable object storage.
2. Store document/version metadata in a durable database.
3. Batch embedding and vector upserts where possible.
4. Cache embeddings using the content hash.
5. Use idempotency keys and retry with exponential backoff.
6. Send documents that repeatedly fail processing to a dead-letter queue.
7. Add backpressure and bounded concurrency.
8. Track parser failures, table extraction failures, embedding latency, indexing latency, queue depth, and per-tenant throughput.
9. Partition or otherwise isolate workloads when tenant volume becomes significant.

## 8. Security and enterprise considerations

Enterprise documents can contain confidential or regulated information, so security needs to be part of the ingestion design from the beginning.

In production, I would make sure that:

- the caller is authenticated and authorized for the tenant;
- file size, type, and parser payloads are validated;
- document contents are not written to normal application logs;
- documents and vector data are encrypted in transit and at rest;
- credentials and API keys are kept outside source control;
- retention and deletion rules are enforced;
- document and parser versions are auditable;
- tenant filters are enforced by the persistence layer.

The same principle applies to observability: logs and metrics should help diagnose the pipeline without accidentally becoming another place where sensitive document content is exposed.

## 9. Embeddings and vector store

For the take-home, I intentionally used a deterministic local embedding implementation and an in-memory vector store.

That choice makes the project easy to run and test without requiring cloud credentials or an external database.

The important part is that both are behind interfaces:

```text
EmbeddingProvider
VectorStore
```

So the ingestion service does not need to change when the local implementation is replaced with a production embedding model/API and a vector database such as Qdrant or pgvector.

This also keeps the core ingestion logic focused on document processing rather than coupling it to one vendor.

## 10. Failure handling

The pipeline fails early when it receives malformed parser JSON or an unsupported parser type.

I also treat an unexpected number of embeddings as an error instead of silently matching vectors to the wrong chunks. A silent mismatch could create incorrect retrieval results that are difficult to diagnose later.

For production, I would extend this with:

- retryable vs. non-retryable error classification;
- exponential backoff;
- circuit breakers for external services;
- dead-letter handling;
- durable ingestion status transitions;
- clearer failure reasons for individual documents.

## 11. What I would add next

If this moved from a take-home into a real production service, my next steps would be:

1. Connect the real Azure Document Intelligence and Docling clients.
2. Replace the in-memory vector store with Qdrant, pgvector, or another approved production store.
3. Add durable document/version metadata.
4. Move long-running ingestion to a queue-based worker model.
5. Add retry and dead-letter handling.
6. Add production metrics, tracing, and dashboards.
7. Build a retrieval evaluation set covering normal text, tables, document updates, parser differences, malformed documents, and cross-tenant access attempts.
8. Add load testing for large documents and high tenant concurrency.

## 12. Bonus: second parser adapter

The repository supports both parser formats provided in the assessment:

- Azure Document Intelligence
- Docling

Each parser has its own adapter, but both produce the same canonical document representation and then use the exact same chunking, hashing, embedding, and vector-store flow.

I chose this approach deliberately because the bonus should not require maintaining two separate ingestion pipelines. The Docling adapter also has its own unit test.
