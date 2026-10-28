"""Local, bounded extraction adapters. No external inference services."""

import csv
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .config import settings

SUPPORTED = {
    "txt",
    "csv",
    "json",
    "jsonl",
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "parquet",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "tif",
    "tiff",
    "mp3",
    "wav",
    "m4a",
    "mp4",
    "mov",
    "webm",
}


def command(args, timeout=120):
    import threading

    process = subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    timer = threading.Timer(timeout, process.kill)
    timer.start()
    try:
        output = process.stdout.read(4 * 1024 * 1024 + 1)
        if len(output) > 4 * 1024 * 1024:
            raise ValueError("Tool output exceeds metadata limit")
        if process.wait() != 0:
            raise ValueError("Local extraction tool failed or timed out")
        return output
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def checked_office(path):
    with zipfile.ZipFile(path) as archive:
        total = 0
        for entry in archive.infolist():
            total += entry.file_size
            if (
                total > settings.archive_expansion_bytes
                or entry.file_size > 128 * 1024 * 1024
                or entry.file_size > max(1, entry.compress_size) * 1000
            ):
                raise ValueError("Office archive expansion limit exceeded")
            if Path(entry.filename).is_absolute() or ".." in Path(entry.filename).parts:
                raise ValueError("Unsafe archive path")


def ocr(image):
    if not shutil.which("tesseract"):
        return "OCR unavailable: install Tesseract locally."
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "image.png"
        image.save(path)
        return command(
            ["tesseract", str(path), "stdout", "--psm", "3"], settings.parser_timeout
        ).decode("utf-8")


def extract(path, name, preview=None):
    import ijson

    kind = name.rsplit(".", 1)[-1].lower()
    if kind in ("txt", "csv", "json", "jsonl"):
        with path.open(encoding="utf-8-sig") as source:
            if kind == "csv":
                csv.field_size_limit(settings.max_record_bytes)
                for index, row in enumerate(csv.reader(source)):
                    yield f"row {index + 1}", json.dumps(row, ensure_ascii=False)
            elif kind == "json":
                first = source.read(4096).lstrip()[:1]
                source.seek(0)
                for index, row in enumerate(
                    ijson.items(source, "item" if first == "[" else "", use_float=True)
                ):
                    yield f"record {index + 1}", json.dumps(row, ensure_ascii=False)
            else:
                index = 0
                while line := source.readline(settings.max_record_bytes + 1):
                    index += 1
                    if len(line) > settings.max_record_bytes:
                        raise ValueError("Individual text record exceeds configured limit")
                    yield (
                        f"line {index}",
                        json.dumps(json.loads(line), ensure_ascii=False)
                        if kind == "jsonl"
                        else line,
                    )
        return
    if kind == "parquet":
        import polars as pl
        import pyarrow.parquet as pq

        for index, batch in enumerate(pq.ParquetFile(path).iter_batches(batch_size=128)):
            for row_index, row in enumerate(pl.from_arrow(batch).iter_rows(named=True)):
                yield (
                    f"batch {index + 1} row {row_index + 1}",
                    json.dumps(row, default=str, ensure_ascii=False),
                )
        return
    if kind in ("xlsx", "docx", "pptx"):
        checked_office(path)
        if kind == "xlsx":
            from openpyxl import load_workbook

            book = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in book:
                    for index, row in enumerate(sheet.iter_rows(values_only=True)):
                        yield (
                            f"{sheet.title[:100]} row {index + 1}",
                            json.dumps(row, default=str, ensure_ascii=False),
                        )
            finally:
                book.close()
        elif kind == "docx":
            from docx import Document

            doc = Document(path)
            for index, paragraph in enumerate(doc.paragraphs):
                yield f"paragraph {index + 1}", paragraph.text
            for index, table in enumerate(doc.tables):
                for row in table.rows:
                    yield f"table {index + 1}", json.dumps([cell.text for cell in row.cells])
        else:
            from pptx import Presentation

            for index, slide in enumerate(Presentation(path).slides):
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        yield f"slide {index + 1}", shape.text
                    if shape.has_table:
                        for row in shape.table.rows:
                            yield (
                                f"slide {index + 1} table",
                                json.dumps([cell.text for cell in row.cells]),
                            )
        return
    if kind == "pdf":
        import pymupdf
        from PIL import Image

        with pymupdf.open(path) as document:
            yield "document properties", json.dumps(document.metadata)
            for index, page in enumerate(document):
                text = page.get_text(sort=True)
                if not text.strip():
                    scale = min(1.5, 1600 / max(page.rect.width, page.rect.height))
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    text = ocr(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
                yield f"page {index + 1}", text
                if index == 0 and preview:
                    scale = min(1, 1200 / max(page.rect.width, page.rect.height))
                    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(preview)
        return
    if kind in ("jpg", "jpeg", "png", "webp", "tif", "tiff"):
        from PIL import Image, ImageOps

        Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
        with Image.open(path) as image:
            image.load()
            yield (
                "image metadata",
                json.dumps(
                    {
                        "format": image.format,
                        "width": image.width,
                        "height": image.height,
                        "frames": getattr(image, "n_frames", 1),
                        "exif_orientation": image.getexif().get(274),
                        "limitations": "Only the first frame is OCR processed. GPS and device identifiers excluded.",
                    }
                ),
            )
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1600, 1600))
            if preview:
                image.save(preview, format="PNG")
            yield "image OCR", ocr(image)
        return
    if kind in ("mp3", "wav", "m4a", "mp4", "mov", "webm"):
        with path.open("rb") as source:
            header = source.read(64)
        valid = (
            (
                header.startswith(b"ID3")
                or (len(header) > 1 and header[0] == 255 and header[1] & 224 == 224)
            )
            if kind == "mp3"
            else header.startswith(b"RIFF") and header[8:12] == b"WAVE"
            if kind == "wav"
            else header.startswith(bytes.fromhex("1a45dfa3"))
            if kind == "webm"
            else header[4:8] == b"ftyp"
        )
        if not valid:
            raise ValueError("Media container signature does not match the declared format")

        info = json.loads(
            command(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-show_entries",
                    "format=duration,format_name:stream=index,codec_name,codec_type,width,height,sample_rate,channels",
                    "-of",
                    "json",
                    str(path),
                ],
                settings.parser_timeout,
            )
        )
        yield "media metadata", json.dumps(info)
        videos = [
            stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"
        ]
        if videos and preview:
            command(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=960:-2",
                    "-threads",
                    "1",
                    "-y",
                    str(preview),
                ],
                settings.parser_timeout,
            )
        if videos and preview and settings.media_keyframes > 1:
            import math

            duration = float(info.get("format", {}).get("duration", 0))
            if math.isfinite(duration) and duration > 0:
                for index in range(1, settings.media_keyframes):
                    timestamp = duration * index / settings.media_keyframes
                    target = path.with_name(path.name + f".keyframe-{index}.png")
                    command(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-nostdin",
                            "-protocol_whitelist",
                            "file,pipe",
                            "-ss",
                            str(timestamp),
                            "-i",
                            str(path),
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale=960:-2",
                            "-threads",
                            "1",
                            "-y",
                            str(target),
                        ],
                        settings.parser_timeout,
                    )
                    yield (
                        f"keyframe {timestamp:.3f}s",
                        "Keyframe extracted locally; no semantic interpretation.",
                    )
        yield (
            "extraction limitations",
            "Media metadata and first video frame only; audio transcription is not enabled. No full semantic video interpretation.",
        )
        return
    raise ValueError("Unsupported file format")
