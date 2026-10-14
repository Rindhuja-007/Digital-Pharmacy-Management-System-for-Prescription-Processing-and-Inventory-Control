"""PaddleOCR wrapper. The engine is loaded lazily on first use (model download/startup is slow).
Tests monkeypatch `run_ocr`, so they never need Paddle models."""
import threading
from inspect import signature
from pathlib import Path

from ..errors import AppError

_engine = None
_load_lock = threading.Lock()
_infer_lock = threading.Lock()  # Paddle inference is not guaranteed thread-safe


def _get_engine():
    global _engine
    with _load_lock:
        if _engine is None:
            try:
                import paddle

                paddle.set_flags({
                    "FLAGS_use_mkldnn": False,
                    "FLAGS_use_onednn": False,
                })

                from paddleocr import PaddleOCR
            except ImportError as e:
                raise AppError(
                    503,
                    "OCR engine is not installed (pip install paddlepaddle paddleocr)",
                ) from e

            try:
                # PaddleOCR 3.x renamed the orientation options and no longer
                # accepts the 2.x constructor arguments.
                options = {"lang": "en"}
                parameters = signature(PaddleOCR).parameters
                if "use_angle_cls" in parameters:
                    options.update(use_angle_cls=True, enable_mkldnn=False)
                else:
                    options.update(
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=True,
                        enable_mkldnn=False,
                    )
                _engine = PaddleOCR(**options)
            except Exception as e:
                raise AppError(
                    503,
                    "OCR engine could not be started. Check that the PaddleOCR models "
                    "are available to the deployment.",
                ) from e
    return _engine

def _collect(result) -> tuple[list[str], list[float]]:
    """Understands both PaddleOCR 2.x ([[box, (text, conf)], ...]) and 3.x (dicts with rec_texts/rec_scores)."""
    texts: list[str] = []
    confs: list[float] = []
    for page in result or []:
        if page is None:
            continue
        if hasattr(page, "get") and page.get("rec_texts") is not None:
            texts += [str(t) for t in page["rec_texts"]]
            confs += [float(s) for s in page.get("rec_scores", [])]
        else:
            for line in page:
                text, conf = line[1]
                texts.append(str(text))
                confs.append(float(conf))
    return texts, confs


def run_ocr(image_path: str | Path) -> tuple[str, float]:
    """Returns (text joined by newlines, mean confidence as a percentage 0-100)."""
    engine = _get_engine()
    try:
        with _infer_lock:
            if hasattr(engine, "predict"):
                result = engine.predict(str(image_path))
            else:
                result = engine.ocr(str(image_path), cls=True)
    except Exception as e:
        raise AppError(
            503,
            "OCR could not process this image. Check the image and OCR service logs.",
        ) from e
    texts, confs = _collect(result)
    mean = round(sum(confs) / len(confs) * 100, 2) if confs else 0.0
    return "\n".join(texts), mean
