"""Node-level retry limit configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetryPolicy:
    """Resolve how many attempts a node may use before failing."""

    default_max_attempts: int = 1
    max_attempts_by_node: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configured retry limits."""

        if self.default_max_attempts < 1:
            raise ValueError("default_max_attempts must be at least 1.")
        invalid_nodes = [
            node_name
            for node_name, max_attempts in self.max_attempts_by_node.items()
            if max_attempts < 1
        ]
        if invalid_nodes:
            raise ValueError(f"Node retry attempts must be at least 1: {invalid_nodes}.")

    def max_attempts_for(self, node_name: str) -> int:
        """Return the configured max attempts for a node."""

        return self.max_attempts_by_node.get(node_name, self.default_max_attempts)
