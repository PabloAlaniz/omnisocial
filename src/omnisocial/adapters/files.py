"""Archivos del disco como medios para subir."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


def _read(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(length)


@dataclass(frozen=True, slots=True)
class PathFile:
    """Un `MediaFile` que se lee del disco de a partes, sin cargarlo entero en memoria."""

    path: Path
    content_type: str
    size: int

    @classmethod
    def open(cls, path: Path | str, content_type: str) -> PathFile:
        resolved = Path(path)
        return cls(resolved, content_type, resolved.stat().st_size)

    async def read(self, offset: int, length: int) -> bytes:
        return await asyncio.to_thread(_read, self.path, offset, length)
