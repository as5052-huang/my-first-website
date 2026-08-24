from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}
MAX_CHARS = 28000


class ResumeParseError(ValueError):
    pass


def extract_resume_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ResumeParseError("仅支持 PDF、DOCX、TXT 文件。")
    if not data:
        raise ResumeParseError("文件为空，请重新上传。")

    if suffix == ".pdf":
        text = _from_pdf(data)
    elif suffix == ".docx":
        text = _from_docx(data)
    else:
        text = data.decode("utf-8", errors="ignore")

    text = _normalize(text)
    if not text:
        raise ResumeParseError("未能从文件中提取到文字，请改用可复制文本的 PDF/DOCX，或直接粘贴简历。")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    return text


def _from_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise ResumeParseError("PDF 无法读取，可能已加密或已损坏。") from exc

    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _from_docx(data: bytes) -> str:
    try:
        doc = Document(BytesIO(data))
    except Exception as exc:
        raise ResumeParseError("DOCX 无法读取，请确认文件未损坏。") from exc

    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _normalize(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                collapsed.append("")
            blank = True
            continue
        blank = False
        collapsed.append(line)
    return "\n".join(collapsed).strip()
