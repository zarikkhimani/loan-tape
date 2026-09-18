"""Tentative table boundaries from sparse row structure, without decoding values."""

from __future__ import annotations

from dataclasses import dataclass, field

from loan_tape.ranges import CellRange


@dataclass(frozen=True)
class TableSuggestion:
    area: CellRange
    header_row: int | None = None
    name: str = ""
    basis: str = "layout"


def overlaps(a: CellRange, b: CellRange) -> bool:
    return (
        a.min_row <= b.max_row
        and b.min_row <= a.max_row
        and a.min_column <= b.max_column
        and b.min_column <= a.max_column
    )


def _mask(columns: set[int]) -> int:
    result = 0
    for column in columns:
        result |= 1 << column
    return result


@dataclass
class _Block:
    left: int
    right: int
    last_row: int
    # Only first/last positions per column and candidate header bit masks are retained.
    columns: dict[int, tuple[int, int]] = field(default_factory=dict)
    candidates: dict[int, tuple[int, int]] = field(default_factory=dict)
    has_text_row: bool = False

    def merge(self, other: _Block) -> None:
        self.left = min(self.left, other.left)
        self.right = max(self.right, other.right)
        self.last_row = max(self.last_row, other.last_row)
        self.has_text_row |= other.has_text_row
        for column, (first, last) in other.columns.items():
            previous = self.columns.get(column, (first, last))
            self.columns[column] = (min(first, previous[0]), max(last, previous[1]))
        for row, (filled, text) in other.candidates.items():
            old = self.candidates.get(row, (0, 0))
            self.candidates[row] = (old[0] | filled, old[1] | text)

    def observe(self, row: int, columns: set[int], texts: set[int]) -> None:
        new_columns = columns.difference(self.columns)
        dense_text = len(texts) >= 2 and texts == columns
        if new_columns or (dense_text and not self.has_text_row):
            self.candidates[row] = (_mask(columns), _mask(texts))
        self.has_text_row |= dense_text
        for column in columns:
            first = self.columns.get(column, (row, row))[0]
            self.columns[column] = (first, row)
        self.last_row = row

    def suggestion(self) -> TableSuggestion | None:
        first = min(first for first, _ in self.columns.values())
        last = max(last for _, last in self.columns.values())
        width = self.right - self.left + 1
        if width < 2 or first == last:
            return None  # Single-cell titles/notes and single-column lists are not inferred tables.
        header = None
        scope = ((1 << (self.right + 1)) - 1) ^ ((1 << self.left) - 1)
        minimum = max(2, (width * 3 + 4) // 5)
        for row, (filled, text) in sorted(self.candidates.items()):
            filled, text = filled & scope, text & scope
            continuing = sum(end > row for _, end in self.columns.values())
            if filled == text and text.bit_count() >= minimum and continuing >= minimum:
                header = row
                break
        return TableSuggestion(CellRange(header or first, self.left, last, self.right), header)


class StructureDetector:
    """Track separate horizontal blocks independently, including stacked neighbours.

    Empty row/column gaps split plain ranges; explicit Excel table definitions can
    override these geometric boundaries. Every row is considered and
    each detected table is retained independently, with no suggestion-count cutoff.
    """

    def __init__(self) -> None:
        self.active: list[_Block] = []
        self.tables: list[TableSuggestion] = []

    def _finish(self, block: _Block) -> None:
        suggestion = block.suggestion()
        if suggestion:
            self.tables.append(suggestion)

    def observe(self, row: int, columns: set[int], texts: set[int]) -> None:
        if not columns:
            return
        remaining = []
        for block in self.active:
            if row > block.last_row + 1:
                self._finish(block)
            else:
                remaining.append(block)
        # Merge intersecting column intervals; blank cells inside a known block
        # do not split it. A blank row local to one block closes only that block.
        segments: list[tuple[int, int, _Block | None, set[int]]] = [
            (block.left, block.right, block, set()) for block in remaining
        ]
        run: set[int] = set()
        previous = 0
        for column in sorted(columns):
            if run and column != previous + 1:
                segments.append((min(run), max(run), None, run))
                run = set()
            run.add(column)
            previous = column
        if run:
            segments.append((min(run), max(run), None, run))
        segments.sort(key=lambda item: item[0])
        groups: list[tuple[_Block, set[int]]] = []
        for left, right, existing, cells in segments:
            if groups and left <= groups[-1][0].right:
                block, current = groups[-1]
                block.right = max(block.right, right)
                if existing is not None:
                    block.merge(existing)
                current.update(cells)
            else:
                groups.append((existing or _Block(left, right, row), set(cells)))
        self.active = []
        for block, cells in groups:
            if cells:
                block.observe(row, cells, texts.intersection(cells))
            self.active.append(block)

    def finish(self) -> tuple[TableSuggestion, ...]:
        for block in self.active:
            self._finish(block)
        self.active.clear()
        return tuple(self.tables)
