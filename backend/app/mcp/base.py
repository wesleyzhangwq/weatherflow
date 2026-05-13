"""MCP connector abstract base.

Why "interface only" in MVP:
- We deliberately resist "MCP showmanship".
- The connectors that *do* matter long-term are listed in PHILOSOPHY.md:
  GitHub, Notes — surfaces of *real-world growth*, not toys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MCPConnector(ABC):
    name: str

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...

    @abstractmethod
    async def fetch(self, **kwargs: Any) -> Any: ...
