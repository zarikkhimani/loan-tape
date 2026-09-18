"""Source-coordinate ranges, independent of display page sizes."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CellRange:
    min_row: int
    min_column: int
    max_row: int
    max_column: int

    def __post_init__(self) -> None:
        if not (
            1 <= self.min_row <= self.max_row <= 1048576
            and 1 <= self.min_column <= self.max_column <= 16384
        ):
            raise ValueError("Enter an ordered Excel range between A1 and XFD1048576.")

    @property
    def address(self) -> str:
        first = f"{column_label(self.min_column)}{self.min_row}"
        last = f"{column_label(self.max_column)}{self.max_row}"
        return first if first == last else f"{first}:{last}"

    @property
    def row_count(self) -> int:
        return self.max_row - self.min_row + 1

    @property
    def column_count(self) -> int:
        return self.max_column - self.min_column + 1

    def contains(self, row: int, column: int) -> bool:
        return self.min_row <= row <= self.max_row and self.min_column <= column <= self.max_column

    def page(self, row: int, column: int, rows: int = 20, columns: int = 10) -> CellRange:
        if not self.contains(row, column):
            raise ValueError("Choose a cell inside the current range, or change the range first.")
        return CellRange(
            row,
            column,
            min(self.max_row, row + rows - 1),
            min(self.max_column, column + columns - 1),
        )


def column_label(index: int) -> str:
    label = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def parse_range(text: str) -> CellRange:
    match = re.fullmatch(
        r"\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)(?::\$?([A-Za-z]{1,3})\$?([1-9][0-9]*))?", text.strip()
    )
    if not match:
        raise ValueError("Enter a cell or range, for example G450 or G450:AZ18400.")

    def column(label: str) -> int:
        result = 0
        for letter in label.upper():
            result = result * 26 + ord(letter) - 64
        return result

    left, top, right, bottom = match.groups()
    return CellRange(int(top), column(left), int(bottom or top), column(right or left))
