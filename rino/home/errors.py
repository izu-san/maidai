from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HomeError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def result_error(error: HomeError) -> dict:
    return {"success": False, "data": None, "error": {"code": error.code, "message": error.message}}
