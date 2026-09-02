from __future__ import annotations

import html
import logging
import math
import os
from collections import Counter
from pathlib import Path
from statistics import median

import numpy as np

try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF's legacy import name
    import fitz  # type: ignore[no-redef]

from .config import AppConfig
from .models import Box, TextAlign, TextRegion
from .ocr import ImageTextRecognizer
from .translation import Translator

LOG = logging.getLogger(__name__)


def _box(value: object) -> Box:
    x0, y0, x1, y1 = value  # type: ignore[misc]
    return Box(float(x0), float(y0), float(x1), float(y1))


def _union(boxes: list[Box]) -> Box:
    return Box(
        min(item.x0 for item in boxes),
        min(item.y0 for item in boxes),
        max(item.x1 for item in boxes),
        max(item.y1 for item in boxes),
    )


def _rgb_from_integer(value: int) -> tuple[float, float, float]:
    return (
        ((value >> 16) & 255) / 255,
        ((value >> 8) & 255) / 255,
        (value & 255) / 255,
    )


def _hex_color(color: tuple[float, float, float]) -> str:
    values = [max(0, min(255, round(channel * 255))) for channel in color]
    return "#" + "".join(f"{value:02x}" for value in values)


def _infer_alignment(line_boxes: list[Box], block_box: Box, page_width: float) -> TextAlign:
    if not line_boxes:
        return "left"
    centers = [item.center[0] for item in line_boxes]
    center_spread = max(centers) - min(centers) if len(centers) > 1 else 0
    near_page_center = abs(block_box.center[0] - page_width / 2) < page_width * 0.08
    if near_page_center and center_spread < max(8, block_box.width * 0.12):
        return "center"
    right_edges = [item.x1 for item in line_boxes]
    if block_box.x0 > page_width * 0.45 and max(right_edges) - min(right_edges) < 8:
        return "right"
    return "left"


def _clip_box(box: Box, page_box: Box) -> Box:
    return Box(
        max(page_box.x0, box.x0),
        max(page_box.y0, box.y0),
        min(page_box.x1, box.x1),
        min(page_box.y1, box.y1),
    )


