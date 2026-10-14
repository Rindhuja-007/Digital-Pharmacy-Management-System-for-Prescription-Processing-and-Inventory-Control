import sys
import types

from app.services import ocr


def test_collects_paddleocr_v3_result():
    result = [{"rec_texts": ["Dolo 500", "1-0-1"], "rec_scores": [0.9, 0.8]}]

    assert ocr._collect(result) == (["Dolo 500", "1-0-1"], [0.9, 0.8])


def test_collects_paddleocr_v2_result():
    result = [[["box", ("Dolo 500", 0.9)], ["box", ("1-0-1", 0.8)]]]

    assert ocr._collect(result) == (["Dolo 500", "1-0-1"], [0.9, 0.8])


def test_uses_paddleocr_v3_constructor_options(monkeypatch):
    calls = []

    class PaddleOCR:
        def __init__(
            self,
            *,
            lang,
            use_doc_orientation_classify,
            use_doc_unwarping,
            use_textline_orientation,
            enable_mkldnn,
        ):
            calls.append({
                "lang": lang,
                "use_doc_orientation_classify": use_doc_orientation_classify,
                "use_doc_unwarping": use_doc_unwarping,
                "use_textline_orientation": use_textline_orientation,
                "enable_mkldnn": enable_mkldnn,
            })

    paddle = types.ModuleType("paddle")
    paddle.set_flags = lambda flags: None
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddle", paddle)
    monkeypatch.setitem(sys.modules, "paddleocr", paddleocr)
    monkeypatch.setattr(ocr, "_engine", None)

    ocr._get_engine()

    assert calls == [{
        "lang": "en",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": True,
        "enable_mkldnn": False,
    }]
