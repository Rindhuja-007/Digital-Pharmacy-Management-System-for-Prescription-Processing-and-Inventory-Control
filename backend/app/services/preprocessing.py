"""OpenCV preprocessing for OCR: resize -> grayscale -> denoise -> CLAHE -> Otsu threshold."""
from pathlib import Path

import cv2
import numpy as np

from ..errors import AppError

MAX_WIDTH = 1800
MAX_PIXELS = 50_000_000  # reject decompression bombs


def decode_image_bytes(data: bytes):
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise AppError(422, "File is not a readable JPG/PNG image")
    h, w = img.shape[:2]
    if h * w > MAX_PIXELS:
        raise AppError(422, "Image dimensions are too large")
    return img


def preprocess_array(img):
    h, w = img.shape[:2]
    if w > MAX_WIDTH:
        scale = MAX_WIDTH / w
        img = cv2.resize(img, (MAX_WIDTH, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def preprocess_image(src: Path, dst: Path) -> Path:
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise AppError(422, "Stored image could not be read")
    out = preprocess_array(img)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(dst), out):  # .png extension => PNG
        raise AppError(500, "Could not save the processed image")
    return dst
