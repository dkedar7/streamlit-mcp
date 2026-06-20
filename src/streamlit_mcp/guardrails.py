"""Guardrails: bound what an agent (or human) can do, uniformly across MCP and CLI.

Three controls (origin R11):
  - read-only mode      -> reject state-changing tools (set_widget / click)
  - allow-list          -> only listed widgets are visible / settable
  - bearer token        -> gate the HTTP/SSE transport (stdio is local, no token)

The engine consults ``can_write`` / ``is_allowed`` / ``filter_widgets`` so both surfaces
enforce identically. ``check_bearer`` / ``require_bearer`` are the auth primitives the HTTP
transport applies to incoming requests.
"""

from __future__ import annotations

import hmac
from typing import Optional


class Guardrails:
    def __init__(
        self,
        read_only: bool = False,
        allow_list: Optional[set[str]] = None,
        bearer_token: Optional[str] = None,
    ):
        self.read_only = read_only
        self.allow_list = set(allow_list) if allow_list is not None else None
        self.bearer_token = bearer_token

    @classmethod
    def allow_all(cls) -> "Guardrails":
        return cls()

    # ---------------------------------------------------------- engine hooks
    def can_write(self) -> bool:
        return not self.read_only

    def is_allowed(self, identifier: str) -> bool:
        return self.allow_list is None or identifier in self.allow_list

    def filter_widgets(self, models: list[dict]) -> list[dict]:
        if self.allow_list is None:
            return models
        return [
            m for m in models
            if m.get("identifier") in self.allow_list or m.get("label") in self.allow_list
        ]

    # ------------------------------------------------------------- http auth
    def check_bearer(self, token: Optional[str]) -> bool:
        """True if no token is configured, or the provided token matches (constant-time)."""
        if not self.bearer_token:
            return True
        if not token:
            return False
        return hmac.compare_digest(token, self.bearer_token)

    def require_bearer(self, authorization_header: Optional[str]) -> bool:
        """Validate an HTTP ``Authorization: Bearer <token>`` header."""
        if not self.bearer_token:
            return True
        if not authorization_header:
            return False
        parts = authorization_header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return self.check_bearer(parts[1].strip())
