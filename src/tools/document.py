from __future__ import annotations

import csv
import hashlib
import io
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool

from src.agents.context import AgentRuntimeContext
from src.logger import get_logger
from src.utils import ensure_conversation_workspace

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".pdf": "PDF",
    ".doc": "DOC",
    ".docx": "DOCX",
    ".txt": "TXT",
    ".csv": "CSV",
    ".tsv": "TSV",
    ".xls": "XLS",
    ".xlsx": "XLSX",
    ".ppt": "PPT",
    ".pptx": "PPTX",
}

LEGACY_OFFICE_CONVERSION_GUIDANCE: dict[str, str] = {
    ".doc": "暂不支持旧版 .doc 文件解析，请将文件另存为 .docx 后重新上传。",
    ".ppt": "暂不支持旧版 .ppt 文件解析，请将文件另存为 .pptx 后重新上传。",
}

DEFAULT_MAX_CHARS_PER_FILE = 50_000
TOTAL_MAX_CHARS = 100_000
INLINE_DISPLAY_MAX_CHARS = 8_000
OUTPUT_FILE_ID_LENGTH = 12

READ_DOCUMENTS_DESCRIPTION = """Read multiple document files in batch and extract their text content.
Supported file types: PDF (.pdf), Word documents (.docx), Excel spreadsheets (.xls, .xlsx), PowerPoint presentations (.pptx), plain text (.txt), CSV tables (.csv), and TSV tables (.tsv).
Legacy Office files (.doc, .ppt) are only recognized and are not parsed directly; when these files are encountered, ask the user to convert them to .docx or .pptx and upload again.

Use this tool to read reports, manuals, spreadsheets, slides, notes, ordinary papers, experimental data, and similar documents for summarization, Q&A, information extraction, comparison, or analysis. It uses document-structure-aware parsers for PDF, Office, and spreadsheet formats.

This tool returns general document content. For a paper PDF whose goal is to extract or reproduce a computational workflow, use extract_workflow_from_literature directly.

When the combined result exceeds 8000 characters, only the first 8000 characters are returned inline. The available parsed result is saved as a Markdown file in the current conversation workspace. Use grep to search that file for relevant keywords before reading only the necessary sections.
"""


def _validate_path(raw_path: str) -> Path:
    path = Path(raw_path).resolve()
    # home = Path(os.path.expanduser("~")).resolve()
    # if not str(path).startswith(str(home)):
    #     raise PermissionError(f"路径不在 $HOME 目录下，拒绝访问: {raw_path}")
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {raw_path}")
    if not path.is_file():
        raise IsADirectoryError(f"路径不是文件: {raw_path}")
    return path


def _read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_txt(path: Path) -> str:
    return _read_text_with_fallback(path)


def _read_delimited_table(path: Path, delimiter: str, empty_label: str) -> str:
    raw = _read_text_with_fallback(path)
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return empty_label

    return _format_table_rows(rows)


def _read_csv(path: Path) -> str:
    return _read_delimited_table(path, delimiter=",", empty_label="(空 CSV 文件)")


def _read_tsv(path: Path) -> str:
    return _read_delimited_table(path, delimiter="\t", empty_label="(空 TSV 文件)")


def _format_table_rows(rows: list[list[str]]) -> str:
    col_widths: list[int] = []
    for row in rows:
        for i, cell in enumerate(row):
            width = len(cell)
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], width)
            else:
                col_widths.append(width)

    lines: list[str] = []
    for idx, row in enumerate(rows):
        padded = [cell.ljust(col_widths[i]) if i < len(col_widths) else cell for i, cell in enumerate(row)]
        lines.append(" | ".join(padded))
        if idx == 0:
            lines.append("-+-".join("-" * w for w in col_widths))
    return "\n".join(lines)


def _read_pdf(path: Path) -> str:
    import pdfplumber

    pages_text: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

    if not pages_text:
        return "(该 PDF 未提取到文本内容。可能是扫描件，暂不支持 OCR 提取。)"

    return "\n\n".join(pages_text)


def _read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)

    for table in doc.tables:
        table_lines: list[str] = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            table_lines.append(" | ".join(cells))
        if table_lines:
            parts.append("\n".join(table_lines))

    return "\n\n".join(parts) if parts else "(DOCX 文件内容为空)"


def _read_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    sheet_parts: list[str] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            rows.append([str(cell) if cell is not None else "" for cell in row])

        if not rows:
            sheet_parts.append(f"## Sheet: {sheet_name}\n(空)")
            continue

        sheet_parts.append(f"## Sheet: {sheet_name}\n" + _format_table_rows(rows))

    wb.close()
    return "\n\n".join(sheet_parts) if sheet_parts else "(XLSX 文件无数据)"


def _read_xls(path: Path) -> str:
    import xlrd

    wb = xlrd.open_workbook(str(path))
    sheet_parts: list[str] = []

    for sheet in wb.sheets():
        sheet_name = sheet.name
        if sheet.nrows == 0:
            sheet_parts.append(f"## Sheet: {sheet_name}\n(空)")
            continue

        rows: list[list[str]] = []
        for row_idx in range(sheet.nrows):
            row = [str(cell.value) if cell.value is not None else "" for cell in sheet.row(row_idx)]
            rows.append(row)

        sheet_parts.append(f"## Sheet: {sheet_name}\n" + _format_table_rows(rows))

    return "\n\n".join(sheet_parts) if sheet_parts else "(XLS 文件无数据)"


def _read_pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    parts: list[str] = []

    for idx, slide in enumerate(prs.slides, start=1):
        slide_text: list[str] = []
        for shape in slide.shapes:
            text = getattr(shape, "text", "").strip()
            if text:
                slide_text.append(text)

        if slide_text:
            parts.append(f"## Slide {idx}\n" + "\n".join(slide_text))

    return "\n\n".join(parts) if parts else "(PPTX 文件内容为空)"


