"""
csv_exporter
============================
CSV export utilities.
"""

from __future__ import annotations

from pathlib import Path

import csv

from config import (
    SERIAL_COLUMN_HEADER,
    RANDOM_COLUMN_HEADER,
    EXPORT_FILENAME,
)


def write_csv(serial_numbers: list[int], random_numbers: list[int], filepath: Path) -> None:
    """
    Write both columns to a CSV file, fully overwriting whatever was there.
    """
    with open(str(filepath), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER])
        for s, r in zip(serial_numbers, random_numbers, strict=True):
            writer.writerow([s, r])


def get_default_export_path() -> Path:
    return Path.cwd() / EXPORT_FILENAME