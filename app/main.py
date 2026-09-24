import base64
import binascii
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.adapters.adi import ADIParserAdapter
from app.adapters.docling import DoclingParserAdapter
from app.services.embedding import DeterministicEmbedding
from app.services.ingestion import IngestionService
from app.services.vector_store import InMemoryVectorStore

app = FastAPI(title="Enterprise RAG Ingestion API", version="1.0.0")
store = InMemoryVectorStore()
service = IngestionService(
    parsers=[ADIParserAdapter(), DoclingParserAdapter()],
    embeddings=DeterministicEmbedding(),
    vector_store=store,
)


class IngestRequest(BaseModel):
    file_bytes_b64: str
    filename: str
    document_id: str
    tenant_id: str
    collection_id: str
    document_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
async def ingest(request: IngestRequest):
    try:
        file_bytes = base64.b64decode(request.file_bytes_b64, validate=True)
        result = await service.ingest(
            file_bytes=file_bytes,
            filename=request.filename,
            document_id=request.document_id,
            tenant_id=request.tenant_id,
            collection_id=request.collection_id,
            document_type=request.document_type,
            tags=request.tags,
            metadata=request.metadata,
        )
        return result.__dict__
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