_PARSERS: dict[str, Callable[[Path], str]] = {
    ".txt": _read_txt,
    ".csv": _read_csv,
    ".tsv": _read_tsv,
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".xls": _read_xls,
    ".xlsx": _read_xlsx,
    ".pptx": _read_pptx,
}


def _parse_file(raw_path: str, max_chars: int) -> tuple[str, str, bool]:
    """解析单个文件，返回文件标签、内容或错误信息、是否成功。"""
    filename = Path(raw_path).name
    ext = Path(raw_path).suffix.lower()
    file_type = SUPPORTED_EXTENSIONS.get(ext, ext.upper().lstrip(".") or "UNKNOWN")
    label = f"{filename} ({file_type})"

    try:
        path = _validate_path(raw_path)
    except (PermissionError, FileNotFoundError, IsADirectoryError) as exc:
        return label, f"[错误] {exc}", False

    parser = _PARSERS.get(ext)
    if parser is None:
        if guidance := LEGACY_OFFICE_CONVERSION_GUIDANCE.get(ext):
            return label, f"[不支持] {guidance}", False

        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS.keys()))
        return label, f"[错误] 不支持的文件格式 '{ext}'。支持的格式: {supported}", False

    try:
        content = parser(path)
    except Exception as exc:
        logger.warning("Failed to parse file path=%s error=%s", raw_path, exc)
        return label, f"[错误] 文件解析失败: {type(exc).__name__}: {exc}", False

    total_chars = len(content)
    if total_chars > max_chars:
        content = content[:max_chars] + f"\n\n[内容已截断，共 {total_chars} 字符，已显示前 {max_chars} 字符]"

    return f"{label}, {len(content)} 字符", content, True


def _short_output_id(runtime: ToolRuntime[AgentRuntimeContext, Any] | None) -> str:
    tool_call_id = runtime.tool_call_id if runtime is not None else None
    source = tool_call_id or uuid.uuid4().hex
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:OUTPUT_FILE_ID_LENGTH]


def _write_document_result(
    content: str,
    runtime: ToolRuntime[AgentRuntimeContext, Any] | None,
) -> Path:
    context = runtime.context if runtime is not None else None
    conversation_id = context.conversation_id if isinstance(context, AgentRuntimeContext) else None
    if not conversation_id:
        raise ValueError("conversationId is required to save a large document result")

    workspace = ensure_conversation_workspace(conversation_id)
    output_path = workspace / f"documents_{_short_output_id(runtime)}.md"
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _format_result_for_model(
    content: str,
    runtime: ToolRuntime[AgentRuntimeContext, Any] | None,
) -> str:
    total_chars = len(content)
    if total_chars <= INLINE_DISPLAY_MAX_CHARS:
        return content

    preview = content[:INLINE_DISPLAY_MAX_CHARS].rstrip()
    try:
        output_path = _write_document_result(content, runtime)
    except Exception as exc:
        logger.exception("Failed to save large document result")
        return (
            f"{preview}\n\n"
            "========== 内容展示已截断 ==========\n\n"
            f"本次文档读取结果共 {total_chars} 字符，上方仅展示前 {len(preview)} 字符。\n"
            f"剩余内容保存失败: {type(exc).__name__}: {exc}"
        )

    return (
        f"{preview}\n\n"
        "========== 内容展示已截断 ==========\n\n"
        f"本次文档读取结果共 {total_chars} 字符，上方仅展示前 {len(preview)} 字符。\n"
        f"本次可用解析结果已保存至: {output_path}\n"
        "建议先使用 grep 在该文件中搜索关键词，再使用 read_file 的 offset 和 limit 分段读取相关内容。"
    )


@tool("read_documents", description=READ_DOCUMENTS_DESCRIPTION)
def read_documents(
    file_paths: Annotated[
        list[str],
        (
            "Document file paths to read. Supported formats: PDF, DOCX, TXT, CSV, TSV, XLS, XLSX, and PPTX. Legacy DOC and PPT files return conversion guidance."
        ),
    ],
    max_chars_per_file: Annotated[
        int,
        ("Maximum number of characters to return per file. Defaults to 50000."),
    ] = DEFAULT_MAX_CHARS_PER_FILE,
    runtime: ToolRuntime[AgentRuntimeContext, Any] = None,
) -> str:
    """批量读取多个本地文档文件，并提取文本内容。"""

    if not file_paths:
        return "未提供文件路径。请传入至少一个文件路径。"

    total = len(file_paths)
    success_count = 0
    fail_count = 0
    accumulated_chars = 0
    sections: list[str] = []

    for idx, raw_path in enumerate(file_paths, start=1):
        if accumulated_chars >= TOTAL_MAX_CHARS:
            remaining = total - idx + 1
            sections.append(
                f"========== [{idx}/{total}] 已跳过 ==========\n"
                f"已达到总字符上限 ({TOTAL_MAX_CHARS} 字符)，跳过剩余 {remaining} 个文件。"
            )
            fail_count += remaining
            break

        label, content, ok = _parse_file(raw_path, max_chars_per_file)

        header = f"========== [{idx}/{total}] {label} =========="
        sections.append(f"{header}\n\n{content}")

        if ok:
            success_count += 1
            accumulated_chars += len(content)
        else:
            fail_count += 1

    sections.append(f"========== 读取完成: {success_count}/{total} 成功, {fail_count} 失败 ==========")
    result = "\n\n".join(sections)
    return _format_result_for_model(result, runtime)


__all__ = ["read_documents"]
