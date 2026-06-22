"""Tests for node runtime wrapper behavior."""

from __future__ import annotations

from time import sleep

import pytest

from guards import InMemoryCancelPolicy, RetryPolicy, TimeoutPolicy
from nodes.runtime import (
    NodeCancelledError,
    NodeExecutionError,
    NodeTimeoutError,
    run_node_with_runtime,
)
from schemas import AgentState, EventType


def _state() -> AgentState:
    """Create a small runtime test state."""

    return AgentState(session_id="session-1", job_id="job-1", user_message="question")


def test_runtime_records_start_and_end_events_on_success() -> None:
    """Successful nodes should emit start and end events."""

    def node(state: AgentState) -> AgentState:
        return state

    result = run_node_with_runtime(state=_state(), node_name="test_node", node_fn=node)

    assert [event.event_type for event in result.events] == [
        EventType.NODE_START,
        EventType.NODE_END,
    ]
    assert result.error_count == 0


def test_runtime_retries_until_success_and_keeps_error_context() -> None:
    """A node should retry within its configured retry limit."""

    calls = {"count": 0}

    def flaky_node(state: AgentState) -> AgentState:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("temporary failure")
        return state

    result = run_node_with_runtime(
        state=_state(),
        node_name="flaky_node",
        node_fn=flaky_node,
        retry_policy=RetryPolicy(max_attempts_by_node={"flaky_node": 2}),
    )

    assert calls["count"] == 2
    assert result.retry_count_by_node["flaky_node"] == 1
    assert result.error_count == 1
    assert result.errors[0].retryable is True
    assert result.events[-1].event_type is EventType.NODE_END


def test_runtime_raises_after_retry_limit_and_records_structured_errors() -> None:
    """A node that keeps failing should not be converted into success."""

    state = _state()

    def failing_node(_: AgentState) -> AgentState:
        raise ValueError("permanent failure")

    with pytest.raises(NodeExecutionError):
        run_node_with_runtime(
            state=state,
            node_name="failing_node",
            node_fn=failing_node,
            retry_policy=RetryPolicy(max_attempts_by_node={"failing_node": 2}),
        )

    assert state.retry_count_by_node["failing_node"] == 2
    assert state.error_count == 2
    assert state.errors[-1].retryable is False
    assert state.events[-1].event_type is EventType.ERROR


def test_runtime_timeout_records_timeout_error() -> None:
    """Timeouts should be structured as node timeout errors."""

    state = _state()

    def slow_node(state: AgentState) -> AgentState:
        sleep(0.05)
        return state

    with pytest.raises(NodeExecutionError) as exc_info:
        run_node_with_runtime(
            state=state,
            node_name="slow_node",
            node_fn=slow_node,
            timeout_policy=TimeoutPolicy(timeout_seconds_by_node={"slow_node": 0.001}),
        )

    assert isinstance(exc_info.value.__cause__, NodeTimeoutError)
    assert state.errors[-1].code == "node_timeout"
    assert state.events[-1].event_type is EventType.ERROR


def test_runtime_cancel_check_stops_before_node_execution() -> None:
    """A cancel flag should stop the node before calling its function."""

    state = _state()
    cancel_policy = InMemoryCancelPolicy()
    cancel_policy.request_cancel(state.job_id)
    called = {"value": False}

    def node(state: AgentState) -> AgentState:
        called["value"] = True
        return state

    with pytest.raises(NodeCancelledError):
        run_node_with_runtime(
            state=state,
            node_name="cancelled_node",
            node_fn=node,
            cancel_policy=cancel_policy,
        )

    assert called["value"] is False
    assert state.error_count == 1
    assert state.errors[-1].code == "node_cancelled"
    assert state.events[-1].event_type is EventType.STOPPED
