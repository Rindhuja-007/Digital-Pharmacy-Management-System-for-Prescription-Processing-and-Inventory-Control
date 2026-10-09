"""Domain errors raised by services; converted to HTTP responses in main.py."""


class AppError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def not_found(what: str) -> AppError:
    return AppError(404, f"{what} not found")
