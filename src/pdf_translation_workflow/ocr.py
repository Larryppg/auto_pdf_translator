from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import OcrConfig
from .models import Box

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrLine:
    box: Box
    text: str
    confidence: float


class ImageTextRecognizer:
    """Lazy RapidOCR wrapper; one model instance is shared safely between workers."""

    def __init__(self, config: OcrConfig):
        self.config = config
        self._engine: Any | None = None
        self._lock = threading.Lock()

    def _get_engine(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                try:
                    # Compatibility for installations created by the older workflow.
                    from rapidocr_onnxruntime import RapidOCR
                except ImportError:
                    raise RuntimeError(
                        "OCR is enabled but rapidocr and onnxruntime are not installed"
                    ) from exc
            self._engine = RapidOCR()
        return self._engine

    def recognize(self, image: np.ndarray, x_scale: float, y_scale: float) -> list[OcrLine]:
        with self._lock:
            raw = self._get_engine()(image)
        result = raw[0] if isinstance(raw, tuple) else raw
        if result is None:
            return []
        # Newer wrappers may expose a result object rather than the legacy list.
        if hasattr(result, "txts") and hasattr(result, "boxes"):
            scores = getattr(result, "scores", [1.0] * len(result.txts))
            entries = zip(result.boxes, result.txts, scores, strict=False)
        else:
            entries = (
                (entry[0], entry[1], entry[2])
                for entry in result
                if isinstance(entry, (list, tuple)) and len(entry) >= 3
            )
        lines: list[OcrLine] = []
        for polygon, text, score in entries:
            value = str(text).strip()
            confidence = float(score)
            if not value or confidence < self.config.minimum_confidence:
                continue
            points = np.asarray(polygon, dtype=float).reshape(-1, 2)
            if len(points) < 2:
                continue
            lines.append(
                OcrLine(
                    box=Box(
                        float(points[:, 0].min()) / x_scale,
                        float(points[:, 1].min()) / y_scale,
                        float(points[:, 0].max()) / x_scale,
                        float(points[:, 1].max()) / y_scale,
                    ),
                    text=value,
                    confidence=confidence,
                )
            )
        return lines
