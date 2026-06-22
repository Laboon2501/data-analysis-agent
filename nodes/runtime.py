"""Runtime wrapper shared by future LangGraph nodes."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from time import perf_counter

from guards.cancel_policy import CancelPolicy
from guards.retry_policy import RetryPolicy
from guards.timeout_policy import TimeoutPolicy
from schemas._base import utc_now
from schemas.agent_state import AgentState
from schemas.errors import AgentError
from schemas.event import AgentEvent, EventType
from schemas.timing import TimingRecord

NodeCallable = Callable[[AgentState], AgentState]
PROGRESS_MESSAGES: dict[str, str] = {
    "route": "正在理解问题...",
    "ensure_database_profile": "正在读取数据源画像...",
    "interpret_question": "正在理解问题...",
    "make_analysis_plan": "正在生成分析计划...",
    "draft_sql": "正在生成并校验 SQL...",
    "validate_sql": "正在生成并校验 SQL...",
    "risk_check_sql": "正在生成并校验 SQL...",
    "execute_sql": "正在执行查询...",
    "check_result": "正在检查查询结果...",
    "repair_sql_if_needed": "正在检查查询结果...",
    "decide_chart": "正在生成图表和结论...",
    "generate_chart_artifact": "正在生成图表和结论...",
    "generate_insight": "正在生成图表和结论...",
    "build_analysis_package": "正在整理分析结果...",
    "answer_schema_question": "正在整理字段说明...",
    "final_response": "正在整理最终回答...",
}


class NodeRuntimeError(RuntimeError):
    """Base exception for node runtime failures."""


class NodeCancelledError(NodeRuntimeError):
    """Raised when a cancel flag is set before or between node attempts."""


class NodeTimeoutError(NodeRuntimeError):
    """Raised when a node exceeds its configured timeout."""


class NodeExecutionError(NodeRuntimeError):
    """Raised when a node fails after exhausting retry attempts."""


def run_node_with_runtime(
    *,
    state: AgentState,
    node_name: str,
    node_fn: NodeCallable,
    retry_policy: RetryPolicy | None = None,
    timeout_policy: TimeoutPolicy | None = None,
    cancel_policy: CancelPolicy | None = None,
) -> AgentState:
    """Run one node with events, retry limits, timeout, cancel, and errors."""

    active_retry_policy = retry_policy or RetryPolicy()
    active_timeout_policy = timeout_policy or TimeoutPolicy()
    _raise_if_cancelled(state, node_name, cancel_policy)
    progress_message = PROGRESS_MESSAGES.get(node_name)
    if progress_message is not None:
        _append_event(state, EventType.TEXT_DELTA, node_name=node_name, message=progress_message)
    started_at = utc_now()
    started_perf = perf_counter()
    _append_event(
        state,
        EventType.NODE_START,
        node_name=node_name,
        payload={"started_at": started_at.isoformat()},
    )

    max_attempts = active_retry_policy.max_attempts_for(node_name)
    timeout_seconds = active_timeout_policy.timeout_for(node_name)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        _raise_if_cancelled(state, node_name, cancel_policy)
        try:
            result_state = _run_with_timeout(node_fn, state, timeout_seconds)
            if not isinstance(result_state, AgentState):
                raise TypeError(f"Node '{node_name}' must return AgentState.")
            _merge_runtime_state(source_state=state, target_state=result_state)
            duration_ms = _duration_ms(started_perf)
            _append_timing_record(
                result_state,
                node_name=node_name,
                started_at=started_at,
                duration_ms=duration_ms,
                status="completed",
                retry_attempt=attempt,
                metadata=_node_timing_metadata(node_name, result_state),
            )
            _append_event(
                result_state,
                EventType.NODE_END,
                node_name=node_name,
                payload={
                    "duration_ms": duration_ms,
                    "status": "completed",
                    "retry_attempt": attempt,
                    **_node_timing_metadata(node_name, result_state),
                },
            )
            return result_state
        except Exception as exc:  # noqa: PERF203 - retry accounting needs this branch.
            last_error = exc
            retryable = attempt < max_attempts
            duration_ms = _duration_ms(started_perf)
            _append_timing_record(
                state,
                node_name=node_name,
                started_at=started_at,
                duration_ms=duration_ms,
                status="retrying" if retryable else "failed",
                retry_attempt=attempt,
                metadata={"error_type": exc.__class__.__name__},
            )
            state.retry_count_by_node[node_name] = state.retry_count_by_node.get(node_name, 0) + 1
            _record_error(
                state=state,
                node_name=node_name,
                exc=exc,
                retryable=retryable,
                attempt=attempt,
                max_attempts=max_attempts,
            )
            if not retryable:
                break

    runtime_error = NodeExecutionError(
        f"Node '{node_name}' failed after {max_attempts} attempt(s)."
    )
    runtime_error.state = state
    raise runtime_error from last_error


def _run_with_timeout(
    node_fn: NodeCallable,
    state: AgentState,
    timeout_seconds: float | None,
) -> AgentState:
    """Run a node callable, optionally enforcing a timeout."""

    if timeout_seconds is None:
        return node_fn(state)

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(node_fn, state)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise NodeTimeoutError(f"Node exceeded timeout of {timeout_seconds} seconds.") from exc
    finally:
        executor.shutdown(wait=not future.running(), cancel_futures=True)


def _raise_if_cancelled(
    state: AgentState,
    node_name: str,
    cancel_policy: CancelPolicy | None,
) -> None:
    """Raise and record a cancellation when the active job has a cancel flag."""

    if cancel_policy is None or not cancel_policy.is_cancelled(state.job_id):
        return

    error = AgentError(
        code="node_cancelled",
        message=f"Node '{node_name}' was cancelled before execution.",
        node_name=node_name,
        retryable=False,
    )
    state.errors.append(error)
    state.error_count += 1
    _append_event(
        state,
        EventType.STOPPED,
        node_name=node_name,
        message=error.message,
        payload={"error_id": error.error_id},
    )
    raise NodeCancelledError(error.message)


def _record_error(
    *,
    state: AgentState,
    node_name: str,
    exc: Exception,
    retryable: bool,
    attempt: int,
    max_attempts: int,
) -> None:
    """Write a structured error and matching event into AgentState."""

    error_details: dict[str, object] = {"attempt": attempt, "max_attempts": max_attempts}
    structured_details = getattr(exc, "details", None)
    if isinstance(structured_details, dict):
        error_details["details"] = structured_details

    error = AgentError(
        code=_error_code_for_exception(exc),
        message=str(exc),
        node_name=node_name,
        retryable=retryable,
        details=error_details,
    )
    state.errors.append(error)
    state.error_count += 1
    _append_event(
        state,
        EventType.ERROR,
        node_name=node_name,
        message=error.message,
        payload={
            "error_id": error.error_id,
            "code": error.code,
            "retryable": retryable,
            "attempt": attempt,
            "max_attempts": max_attempts,
        },
    )


def _error_code_for_exception(exc: Exception) -> str:
    """Map runtime exceptions into stable error codes."""

    structured_code = getattr(exc, "error_code", None)
    if isinstance(structured_code, str) and structured_code:
        return structured_code
    if isinstance(exc, NodeTimeoutError):
        return "node_timeout"
    if isinstance(exc, TypeError):
        return "node_invalid_return"
    return "node_execution_error"


def _append_event(
    state: AgentState,
    event_type: EventType,
    *,
    node_name: str,
    message: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    """Append a node-scoped runtime event to state."""

    state.events.append(
        AgentEvent(
            event_type=event_type,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name=node_name,
            message=message,
            payload=payload or {},
        )
    )


def _append_timing_record(
    state: AgentState,
    *,
    node_name: str,
    started_at: datetime,
    duration_ms: float,
    status: str,
    retry_attempt: int,
    metadata: dict[str, object] | None = None,
) -> None:
    """Append one bounded timing record to AgentState."""

    state.timing_records.append(
        TimingRecord(
            node_name=node_name,
            started_at=started_at,
            ended_at=utc_now(),
            duration_ms=duration_ms,
            status=status,
            retry_attempt=retry_attempt,
            metadata=metadata or {},
        )
    )


def _duration_ms(started_perf: float) -> float:
    return round((perf_counter() - started_perf) * 1000, 3)


def _node_timing_metadata(node_name: str, state: AgentState) -> dict[str, object]:
    """Return small node-specific timing metadata without large payloads."""

    if node_name == "execute_sql" and state.sql_result is not None:
        return {"row_count": state.sql_result.row_count}
    if node_name in {"generate_chart_artifact", "final_response"} and state.chart_spec is not None:
        return {"artifact_ref": state.chart_spec.artifact_ref}
    if node_name.startswith("export") and state.report_result is not None:
        return {"artifact_ref": state.report_result.artifact_ref}
    return {}


def _merge_runtime_state(source_state: AgentState, target_state: AgentState) -> None:
    """Preserve runtime bookkeeping when a node returns a copied AgentState."""

    existing_event_ids = {event.event_id for event in target_state.events}
    missing_runtime_events = [
        event for event in source_state.events if event.event_id not in existing_event_ids
    ]
    if missing_runtime_events:
        target_state.events = [*missing_runtime_events, *target_state.events]

    existing_error_ids = {error.error_id for error in target_state.errors}
    missing_runtime_errors = [
        error for error in source_state.errors if error.error_id not in existing_error_ids
    ]
    if missing_runtime_errors:
        target_state.errors = [*missing_runtime_errors, *target_state.errors]
        target_state.error_count = max(target_state.error_count, source_state.error_count)

    for node_name, retry_count in source_state.retry_count_by_node.items():
        target_state.retry_count_by_node[node_name] = max(
            retry_count,
            target_state.retry_count_by_node.get(node_name, 0),
        )

    existing_timing_keys = {
        (
            timing.node_name,
            timing.started_at,
            timing.retry_attempt,
            timing.status,
        )
        for timing in target_state.timing_records
    }
    missing_timing = [
        timing
        for timing in source_state.timing_records
        if (
            timing.node_name,
            timing.started_at,
            timing.retry_attempt,
            timing.status,
        )
        not in existing_timing_keys
    ]
    if missing_timing:
        target_state.timing_records = [*missing_timing, *target_state.timing_records]
