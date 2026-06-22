"""Node-level timeout configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TimeoutPolicy:
    """Resolve node timeout seconds without executing any business work."""

    default_timeout_seconds: float | None = None
    timeout_seconds_by_node: Mapping[str, float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate timeout values."""

        self._validate_timeout(self.default_timeout_seconds, "default_timeout_seconds")
        for node_name, timeout_seconds in self.timeout_seconds_by_node.items():
            self._validate_timeout(timeout_seconds, f"timeout_seconds_by_node[{node_name}]")

    def timeout_for(self, node_name: str) -> float | None:
        """Return the configured timeout for a node."""

        return self.timeout_seconds_by_node.get(node_name, self.default_timeout_seconds)

    @staticmethod
    def _validate_timeout(timeout_seconds: float | None, field_name: str) -> None:
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError(f"{field_name} must be positive when provided.")
