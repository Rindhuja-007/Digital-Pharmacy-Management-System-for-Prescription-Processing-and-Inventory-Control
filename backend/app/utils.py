from decimal import Decimal
from typing import Any


def money_json(obj: Any) -> Any:
    """Recursively turn Decimals into 2-dp strings so FastAPI never serialises money as float."""
    if isinstance(obj, Decimal):
        return str(obj.quantize(Decimal("0.01")))
    if isinstance(obj, dict):
        return {k: money_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [money_json(v) for v in obj]
    return obj
