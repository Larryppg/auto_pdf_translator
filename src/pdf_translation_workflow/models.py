from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RegionKind = Literal["pdf_text", "image_ocr"]
TextAlign = Literal["left", "center", "right"]


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def expanded(self, amount: float) -> "Box":
        return Box(self.x0 - amount, self.y0 - amount, self.x1 + amount, self.y1 + amount)

    def intersection_area(self, other: "Box") -> float:
        width = max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))
        height = max(0.0, min(self.y1, other.y1) - max(self.y0, other.y0))
        return width * height

    def coverage_of_smaller(self, other: "Box") -> float:
        denominator = min(self.area, other.area)
        return self.intersection_area(other) / denominator if denominator else 0.0

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


@dataclass
class TextRegion:
    id: str
    page_number: int
    kind: RegionKind
    box: Box
    source_text: str
    font_size: float
    color: tuple[float, float, float]
    alignment: TextAlign = "left"
    confidence: float = 1.0
    translated_text: str | None = None
