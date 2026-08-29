"""Scripted provider for tests and ``--dry-run`` modes (#010).

``MockProvider`` replays canned replies in order and records every
request it receives. When the script is exhausted it repeats the last
reply, so open-ended loops (the interview conversation) stay
deterministic without knowing the turn count in advance.
"""

from __future__ import annotations

from experienceos.ai.provider import Message


class MockProvider:
    """A provider that never touches the network."""

    name = "mock"

    def __init__(self, *replies: str) -> None:
        if not replies:
            raise ValueError("MockProvider needs at least one scripted reply")
        self._replies: list[str] = list(replies)
        self._cursor = 0
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> str:
        self.calls.append(list(messages))
        reply = self._replies[min(self._cursor, len(self._replies) - 1)]
        self._cursor += 1
        return reply

    @property
    def replies_used(self) -> int:
        return self._cursor
