"""Streaming utilities for zstd-compressed files."""

import io
from collections.abc import Iterator
from pathlib import Path

import zstandard


def stream_zst_lines(zst_path: Path) -> Iterator[str]:
    """Yield lines from a zstd-compressed file without loading into memory."""
    dctx = zstandard.ZstdDecompressor()
    with zst_path.open("rb") as fh:
        reader = dctx.stream_reader(fh)
        text_reader = io.TextIOWrapper(reader, encoding="utf-8")
        yield from text_reader
