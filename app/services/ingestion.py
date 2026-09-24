import hashlib
import json
import re
from typing import Any

from app.models.domain import Chunk, IngestResult, ParsedDocument
from app.services.vector_store import VectorRecord


class IngestionService:
    """Orchestrates parse -> normalize -> chunk -> embed -> upsert."""

    def __init__(self, parsers, embeddings, vector_store, max_chars: int = 1200, overlap: int = 150):
        if overlap >= max_chars:
            raise ValueError("overlap must be smaller than max_chars")
        self.parsers = {parser.name: parser for parser in parsers}
        self.embeddings = embeddings
        self.store = vector_store
        self.max_chars = max_chars
        self.overlap = overlap

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _make_chunk(
        self,
        text: str,
        page: int | None,
        kind: str,
        idx: int,
        document_id: str,
        tenant_id: str,
        collection_id: str,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> Chunk:
        normalized = self._clean(text)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        # The content hash makes re-ingestion idempotent while the chunk index keeps IDs stable
        # within one document version.
        chunk_id = hashlib.sha256(
            f"{tenant_id}:{document_id}:{idx}:{content_hash}".encode("utf-8")
        ).hexdigest()
        payload_metadata = {
            **metadata,
            "tags": list(tags),
            "element_type": kind,
            "page": page,
        }
        return Chunk(
            chunk_id=chunk_id,
            document_id=document_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            text=normalized,
            page=page,
            chunk_index=idx,
            content_hash=content_hash,
            metadata=payload_metadata,
        )

    def _split_text(self, text: str) -> list[str]:
        """Split long prose on word boundaries while keeping a small overlap."""
        text = self._clean(text)
        if len(text) <= self.max_chars:
            return [text] if text else []

        parts: list[str] = []
        remaining = text
        while len(remaining) > self.max_chars:
            cut = remaining.rfind(" ", 0, self.max_chars + 1)
            if cut < self.max_chars // 2:
                cut = self.max_chars
            parts.append(remaining[:cut].strip())
            next_start = max(0, cut - self.overlap)
            remaining = remaining[next_start:].strip()
        if remaining:
            parts.append(remaining)
        return parts

    def _split_table(self, rows: list[list[str]], caption: str | None) -> list[str]:
        """Keep table rows intact; repeat the header when a table spans chunks."""
        non_empty = [[self._clean(cell) for cell in row] for row in rows]
        non_empty = [row for row in non_empty if any(row)]
        if not non_empty:
            return []

        prefix = f"Table: {caption}\n" if caption else "Table:\n"
        header = " | ".join(non_empty[0])
        chunks: list[str] = []
        current_rows = [header]

        for row in non_empty[1:]:
            candidate = prefix + "\n".join(current_rows + [" | ".join(row)])
            if len(candidate) <= self.max_chars or len(current_rows) == 1:
                current_rows.append(" | ".join(row))
            else:
                chunks.append(prefix + "\n".join(current_rows))
                current_rows = [header, " | ".join(row)]

        if current_rows:
            chunks.append(prefix + "\n".join(current_rows))
        return chunks

    def _chunks(
        self,
        parsed: ParsedDocument,
        document_id: str,
        tenant_id: str,
        collection_id: str,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        index = 0
        base_metadata = {
            **parsed.metadata,
            **metadata,
        }

        for element in parsed.elements:
            for part in self._split_text(element.text):
                chunks.append(
                    self._make_chunk(
                        part,
                        element.page,
                        element.element_type,
                        index,
                        document_id,
                        tenant_id,
                        collection_id,
                        tags,
                        base_metadata,
                    )
                )
                index += 1

        for table in parsed.tables:
            for part in self._split_table(table.rows, table.caption):
                chunks.append(
                    self._make_chunk(
                        part,
                        table.page,
                        "table",
                        index,
                        document_id,
                        tenant_id,
                        collection_id,
                        tags,
                        {**base_metadata, "table_id": table.table_id, "caption": table.caption},
                    )
                )
                index += 1

        return chunks

    async def ingest(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        document_id: str,
        tenant_id: str,
        collection_id: str,
        document_type: str | None,
        tags: list[str],
        metadata: dict,
    ) -> IngestResult:
        """Ingest parser output. The adapter boundary is where real parser clients plug in."""
        try:
            payload = json.loads(file_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("file_bytes must contain valid UTF-8 parser JSON for this offline implementation") from exc

        parser_name = document_type or payload.get("_parser") or "azure_document_intelligence"
        parser = self.parsers.get(parser_name)
        if parser is None:
            raise ValueError(f"Unsupported parser: {parser_name}")

        parsed = parser.parse(payload)
        effective_metadata = {
            **metadata,
            "filename": filename,
            "parser": parser_name,
            "document_version": metadata.get("document_version"),
        }
        chunks = self._chunks(
            parsed,
            document_id,
            tenant_id,
            collection_id,
            tags,
            effective_metadata,
        )

        existing = await self.store.get_by_document(tenant_id, document_id)
        old_by_hash = {record.payload.get("content_hash"): record for record in existing}
        new_hashes = {chunk.content_hash for chunk in chunks}

        reused_count = 0
        to_index: list[Chunk] = []
        for chunk in chunks:
            if chunk.content_hash in old_by_hash:
                reused_count += 1
            else:
                to_index.append(chunk)

        stale_ids = [
            record.id
            for record in existing
            if record.payload.get("content_hash") not in new_hashes
        ]

        if to_index:
            vectors = await self.embeddings.embed([chunk.text for chunk in to_index])
            if len(vectors) != len(to_index):
                raise ValueError("embedding provider returned an unexpected number of vectors")
            await self.store.upsert(
                [
                    VectorRecord(
                        id=chunk.chunk_id,
                        vector=vector,
                        payload={
                            "tenant_id": chunk.tenant_id,
                            "document_id": chunk.document_id,
                            "collection_id": chunk.collection_id,
                            "chunk_id": chunk.chunk_id,
                            "content_hash": chunk.content_hash,
                            "text": chunk.text,
                            "page": chunk.page,
                            "metadata": chunk.metadata,
                        },
                    )
                    for chunk, vector in zip(to_index, vectors)
                ]
            )

        if stale_ids:
            await self.store.delete(stale_ids)

        return IngestResult(
            document_id=document_id,
            tenant_id=tenant_id,
            status="completed",
            chunk_count=len(chunks),
            reused_count=reused_count,
            indexed_count=len(to_index),
            skipped_count=len(stale_ids),
            parser=parser_name,
        )
