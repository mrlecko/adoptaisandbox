"""
Executor interface for sandboxed run backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Executor(ABC):
    @abstractmethod
    def submit_run(self, payload: Dict[str, Any], query_type: str = "sql") -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_status(self, run_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def cleanup(self, run_id: str) -> None:
        raise NotImplementedError
