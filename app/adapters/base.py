from abc import ABC, abstractmethod
from app.models.domain import ParsedDocument


class ParserAdapter(ABC):
    """Translate one parser's JSON contract into the canonical domain model."""

    name: str

    @abstractmethod
    def parse(self, payload: dict) -> ParsedDocument:
        raise NotImplementedError
