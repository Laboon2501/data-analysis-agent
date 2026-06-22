"""Open exploration response summary regressions."""

from graphs.open_exploration_graph import build_open_exploration_graph
from persistence import InMemoryCacheStore
from schemas import AgentState


def test_open_exploration_final_response_lists_directions_and_exports(
    sqlite_data_source,
) -> None:
    """开放探索最终回答应包含方向、发现、追问和导出选项。"""

    graph = build_open_exploration_graph(
        data_source=sqlite_data_source,
        cache_store=InMemoryCacheStore(),
        top_n=3,
    )
    result = AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message="帮我看看这张表都有什么可以分析的",
                datasource_id=sqlite_data_source.datasource_id,
            )
        )
    )

    assert result.final_response_text is not None
    assert "已完成开放探索，自动分析了 3 个方向" in result.final_response_text
    assert "1." in result.final_response_text
    assert "2." in result.final_response_text
    assert "3." in result.final_response_text
    assert "可继续追问" in result.final_response_text
    assert "可导出" in result.final_response_text
    assert "completed" not in result.final_response_text.casefold()