class PdfTranslationEngine:
    def __init__(self, config: AppConfig, translator: Translator):
        self.config = config
        self.translator = translator
        self.ocr = ImageTextRecognizer(config.ocr) if config.ocr.enabled else None

    def translate(self, source: Path, temporary_output: Path) -> dict[str, object]:
        document = fitz.open(source)
        try:
            if document.needs_pass:
                raise RuntimeError("Password-protected PDFs are not supported")
            LOG.info(
                "Phase 1/5 - extraction and OCR started: %d pages",
                document.page_count,
            )
            all_regions: list[TextRegion] = []
            regions_by_page: dict[int, list[TextRegion]] = {}
            for page_index, page in enumerate(document):
                page_regions = self._extract_page_regions(page, page_index)
                regions_by_page[page_index] = page_regions
                all_regions.extend(page_regions)
                LOG.info(
                    "Extraction/OCR page %d/%d (%.1f%%): found %d text regions",
                    page_index + 1,
                    document.page_count,
                    (page_index + 1) / document.page_count * 100,
                    len(page_regions),
                )

            LOG.info(
                "Phase 1/5 - extraction and OCR completed: %d total regions",
                len(all_regions),
            )
            LOG.info("Phase 2/5 - document analysis and AI translation started")
            document_analysis = self.translator.translate_regions(all_regions)
            LOG.info("Phase 2/5 - document analysis and AI translation completed")

            LOG.info("Phase 3/5 - translated text layout started")
            for page_index, page in enumerate(document):
                self._replace_page_text(page, regions_by_page[page_index])
                LOG.info(
                    "Layout page %d/%d (%.1f%%): %d regions placed",
                    page_index + 1,
                    document.page_count,
                    (page_index + 1) / document.page_count * 100,
                    len(regions_by_page[page_index]),
                )
            LOG.info("Phase 3/5 - translated text layout completed")

            LOG.info("Phase 4/5 - writing temporary PDF: %s", temporary_output.name)
            temporary_output.parent.mkdir(parents=True, exist_ok=True)
            if temporary_output.exists():
                temporary_output.unlink()
            document.save(
                temporary_output,
                garbage=4,
                deflate=True,
                clean=True,
            )
            page_count = document.page_count
            LOG.info("Phase 4/5 - temporary PDF written")
        finally:
            document.close()

        LOG.info("Phase 5/5 - validating translated PDF")
        self._validate_output(temporary_output, page_count)
        LOG.info("Phase 5/5 - validation completed: %d pages readable", page_count)
        metrics: dict[str, object] = {
            "page_count": page_count,
            "region_count": len(all_regions),
            "pdf_text_regions": sum(item.kind == "pdf_text" for item in all_regions),
            "image_ocr_regions": sum(item.kind == "image_ocr" for item in all_regions),
        }
        if document_analysis is not None:
            metrics["document_analysis"] = document_analysis
        return metrics

    def _extract_page_regions(self, page: fitz.Page, page_index: int) -> list[TextRegion]:
        page_rect = _box(page.rect)
        regions: list[TextRegion] = []
        flags = getattr(fitz, "TEXTFLAGS_DICT", 0) & ~getattr(
            fitz, "TEXT_PRESERVE_IMAGES", 0
        )
        page_dict = page.get_text("dict", flags=flags)
        block_number = 0
        for block in page_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            line_texts: list[str] = []
            line_boxes: list[Box] = []
            sizes: list[float] = []
            colors: list[int] = []
            for line in block.get("lines", []):
                spans = [span for span in line.get("spans", []) if str(span.get("text", "")).strip()]
                if not spans:
                    continue
                line_text = "".join(str(span.get("text", "")) for span in spans).strip()
                if not line_text:
                    continue
                line_texts.append(line_text)
                line_boxes.append(_union([_box(span["bbox"]) for span in spans]))
                for span in spans:
                    sizes.append(float(span.get("size", 10)))
                    colors.append(int(span.get("color", 0)))
            if not line_texts or not line_boxes:
                continue
            value = "\n".join(line_texts).strip()
            if not value:
                continue
            block_number += 1
            region_box = _clip_box(_union(line_boxes), page_rect)
            regions.append(
                TextRegion(
                    id=f"p{page_index + 1:04d}-t{block_number:04d}",
                    page_number=page_index,
                    kind="pdf_text",
                    box=region_box,
                    source_text=value,
                    font_size=median(sizes) if sizes else 10,
                    color=_rgb_from_integer(Counter(colors).most_common(1)[0][0] if colors else 0),
                    alignment=_infer_alignment(line_boxes, region_box, page_rect.width),
                )
            )

        if self.ocr is not None:
            regions.extend(self._extract_image_text(page, page_index, regions))
        return regions

    def _extract_image_text(
        self,
        page: fitz.Page,
        page_index: int,
        existing: list[TextRegion],
    ) -> list[TextRegion]:
        image_boxes: list[Box] = []
        for image in page.get_image_info(xrefs=True):
            width, height = int(image.get("width", 0)), int(image.get("height", 0))
            if width < self.config.ocr.minimum_image_width or height < self.config.ocr.minimum_image_height:
                continue
            image_boxes.append(_box(image["bbox"]))
        if not image_boxes:
            return []

        scale = self.config.ocr.render_dpi / 72
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n
        )
        if pixmap.n > 3:
            array = array[:, :, :3]
        x_scale = pixmap.width / page.rect.width
        y_scale = pixmap.height / page.rect.height
        found = self.ocr.recognize(array, x_scale=x_scale, y_scale=y_scale)
        accepted: list[TextRegion] = []
        page_box = _box(page.rect)
        for line in found:
            candidate = _clip_box(line.box, page_box)
            center = candidate.center
            if not any(image_box.expanded(1).contains_point(*center) for image_box in image_boxes):
                continue
            if any(candidate.coverage_of_smaller(item.box) >= 0.55 for item in [*existing, *accepted]):
                continue
            if candidate.width < 2 or candidate.height < 2:
                continue
            accepted.append(
                TextRegion(
                    id=f"p{page_index + 1:04d}-i{len(accepted) + 1:04d}",
                    page_number=page_index,
                    kind="image_ocr",
                    box=candidate,
                    source_text=line.text,
                    font_size=max(6, candidate.height * 0.72),
                    color=(0, 0, 0),
                    alignment="left",
                    confidence=line.confidence,
                )
            )
        return accepted

    def _replace_page_text(self, page: fitz.Page, regions: list[TextRegion]) -> None:
        if not regions:
            return
        backgrounds = self._sample_backgrounds(page, regions)
        page_box = _box(page.rect)
        for region in regions:
            redact_box = _clip_box(
                region.box.expanded(self.config.layout.redaction_padding), page_box
            )
            fill = backgrounds.get(region.id, (1.0, 1.0, 1.0))
            page.add_redact_annot(
                fitz.Rect(redact_box.x0, redact_box.y0, redact_box.x1, redact_box.y1),
                fill=fill,
            )
        page.apply_redactions(
            images=getattr(fitz, "PDF_REDACT_IMAGE_PIXELS", 2),
            graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        )
        for region in regions:
            value = (region.translated_text or region.source_text).strip()
            if value:
                self._insert_fitted_text(page, region, value)

    def _sample_backgrounds(
        self, page: fitz.Page, regions: list[TextRegion]
    ) -> dict[str, tuple[float, float, float]]:
        if not self.config.layout.background_sampling:
            return {}
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n
        )[:, :, :3]
        result: dict[str, tuple[float, float, float]] = {}
        for region in regions:
            x0 = max(0, min(pixmap.width - 1, math.floor(region.box.x0)))
            x1 = max(x0 + 1, min(pixmap.width, math.ceil(region.box.x1)))
            y0 = max(0, min(pixmap.height - 1, math.floor(region.box.y0)))
            y1 = max(y0 + 1, min(pixmap.height, math.ceil(region.box.y1)))
            samples: list[np.ndarray] = []
            margin = 2
            if y0 > 0:
                samples.append(pixels[max(0, y0 - margin) : y0, x0:x1])
            if y1 < pixmap.height:
                samples.append(pixels[y1 : min(pixmap.height, y1 + margin), x0:x1])
            if x0 > 0:
                samples.append(pixels[y0:y1, max(0, x0 - margin) : x0])
            if x1 < pixmap.width:
                samples.append(pixels[y0:y1, x1 : min(pixmap.width, x1 + margin)])
            usable = [sample.reshape(-1, 3) for sample in samples if sample.size]
            if usable:
                rgb = np.median(np.concatenate(usable, axis=0), axis=0) / 255
                result[region.id] = tuple(float(channel) for channel in rgb)  # type: ignore[assignment]
        return result

    def _insert_fitted_text(self, page: fitz.Page, region: TextRegion, value: str) -> None:
        page_box = _box(page.rect)
        target = _clip_box(region.box.expanded(self.config.layout.box_padding), page_box)
        rect = fitz.Rect(target.x0, target.y0, target.x1, target.y1)
        preferred_size = min(
            self.config.layout.maximum_font_size,
            max(self.config.layout.minimum_font_size, region.font_size),
        )
        alignment = {"left": "left", "center": "center", "right": "right"}[region.alignment]
        escaped = html.escape(value).replace("\n", "<br>")
        font_family = "sans-serif"
        archive = None
        css_font = ""
        if self.config.layout.font_file:
            font_path = self.config.layout.font_file
            if not font_path.is_file():
                raise FileNotFoundError(f"Configured font file does not exist: {font_path}")
            archive = fitz.Archive(str(font_path.parent))
            font_family = "TranslationFont"
            css_font = (
                f'@font-face {{font-family: TranslationFont; src: url("{font_path.name}");}}'
            )
        css = f"""{css_font}
            * {{font-family: {font_family};}}
            p {{margin: 0; padding: 0; color: {_hex_color(region.color)};
                font-size: {preferred_size}pt; line-height: {self.config.layout.line_height};
                text-align: {alignment};}}
        """
        _, scale = page.insert_htmlbox(
            rect,
            f"<p>{escaped}</p>",
            css=css,
            archive=archive,
            scale_low=0,
            overlay=True,
        )
        actual_size = preferred_size * scale
        if actual_size < self.config.layout.minimum_font_size:
            LOG.warning(
                "Region %s needed %.1fpt text to fit below configured minimum %.1fpt",
                region.id,
                actual_size,
                self.config.layout.minimum_font_size,
            )

    @staticmethod
    def _validate_output(path: Path, expected_pages: int) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("Translated PDF was not written")
        check = fitz.open(path)
        try:
            if check.page_count != expected_pages:
                raise RuntimeError(
                    f"Translated PDF page count changed: {expected_pages} -> {check.page_count}"
                )
            for page in check:
                _ = page.rect
        finally:
            check.close()


def atomic_translate(
    engine: PdfTranslationEngine, source: Path, output: Path, state_dir: Path
) -> dict[str, object]:
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = state_dir / f"{output.name}.{os.getpid()}.partial.pdf"
    try:
        metrics = engine.translate(source, temporary)
        output.parent.mkdir(parents=True, exist_ok=True)
        LOG.info("Promoting validated PDF to final output: %s", output)
        os.replace(temporary, output)
        LOG.info("Final translated PDF saved: %s", output)
        return metrics
    finally:
        if temporary.exists():
            temporary.unlink()
