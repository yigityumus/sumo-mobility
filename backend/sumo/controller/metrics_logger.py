from __future__ import annotations

import csv
from pathlib import Path


class CsvLogger:
    def __init__(self, path: Path, fieldnames: list[str]):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("w", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)
        self.writer.writeheader()

    def write(self, **kwargs) -> None:
        self.writer.writerow(kwargs)

    def flush(self) -> None:
        self.file.flush()

    def checkpoint(self) -> int:
        """Return a durable byte position that can be restored after replay."""
        self.file.flush()
        return self.file.tell()

    def restore(self, position: int) -> None:
        """Discard rows written after a controller/SUMO checkpoint."""
        self.file.flush()
        self.file.seek(position)
        self.file.truncate()

    def close(self) -> None:
        self.file.close()
