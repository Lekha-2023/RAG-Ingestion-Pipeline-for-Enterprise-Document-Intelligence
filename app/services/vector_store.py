from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class VectorRecord:
    id: str
    vector: list[float]
    payload: dict

class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, records: list[VectorRecord]) -> None: ...
    @abstractmethod
    async def delete(self, ids: list[str]) -> None: ...
    @abstractmethod
    async def get_by_document(self, tenant_id: str, document_id: str) -> list[VectorRecord]: ...

class InMemoryVectorStore(VectorStore):
    def __init__(self): self.records={}
    async def upsert(self, records):
        for r in records: self.records[r.id]=r
    async def delete(self, ids):
        for i in ids: self.records.pop(i,None)
    async def get_by_document(self, tenant_id, document_id):
        return [r for r in self.records.values() if r.payload.get("tenant_id")==tenant_id and r.payload.get("document_id")==document_id]
