"""Preprocesamiento configurable de imágenes de boletas (OpenCV/Pillow).

Etapas: deskew, denoise, mejora de contraste (CLAHE), upscaling y binarización
opcional. Cada etapa se activa/desactiva desde config.yaml. También rasteriza
páginas de PDF a imágenes para que sigan el mismo camino de preprocesamiento.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import cv2
import numpy as np
from PIL import Image

PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def load_pages(file_path: Path, pdf_render_dpi: int = 300) -> List[Image.Image]:
    """Carga un archivo (imagen o PDF) como una lista de imágenes PIL (una por página)."""
    suffix = file_path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _render_pdf_pages(file_path, pdf_render_dpi)
    if suffix in IMAGE_SUFFIXES:
        return [Image.open(file_path).convert("RGB")]
    raise ValueError(f"Formato no soportado: {file_path}")


def _render_pdf_pages(file_path: Path, dpi: int) -> List[Image.Image]:
    import fitz  # PyMuPDF

    pages = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(file_path) as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix)
            mode = "RGB" if pix.n < 4 else "RGBA"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")
            pages.append(img)
    return pages


def _deskew(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return image

    angle = cv2.minAreaRect(coords)[-1]
    # cv2.minAreaRect devuelve ángulos en [-90, 0); normalizamos a una corrección pequeña.
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.1 or abs(angle) > 45:
        return image

    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    rot_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image, rot_matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _denoise(image: np.ndarray, strength: float) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(image, None, strength, strength, 7, 21)


def _enhance_contrast(image: np.ndarray, clip_limit: float, tile_grid_size: int) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_grid_size, tile_grid_size))
    l_channel = clahe.apply(l_channel)
    lab = cv2.merge((l_channel, a_channel, b_channel))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def _upscale(image: np.ndarray, min_dimension_px: int, target_dimension_px: int) -> np.ndarray:
    h, w = image.shape[:2]
    if min(h, w) >= min_dimension_px:
        return image
    scale = target_dimension_px / min(h, w)
    new_size = (int(w * scale), int(h * scale))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_CUBIC)


def _binarize(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2RGB)


def preprocess_image(image: Image.Image, config: dict) -> Image.Image:
    """Aplica el pipeline de preprocesamiento configurado a una imagen PIL y devuelve PIL."""
    cfg = config.get("preprocess", {})
    arr = np.array(image.convert("RGB"))

    if cfg.get("deskew", {}).get("enabled", True):
        arr = _deskew(arr)

    if cfg.get("denoise", {}).get("enabled", True):
        arr = _denoise(arr, cfg.get("denoise", {}).get("strength", 10))

    if cfg.get("contrast", {}).get("enabled", True):
        arr = _enhance_contrast(
            arr,
            cfg.get("contrast", {}).get("clahe_clip_limit", 2.0),
            cfg.get("contrast", {}).get("clahe_tile_grid_size", 8),
        )

    upscale_cfg = cfg.get("upscale", {})
    if upscale_cfg.get("enabled", True):
        arr = _upscale(
            arr,
            upscale_cfg.get("min_dimension_px", 1200),
            upscale_cfg.get("target_dimension_px", 1800),
        )

    if cfg.get("binarize", {}).get("enabled", False):
        arr = _binarize(arr)

    return Image.fromarray(arr)


def preprocess_file(file_path: Path, config: dict) -> List[Image.Image]:
    """Carga un archivo (imagen o PDF) y aplica el preprocesamiento a cada página."""
    dpi = config.get("preprocess", {}).get("pdf_render_dpi", 300)
    pages = load_pages(file_path, dpi)
    return [preprocess_image(page, config) for page in pages]
