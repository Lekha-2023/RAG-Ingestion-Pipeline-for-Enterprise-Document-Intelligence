import asyncio
import json

from app.adapters.adi import ADIParserAdapter
from app.adapters.docling import DoclingParserAdapter
from app.services.embedding import DeterministicEmbedding
from app.services.ingestion import IngestionService
from app.services.vector_store import InMemoryVectorStore


ADI = {
    "paragraphs": [
        {
            "content": "All amounts shown are in-network rates.",
            "role": None,
            "bounding_regions": [{"page_number": 1}],
        },
        {
            "content": "Annual Deductible",
            "role": "sectionHeading",
            "bounding_regions": [{"page_number": 1}],
        },
    ],
    "tables": [
        {
            "row_count": 3,
            "column_count": 2,
            "cells": [
                {"row_index": 0, "column_index": 0, "content": "Service"},
                {"row_index": 0, "column_index": 1, "content": "Your Cost"},
                {"row_index": 1, "column_index": 0, "content": "Primary Care Visit"},
                {"row_index": 1, "column_index": 1, "content": "$20 copay"},
                {"row_index": 2, "column_index": 0, "content": "Specialist Visit"},
                {"row_index": 2, "column_index": 1, "content": "$40 copay"},
            ],
            "bounding_regions": [{"page_number": 1}],
            "caption": {"content": "Table 1: Cost Sharing Summary"},
        }
    ],
}


def service(max_chars=500):
    return IngestionService(
        [ADIParserAdapter(), DoclingParserAdapter()],
        DeterministicEmbedding(),
        InMemoryVectorStore(),
        max_chars=max_chars,
        overlap=min(150, max_chars // 4),
    )


def ingest_args(tenant="t1", payload=ADI, parser="azure_document_intelligence"):
    return dict(
        file_bytes=json.dumps(payload).encode(),
        filename="benefit_summary.pdf",
        document_id="d1",
        tenant_id=tenant,
        collection_id="c1",
        document_type=parser,
        tags=["benefits"],
        metadata={"document_version": "v1"},
    )


def test_adi_table_is_preserved_and_indexed():
    s = service()
    result = asyncio.run(s.ingest(**ingest_args()))
    records = asyncio.run(s.store.get_by_document("t1", "d1"))
    assert result.status == "completed"
    assert result.chunk_count == 3
    assert any("Primary Care Visit | $20 copay" in r.payload["text"] for r in records)
    assert any("Specialist Visit | $40 copay" in r.payload["text"] for r in records)


def test_idempotent_reingest_reuses_chunks():
    s = service()
    first = asyncio.run(s.ingest(**ingest_args()))
    second = asyncio.run(s.ingest(**ingest_args()))
    assert first.indexed_count == first.chunk_count
    assert second.reused_count == first.chunk_count
    assert second.indexed_count == 0


def test_changed_document_removes_stale_chunks():
    s = service()
    asyncio.run(s.ingest(**ingest_args()))
    changed = json.loads(json.dumps(ADI))
    changed["paragraphs"][0]["content"] = "Updated network rates apply."
    result = asyncio.run(s.ingest(**ingest_args(payload=changed)))
    records = asyncio.run(s.store.get_by_document("t1", "d1"))
    texts = {r.payload["text"] for r in records}
    assert result.indexed_count >= 1
    assert "Updated network rates apply." in texts
    assert "All amounts shown are in-network rates." not in texts


def test_tenant_isolation():
    s = service()
    asyncio.run(s.ingest(**ingest_args(tenant="t1")))
    asyncio.run(s.ingest(**ingest_args(tenant="t2")))
    assert len(asyncio.run(s.store.get_by_document("t1", "d1"))) == 3
    assert len(asyncio.run(s.store.get_by_document("t2", "d1"))) == 3


def test_docling_bonus_adapter_shape():
    payload = {
        "schema_name": "DoclingDocument",
        "version": "1.3.0",
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "section_header",
                "prov": [{"page_no": 1}],
                "text": "Annual Deductible",
            }
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "data": {
                    "table_cells": [
                        {"start_row_offset_idx": 0, "start_col_offset_idx": 0, "text": "Service"},
                        {"start_row_offset_idx": 0, "start_col_offset_idx": 1, "text": "Your Cost"},
                    ],
                    "num_rows": 1,
                    "num_cols": 2,
                },
                "prov": [{"page_no": 1}],
            }
        ],
    }
    parsed = DoclingParserAdapter().parse(payload)
    assert parsed.elements[0].text == "Annual Deductible"
    assert parsed.tables[0].rows == [["Service", "Your Cost"]]


def test_long_table_keeps_header_with_each_chunk():
    payload = json.loads(json.dumps(ADI))
    payload["tables"][0]["cells"] = [
        {"row_index": 0, "column_index": 0, "content": "Service"},
        {"row_index": 0, "column_index": 1, "content": "Your Cost"},
        *[
            {"row_index": i, "column_index": 0, "content": f"Service {i}"}
            for i in range(1, 8)
        ],
        *[
            {"row_index": i, "column_index": 1, "content": f"${i}0 copay"}
            for i in range(1, 8)
        ],
    ]
    payload["tables"][0]["row_count"] = 8
    s = service(max_chars=90)
    result = asyncio.run(s.ingest(**ingest_args(payload=payload)))
    records = asyncio.run(s.store.get_by_document("t1", "d1"))
    table_records = [r.payload["text"] for r in records if r.payload["metadata"]["element_type"] == "table"]
    assert result.chunk_count > 3
    assert len(table_records) >= 2
    assert all("Service | Your Cost" in text for text in table_records)
