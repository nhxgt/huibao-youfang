"""Bounded, read-only extraction. Never executes document macros or formulas."""
import base64
import io
import itertools
import zipfile
from html.parser import HTMLParser
from pathlib import Path

MAX_TEXT = 24000
OFFICE_TYPES = {".docx", ".xlsx", ".pptx"}
TEXT_TYPES = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".xml", ".html", ".htm", ".svg"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.parts.append(text.strip())


def check_office_archive(path):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if (len(members) > 10000 or sum(m.file_size for m in members) > 64 * 1024 * 1024 or
                any(m.file_size > max(m.compress_size, 1) * 1000 for m in members)):
            raise ValueError("压缩文档展开体积过大，未解析")


def extract(path: Path, name: str):
    ext = Path(name).suffix.lower()
    warnings, parts = [], []
    try:
        if ext in OFFICE_TYPES:
            check_office_archive(path)
        if ext in TEXT_TYPES:
            with path.open("rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                warnings.append("文本仅读取前 2 MB")
                raw = raw[:2 * 1024 * 1024]
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
            if ext in {".html", ".htm", ".svg", ".xml"}:
                parser = VisibleText()
                parser.feed(text)
                text = "\n".join(parser.parts)
            parts = [f"正文，第{i}行：{line}" for i, line in enumerate(text.splitlines(), 1) if line.strip()]
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            if reader.is_encrypted:
                return {"content": "", "warnings": ["PDF 已加密，无法读取，请提供未加密版本"], "image": None}
            for i, page in enumerate(itertools.islice(reader.pages, 100), 1):
                parts.append(f"第{i}页：\n{page.extract_text() or ''}")
                if sum(map(len, parts)) > MAX_TEXT:
                    break
            if len(reader.pages) > 100:
                warnings.append("PDF 最多解析前 100 页")
            if not any(part.split("：\n", 1)[-1].strip() for part in parts):
                parts = []
                warnings.append("PDF 没有可提取文字，可能是扫描件；请补充文字或上传对应图片")
        elif ext == ".docx":
            from docx import Document
            doc = Document(path)
            for i, paragraph in enumerate(itertools.islice(doc.paragraphs, 2000), 1):
                if paragraph.text.strip():
                    parts.append(f"段落{i}：{paragraph.text}")
            for i, table in enumerate(itertools.islice(doc.tables, 30), 1):
                for j, row in enumerate(itertools.islice(table.rows, 200), 1):
                    parts.append(f"表{i}第{j}行：" + " | ".join(c.text[:2000] for c in row.cells[:30]))
            warnings.append("Word 解析范围为正文段落和表格；图片、批注、页眉及修订标记未解析")
        elif ext == ".xlsx":
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
            try:
                for sheet in book.worksheets[:10]:
                    for i, row in enumerate(sheet.iter_rows(max_row=200, max_col=30, values_only=True), 1):
                        if any(v is not None for v in row):
                            parts.append(f"工作表《{sheet.title}》第{i}行：" +
                                         " | ".join("" if v is None else str(v)[:2000] for v in row))
                    if sum(map(len, parts)) > MAX_TEXT:
                        break
                warnings.append("表格最多读取前 10 个工作表各 200 行、30 列；公式原样保留，未执行计算")
            finally:
                book.close()
        elif ext == ".pptx":
            from pptx import Presentation
            deck = Presentation(path)
            for i, slide in enumerate(itertools.islice(deck.slides, 100), 1):
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        parts.append(f"幻灯片{i}：{shape.text}")
                    if shape.has_table:
                        for j, row in enumerate(itertools.islice(shape.table.rows, 100), 1):
                            parts.append(f"幻灯片{i}表格第{j}行：" + " | ".join(c.text for c in row.cells))
                if sum(map(len, parts)) > MAX_TEXT:
                    break
            warnings.append("演示文稿只提取文字与表格，未解析图表数值和嵌入文件")
        elif ext in IMAGE_TYPES:
            from PIL import Image, ImageOps
            with Image.open(path) as image:
                if image.width * image.height > 25_000_000:
                    raise ValueError("图片像素超过 2500 万，请缩小后重试")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1600, 1600))
                out = io.BytesIO()
                image.save(out, format="JPEG", quality=85)
            return {"content": "", "warnings": ["图片识别需要所配置模型支持视觉输入"],
                    "image": "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")}
        else:
            return {"content": "", "warnings": [f"暂不解析 {ext or '无扩展名'} 文件；原文件仍会归档打包"], "image": None}
        text = "\n".join(parts)
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT]
            warnings.append(f"材料文字超过 {MAX_TEXT} 字符，仅分析前段内容")
        return {"content": text, "warnings": warnings, "image": None}
    except Exception:
        return {"content": "", "warnings": ["文件解析失败或文件格式与扩展名不符；请提供可读取版本或补充工作内容"], "image": None}
