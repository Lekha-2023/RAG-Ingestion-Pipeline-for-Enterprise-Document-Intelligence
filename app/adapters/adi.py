from app.adapters.base import ParserAdapter
from app.models.domain import Element, ParsedDocument, Table


class ADIParserAdapter(ParserAdapter):
    """Adapter for the Azure Document Intelligence JSON shape in the assignment."""

    name = "azure_document_intelligence"

    def parse(self, payload: dict) -> ParsedDocument:
        if not isinstance(payload, dict):
            raise ValueError("ADI parser output must be a JSON object")

        elements: list[Element] = []
        tables: list[Table] = []

        for i, paragraph in enumerate(payload.get("paragraphs", [])):
            if not isinstance(paragraph, dict):
                continue
            regions = paragraph.get("bounding_regions") or []
            page = regions[0].get("page_number") if regions else None
            text = str(paragraph.get("content") or "").strip()
            if text:
                elements.append(
                    Element(
                        element_id=f"p-{i}",
                        text=text,
                        element_type=paragraph.get("role") or "paragraph",
                        page=page,
                        metadata={"spans": paragraph.get("spans", [])},
                    )
                )

        for i, table in enumerate(payload.get("tables", [])):
            if not isinstance(table, dict):
                continue
            row_count = max(0, int(table.get("row_count", 0)))
            column_count = max(0, int(table.get("column_count", 0)))
            rows = [[""] * column_count for _ in range(row_count)]
            for cell in table.get("cells", []):
                row = int(cell.get("row_index", 0))
                col = int(cell.get("column_index", 0))
                if 0 <= row < row_count and 0 <= col < column_count:
                    rows[row][col] = str(cell.get("content") or "").strip()

            regions = table.get("bounding_regions") or []
            page = regions[0].get("page_number") if regions else None
            caption_obj = table.get("caption") or {}
            caption = caption_obj.get("content") if isinstance(caption_obj, dict) else None
            if any(any(cell for cell in row) for row in rows):
                tables.append(Table(f"t-{i}", rows, page, caption))

        return ParsedDocument(
            elements=elements,
            tables=tables,
            metadata={"source_schema": self.name},
        )
