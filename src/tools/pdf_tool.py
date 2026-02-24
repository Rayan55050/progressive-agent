"""
PDF Swiss Knife — extract text, metadata, merge, split, page-to-image.

Uses pypdf for text extraction, metadata, merge, and split operations.
All heavy work runs in asyncio.to_thread() to avoid blocking the event loop.
Note: 'to_image' action is not supported with pypdf (requires pymupdf).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "pdf_output"

try:
    from pypdf import PdfReader, PdfWriter

    PYPDF_OK = True
except ImportError:
    PdfReader = None  # type: ignore[assignment,misc]
    PdfWriter = None  # type: ignore[assignment,misc]
    PYPDF_OK = False
    logger.warning("pypdf not installed — PDF tool disabled. pip install pypdf")


class PDFSwissKnifeTool:
    """PDF operations: extract text, metadata, merge, split, page-to-image."""

    def __init__(self, pending_sends: list[Path] | None = None) -> None:
        self._pending_sends = pending_sends
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="pdf_tool",
            description=(
                "PDF швейцарский нож. "
                "Actions: 'text' — извлечь текст из PDF (всех или конкретных страниц); "
                "'info' — метаданные (автор, дата, кол-во страниц, размер); "
                "'merge' — объединить несколько PDF в один; "
                "'split' — извлечь страницы из PDF в новый файл; "
                "'to_image' — конвертировать страницу в PNG (высокое качество). "
                "Использовуй коли питають: 'вытащи текст из PDF', 'объедини PDF', "
                "'раздели PDF', 'инфо о PDF', 'страницу в картинку', 'скільки сторінок'."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'text', 'info', 'merge', 'split', 'to_image'",
                    required=True,
                    enum=["text", "info", "merge", "split", "to_image"],
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to PDF file (or first file for 'merge')",
                    required=True,
                ),
                ToolParameter(
                    name="pages",
                    type="string",
                    description=(
                        "Page range: '1-5', '1,3,5', '2-' (from 2 to end), '-3' (first 3). "
                        "1-indexed. Default: all pages."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="files",
                    type="string",
                    description="For 'merge': comma-separated paths to PDF files to merge (in order)",
                    required=False,
                ),
                ToolParameter(
                    name="output_path",
                    type="string",
                    description="Output file path (optional, auto-generated if not specified)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not PYPDF_OK:
            return ToolResult(success=False, error="pypdf not installed. Run: pip install pypdf")

        action = kwargs.get("action", "text")
        file_path = kwargs.get("file_path", "")

        if not file_path:
            return ToolResult(success=False, error="file_path is required")

        path = Path(file_path)

        # For merge, only first file needs to exist at this stage
        if action != "merge" and not path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")
        if action != "merge" and path.suffix.lower() != ".pdf":
            return ToolResult(success=False, error=f"Not a PDF: {path.name}")

        try:
            if action == "text":
                pages_str = kwargs.get("pages", "")
                return await asyncio.to_thread(self._extract_text, path, pages_str)
            elif action == "info":
                return await asyncio.to_thread(self._get_info, path)
            elif action == "merge":
                files_str = kwargs.get("files", "")
                output = kwargs.get("output_path", "")
                return await asyncio.to_thread(self._merge, path, files_str, output)
            elif action == "split":
                pages_str = kwargs.get("pages", "")
                output = kwargs.get("output_path", "")
                return await asyncio.to_thread(self._split, path, pages_str, output)
            elif action == "to_image":
                pages_str = kwargs.get("pages", "1")
                return await asyncio.to_thread(self._to_image, path, pages_str)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.exception("PDF tool error")
            return ToolResult(success=False, error=f"PDF error: {e}")

    @staticmethod
    def _parse_pages(pages_str: str, total: int) -> list[int]:
        """Parse page range string into 0-indexed page list.

        Formats: '1-5', '1,3,5', '2-', '-3', '' (all).
        Input is 1-indexed, output is 0-indexed.
        """
        if not pages_str or not pages_str.strip():
            return list(range(total))

        pages: list[int] = []
        for part in pages_str.split(","):
            part = part.strip()
            if "-" in part:
                parts = part.split("-", 1)
                start_str, end_str = parts[0].strip(), parts[1].strip()
                start = int(start_str) - 1 if start_str else 0
                end = int(end_str) if end_str else total
                start = max(0, min(start, total - 1))
                end = max(1, min(end, total))
                pages.extend(range(start, end))
            else:
                p = int(part) - 1
                if 0 <= p < total:
                    pages.append(p)

        return sorted(set(pages))

    @staticmethod
    def _extract_text(path: Path, pages_str: str) -> ToolResult:
        """Extract text from PDF pages."""
        reader = PdfReader(str(path))
        total = len(reader.pages)
        page_indices = PDFSwissKnifeTool._parse_pages(pages_str, total)

        if not page_indices:
            return ToolResult(success=False, error="No valid pages specified")

        text_parts = []
        for i in page_indices:
            text = reader.pages[i].extract_text() or ""
            if text.strip():
                text_parts.append(f"--- Page {i + 1} ---\n{text.strip()}")

        if not text_parts:
            return ToolResult(success=True, data={
                "answer": f"No text found in {path.name} (pages {pages_str or 'all'}). "
                          "The PDF may contain only images.",
            })

        full_text = "\n\n".join(text_parts)
        # Truncate to ~30K chars to avoid tool result truncation
        if len(full_text) > 30000:
            full_text = full_text[:30000] + f"\n\n... [truncated, {len(full_text)} chars total]"

        return ToolResult(success=True, data={
            "answer": f"Text from {path.name} ({len(page_indices)} pages):\n\n{full_text}",
            "pages_extracted": len(page_indices),
            "total_pages": total,
        })

    @staticmethod
    def _get_info(path: Path) -> ToolResult:
        """Get PDF metadata and structure info."""
        reader = PdfReader(str(path))
        meta = reader.metadata
        total = len(reader.pages)

        lines = [
            f"File: {path.name}",
            f"Size: {path.stat().st_size / 1024:.0f} KB",
            f"Pages: {total}",
        ]

        if meta:
            if meta.title:
                lines.append(f"Title: {meta.title}")
            if meta.author:
                lines.append(f"Author: {meta.author}")
            if meta.subject:
                lines.append(f"Subject: {meta.subject}")
            if meta.creator:
                lines.append(f"Creator: {meta.creator}")
            if meta.producer:
                lines.append(f"Producer: {meta.producer}")
            if meta.creation_date:
                lines.append(f"Created: {meta.creation_date}")
            if meta.modification_date:
                lines.append(f"Modified: {meta.modification_date}")

        # Page sizes
        if total > 0:
            page = reader.pages[0]
            box = page.mediabox
            width = float(box.width)
            height = float(box.height)
            lines.append(f"Page size: {width:.0f} x {height:.0f} pts "
                         f"({width / 72:.1f} x {height / 72:.1f} inches)")

        # Check for text
        has_text = False
        for i in range(min(total, 5)):  # Check first 5 pages
            text = reader.pages[i].extract_text() or ""
            if text.strip():
                has_text = True
                break

        lines.append(f"Contains text: {'yes' if has_text else 'no (scanned/image PDF?)'}")

        # TOC (outlines)
        try:
            if reader.outline:
                # Flatten outline entries
                def _count_outlines(outlines: list) -> int:
                    count = 0
                    for item in outlines:
                        if isinstance(item, list):
                            count += _count_outlines(item)
                        else:
                            count += 1
                    return count

                toc_count = _count_outlines(reader.outline)
                if toc_count > 0:
                    lines.append(f"\nTable of Contents: {toc_count} entries found")
        except Exception:
            pass  # Some PDFs have malformed outlines

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "pages": total,
        })

    @staticmethod
    def _merge(first_path: Path, files_str: str, output_path: str) -> ToolResult:
        """Merge multiple PDFs into one."""
        # Collect all files
        all_paths = [first_path]
        if files_str:
            for f in files_str.split(","):
                f = f.strip()
                if f:
                    all_paths.append(Path(f))

        if len(all_paths) < 2:
            return ToolResult(success=False, error="Need at least 2 PDF files to merge")

        # Validate all exist
        for p in all_paths:
            if not p.exists():
                return ToolResult(success=False, error=f"File not found: {p}")
            if p.suffix.lower() != ".pdf":
                return ToolResult(success=False, error=f"Not a PDF: {p.name}")

        # Output path
        if output_path:
            out = Path(output_path)
        else:
            out = DATA_DIR / f"merged_{first_path.stem}.pdf"

        # Merge
        writer = PdfWriter()
        for p in all_paths:
            reader = PdfReader(str(p))
            for page in reader.pages:
                writer.add_page(page)

        out.parent.mkdir(parents=True, exist_ok=True)
        with open(str(out), "wb") as f:
            writer.write(f)

        return ToolResult(success=True, data={
            "answer": f"Merged {len(all_paths)} PDFs -> {out.name} ({out.stat().st_size / 1024:.0f} KB)",
            "file_path": str(out),
            "files_merged": len(all_paths),
        })

    @staticmethod
    def _split(path: Path, pages_str: str, output_path: str) -> ToolResult:
        """Extract pages from PDF into a new file."""
        if not pages_str:
            return ToolResult(success=False, error="pages parameter is required for 'split' action")

        reader = PdfReader(str(path))
        total = len(reader.pages)
        page_indices = PDFSwissKnifeTool._parse_pages(pages_str, total)

        if not page_indices:
            return ToolResult(success=False, error="No valid pages specified")

        if output_path:
            out = Path(output_path)
        else:
            out = DATA_DIR / f"{path.stem}_pages_{pages_str.replace(',', '_').replace('-', '_')}.pdf"

        writer = PdfWriter()
        for i in page_indices:
            writer.add_page(reader.pages[i])

        out.parent.mkdir(parents=True, exist_ok=True)
        with open(str(out), "wb") as f:
            writer.write(f)

        return ToolResult(success=True, data={
            "answer": (
                f"Split: {path.name} -> {out.name}\n"
                f"Pages extracted: {len(page_indices)} of {total}\n"
                f"Size: {out.stat().st_size / 1024:.0f} KB"
            ),
            "file_path": str(out),
            "pages_extracted": len(page_indices),
        })

    def _to_image(self, path: Path, pages_str: str) -> ToolResult:
        """Convert PDF page(s) to PNG image(s). Not supported with pypdf."""
        return ToolResult(
            success=False,
            error=(
                "Page-to-image conversion is not supported with pypdf. "
                "Install pymupdf (pip install pymupdf) for this feature, "
                "or use 'text' action to extract text instead."
            ),
        )
