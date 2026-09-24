import hashlib, math
from abc import ABC, abstractmethod

class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class DeterministicEmbedding(EmbeddingProvider):
    """Offline deterministic embedding for local runs/tests; replace with a real model in production."""
    def __init__(self, dimensions: int = 32): self.dimensions=dimensions
    async def embed(self, texts):
        out=[]
        for text in texts:
            v=[0.0]*self.dimensions
            for token in text.lower().split():
                h=int(hashlib.sha256(token.encode()).hexdigest(),16)
                v[h % self.dimensions] += 1.0
            n=math.sqrt(sum(x*x for x in v)) or 1.0
            out.append([x/n for x in v])
        return out
