"""Streaming utilities for zstd-compressed files."""

import io
from pathlib import Path
from typing import Iterator

import zstandard


def stream_zst_lines(zst_path: Path) -> Iterator[str]:
    """Yield lines from a zstd-compressed file without loading into memory."""
    dctx = zstandard.ZstdDecompressor()
    with open(zst_path, "rb") as fh:
        reader = dctx.stream_reader(fh)
        text_reader = io.TextIOWrapper(reader, encoding="utf-8")
        yield from text_reader
