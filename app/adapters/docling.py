from app.adapters.base import ParserAdapter
from app.models.domain import Element, ParsedDocument, Table


class DoclingParserAdapter(ParserAdapter):
    """Adapter for the Docling JSON shape in the assignment."""

    name = "docling"

    def parse(self, payload: dict) -> ParsedDocument:
        if not isinstance(payload, dict):
            raise ValueError("Docling parser output must be a JSON object")

        elements: list[Element] = []
        tables: list[Table] = []

        for i, item in enumerate(payload.get("texts", [])):
            if not isinstance(item, dict):
                continue
            provenance = item.get("prov") or []
            page = provenance[0].get("page_no") if provenance else None
            text = str(item.get("text") or "").strip()
            if text:
                elements.append(
                    Element(
                        element_id=item.get("self_ref") or f"text-{i}",
                        text=text,
                        element_type=item.get("label", "text"),
                        page=page,
                        metadata={"provenance": provenance},
                    )
                )

        for i, item in enumerate(payload.get("tables", [])):
            if not isinstance(item, dict):
                continue
            data = item.get("data") or {}
            row_count = max(0, int(data.get("num_rows", 0)))
            column_count = max(0, int(data.get("num_cols", 0)))
            rows = [[""] * column_count for _ in range(row_count)]
            for cell in data.get("table_cells", []):
                row = int(cell.get("start_row_offset_idx", 0))
                col = int(cell.get("start_col_offset_idx", 0))
                if 0 <= row < row_count and 0 <= col < column_count:
                    rows[row][col] = str(cell.get("text") or "").strip()

            provenance = item.get("prov") or []
            page = provenance[0].get("page_no") if provenance else None
            if any(any(cell for cell in row) for row in rows):
                tables.append(
                    Table(
                        item.get("self_ref") or f"table-{i}",
                        rows,
                        page,
                        metadata={"provenance": provenance},
                    )
                )

        return ParsedDocument(
            elements=elements,
            tables=tables,
            metadata={
                "source_schema": self.name,
                "schema_version": payload.get("version"),
            },
        )
