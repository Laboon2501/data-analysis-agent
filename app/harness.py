"""Application harness for building initial state and rule-based routing."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import Field

from llm.base import LLMClient
from llm.config import ModelConfig
from llm.openai_compatible import OpenAICompatibleClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import NodeStrategy
from nodes.router import route as route_node
from schemas._base import StrictBaseModel
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.analysis_package import AnalysisPackage
from schemas.analysis_plan import AnalysisPlan
from schemas.chart import ChartSpec
from schemas.context_summary import AgentContextSummary
from schemas.direct_analysis import QuestionInterpretation
from schemas.query_result import QueryResult
from schemas.report import ReportOutline
from schemas.router import RouterDecision
from schemas.sql import SqlDraft

if TYPE_CHECKING:
    from mcp.manager import MCPManager

CONFIRM_COMMANDS: frozenset[AgentCommand] = frozenset(
    {
        AgentCommand.REPORT_CONFIRM,
        AgentCommand.PPT_CONFIRM,
        AgentCommand.EXCEL_CONFIRM,
        AgentCommand.DASHBOARD_CONFIRM,
    }
)

NODE_STRATEGY_ALIASES: dict[str, tuple[str, ...]] = {
    "router": ("route",),
    "route": ("route",),
    "planner": ("interpret_question", "make_analysis_plan"),
    "analysis_planner": ("interpret_question", "make_analysis_plan"),
    "interpret_question": ("interpret_question",),
    "make_analysis_plan": ("make_analysis_plan",),
    "sql_drafter": ("draft_sql",),
    "draft_sql": ("draft_sql",),
    "insight_writer": ("generate_insight",),
    "generate_insight": ("generate_insight",),
}


class LLMNodeStrategyConfig(StrictBaseModel):
    """Optional per-node LLM rollout configuration."""

    enabled_nodes: list[str] = Field(default_factory=list)


def build_initial_state(
    *,
    session_id: str,
    user_message: str,
    datasource_id: str | None = None,
    command: AgentCommand | str = AgentCommand.NONE,
    job_id: str | None = None,
    analysis_package: AnalysisPackage | None = None,
    report_outline: ReportOutline | None = None,
    response_language: str = "zh-CN",
    last_user_question: str | None = None,
    last_question_interpretation: QuestionInterpretation | None = None,
    last_analysis_plan: AnalysisPlan | None = None,
    last_sql_draft: SqlDraft | None = None,
    last_sql_result: QueryResult | None = None,
    last_chart_spec: ChartSpec | None = None,
    context_summary: AgentContextSummary | None = None,
    llm_client: LLMClient | None = None,
    model_config: ModelConfig | None = None,
    prompt_loader: PromptLoader | None = None,
    route_strategy: NodeStrategy = "rule",
    llm_strategy_config: LLMNodeStrategyConfig | None = None,
    mcp_manager: MCPManager | None = None,
) -> AgentState:
    """Create an AgentState and route it using deterministic app-level rules."""

    _ = mcp_manager
    normalized_command = normalize_command(command)
    active_route_strategy = strategy_for_configured_node(
        "route",
        default_strategy=route_strategy,
        llm_strategy_config=llm_strategy_config,
    )
    state = AgentState(
        session_id=session_id,
        job_id=job_id or str(uuid4()),
        user_message=user_message,
        response_language=response_language,
        command=normalized_command,
        datasource_id=datasource_id,
        context_summary=context_summary,
        analysis_package=analysis_package,
        report_outline=report_outline,
        last_user_question=last_user_question,
        last_question_interpretation=last_question_interpretation,
        last_analysis_plan=last_analysis_plan,
        last_sql_draft=last_sql_draft,
        last_sql_result_summary=_query_result_summary(last_sql_result),
        last_chart_spec=last_chart_spec,
        is_followup_correction=_is_followup_correction(user_message),
    )
    return route_initial_state(
        state,
        strategy=active_route_strategy,
        llm_client=_resolve_llm_client(
            strategy=active_route_strategy,
            llm_client=llm_client,
            model_config=model_config,
        ),
        prompt_loader=prompt_loader,
    )


def route_initial_state(
    state: AgentState,
    *,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    model_config: ModelConfig | None = None,
    prompt_loader: PromptLoader | None = None,
    llm_strategy_config: LLMNodeStrategyConfig | None = None,
    mcp_manager: MCPManager | None = None,
) -> AgentState:
    """Set intent and command with rule default and optional LLM routing."""

    _ = mcp_manager
    active_strategy = strategy_for_configured_node(
        "route",
        default_strategy=strategy,
        llm_strategy_config=llm_strategy_config,
    )
    active_llm_client = _resolve_llm_client(
        strategy=active_strategy,
        llm_client=llm_client,
        model_config=model_config,
    )
    if state.command in CONFIRM_COMMANDS:
        state.intent = AgentIntent.REPORT_EXPORT
        return _record_rule_route(state, reason="Confirm command fast-path.")
    if state.command is AgentCommand.PROFILE:
        state.intent = AgentIntent.CONTEXT_MANAGER
        return _record_rule_route(state, reason="Explicit profile command.")
    if state.command is AgentCommand.EXPLORE:
        state.intent = AgentIntent.OPEN_EXPLORATION
        return _record_rule_route(state, reason="Explicit explore command.")
    if state.command is AgentCommand.SCHEMA_QA:
        state.intent = AgentIntent.SCHEMA_QA
        return _record_rule_route(state, reason="Explicit schema QA command.")
    if state.command is AgentCommand.REPORT:
        state.intent = AgentIntent.REPORT_EXPORT
        return _record_rule_route(state, reason="Explicit report command.")
    if state.command is AgentCommand.ANALYZE:
        _, inferred_intent = infer_command_and_intent(state.user_message)
        if inferred_intent is AgentIntent.SCHEMA_QA:
            state.command = AgentCommand.SCHEMA_QA
            state.intent = AgentIntent.SCHEMA_QA
            return _record_rule_route(state, reason="Analyze command corrected to schema QA.")
        if inferred_intent is AgentIntent.CLARIFICATION:
            state.command = AgentCommand.NONE
            state.intent = AgentIntent.CLARIFICATION
            return _record_rule_route(state, reason="Analyze command corrected to clarification.")
        state.intent = AgentIntent.DIRECT_ANALYSIS
        return _record_rule_route(state, reason="Explicit analyze command.")

    inferred_command, inferred_intent = infer_command_and_intent(state.user_message)
    if _is_rule_guarded_intent(inferred_command, inferred_intent, state.user_message):
        state.command = inferred_command
        state.intent = inferred_intent
        return _record_rule_route(state, reason="Rule guard handled routing.")

    if active_strategy == "llm":
        return route_node(
            state,
            strategy="llm",
            llm_client=active_llm_client,
            prompt_loader=prompt_loader,
        )

    if state.is_followup_correction and state.last_question_interpretation is not None:
        state.command = AgentCommand.ANALYZE
        state.intent = AgentIntent.DIRECT_ANALYSIS
        return _record_rule_route(
            state,
            reason="Follow-up correction reused prior analysis context.",
        )

    state.command = inferred_command
    state.intent = inferred_intent
    return _record_rule_route(state, reason="Rule router inferred workflow.")


def infer_command_and_intent(user_message: str) -> tuple[AgentCommand, AgentIntent]:
    """Infer a workflow from simple user-message keywords."""

    lowered_message = user_message.casefold().strip()
    confirm_keyword_commands = {
        "ppt_confirm": AgentCommand.PPT_CONFIRM,
        "report_confirm": AgentCommand.REPORT_CONFIRM,
        "excel_confirm": AgentCommand.EXCEL_CONFIRM,
        "dashboard_confirm": AgentCommand.DASHBOARD_CONFIRM,
    }
    for keyword, command in confirm_keyword_commands.items():
        if keyword in lowered_message:
            return command, AgentIntent.REPORT_EXPORT
    if _is_cancel_or_stop_request(lowered_message) or _is_write_operation_request(lowered_message):
        return AgentCommand.NONE, AgentIntent.CLARIFICATION
    if _is_schema_qa_request(lowered_message):
        return AgentCommand.SCHEMA_QA, AgentIntent.SCHEMA_QA
    if _is_open_exploration_request(lowered_message):
        return AgentCommand.EXPLORE, AgentIntent.OPEN_EXPLORATION
    if _contains_any(
        lowered_message,
        (
            "report",
            "ppt",
            "excel",
            "dashboard",
            "export",
            "outline",
            "报告",
            "报表",
            "导出",
            "生成报告",
            "生成报表",
            "大纲",
            "看板",
            "仪表盘",
        ),
    ):
        return AgentCommand.REPORT, AgentIntent.REPORT_EXPORT
    if _contains_any(
        lowered_message,
        (
            "schema",
            "profile",
            "context",
            "table structure",
            "database schema",
            "field",
            "表结构",
            "字段",
        ),
    ):
        return AgentCommand.PROFILE, AgentIntent.CONTEXT_MANAGER
    if (
        _is_greeting_or_help(lowered_message)
        or _is_model_status_question(lowered_message)
        or not _has_data_analysis_intent(lowered_message)
    ):
        return AgentCommand.NONE, AgentIntent.CLARIFICATION
    return AgentCommand.ANALYZE, AgentIntent.DIRECT_ANALYSIS


def normalize_command(command: AgentCommand | str) -> AgentCommand:
    """Normalize external command input into the AgentCommand enum."""

    return command if isinstance(command, AgentCommand) else AgentCommand(command)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    """Return whether any token appears in text."""

    return any(token in text for token in tokens)


def _is_rule_guarded_intent(
    command: AgentCommand,
    intent: AgentIntent,
    user_message: str,
) -> bool:
    """Return whether routing must stay on deterministic safety rails."""

    lowered_message = user_message.casefold().strip()
    return (
        command in CONFIRM_COMMANDS
        or intent is AgentIntent.REPORT_EXPORT
        or intent is AgentIntent.SCHEMA_QA
        or _is_greeting_or_help(lowered_message)
        or _is_model_status_question(lowered_message)
        or _is_cancel_or_stop_request(lowered_message)
        or _is_write_operation_request(lowered_message)
    )


def _record_rule_route(
    state: AgentState,
    *,
    reason: str,
) -> AgentState:
    """Record rule router metadata without changing workflow behavior."""

    state.router_decision = RouterDecision(
        intent=state.intent.value,
        confidence=1.0,
        reason=reason,
        needs_datasource=state.intent
        in {
            AgentIntent.CONTEXT_MANAGER,
            AgentIntent.DIRECT_ANALYSIS,
            AgentIntent.OPEN_EXPLORATION,
            AgentIntent.REPORT_EXPORT,
            AgentIntent.SCHEMA_QA,
        },
        is_followup=state.is_followup_correction,
        referenced_previous_context=bool(state.last_user_question),
        source="rule",
        command=state.command.value,
    )
    return state


def _is_greeting_or_help(text: str) -> bool:
    """判断消息是否属于问候或帮助，而不是数据分析请求。"""

    compact_text = text.strip().strip(".,!?;:，。！？；：~～ ")
    if compact_text in {
        "hi",
        "hello",
        "hey",
        "help",
        "你好",
        "您好",
        "在吗",
        "帮助",
    }:
        return True
    return _contains_any(compact_text, ("你能做什么", "能做什么", "怎么用", "如何使用"))


def _is_cancel_or_stop_request(text: str) -> bool:
    """Detect plain stop/cancel messages that should not enter analysis."""

    compact_text = text.strip().strip(".,!?;:，。！？；：")
    return compact_text in {"cancel", "stop", "取消", "停止", "停下"}


def _is_write_operation_request(text: str) -> bool:
    """Keep dangerous write requests out of LLM and SQL workflows."""

    return _contains_any(
        text,
        (
            "delete from",
            "drop table",
            "update ",
            "insert into",
            "alter table",
            "truncate",
            "create table",
            "grant ",
            "revoke ",
            "删除表",
            "删除数据",
            "更新数据",
            "写入数据",
            "新建表",
            "建表",
            "清空表",
            "修改表",
        ),
    )


def _is_model_status_question(text: str) -> bool:
    """Return whether the user is asking about the current model, not data."""

    return _contains_any(
        text,
        (
            "\u4ec0\u4e48\u6a21\u578b",
            "\u54ea\u4e2a\u6a21\u578b",
            "\u5f53\u524d\u6a21\u578b",
            "\u7528\u7684\u4ec0\u4e48\u6a21\u578b",
            "\u4f60\u662fdeepseek",
            "\u4f60\u662f deepseek",
            "deepseek\u5417",
            "model",
            "provider",
        ),
    )


def _is_followup_correction(text: str) -> bool:
    """Return whether the user is correcting or refining the prior analysis intent."""

    lowered = text.casefold().strip()
    return _contains_any(
        lowered,
        (
            "不是",
            "不对",
            "我的意思是",
            "应该是",
            "刚才那个问题",
            "刚才的问题",
            "换成",
            "改成",
            "不是的",
            "i mean",
            "not",
            "instead",
            "change to",
        ),
    )


def _query_result_summary(
    sql_result: QueryResult | None,
) -> dict[str, int | float | str | None] | None:
    """Keep only bounded SQL result metadata for follow-up context."""

    if sql_result is None:
        return None
    return {
        "row_count": sql_result.row_count,
        "column_count": len(sql_result.columns),
        "first_column": sql_result.columns[0].name if sql_result.columns else None,
    }


def _is_open_exploration_request(text: str) -> bool:
    """判断用户是否请求对数据源做开放探索。"""

    if _contains_any(text, ("explore", "exploration", "open analysis")):
        return True
    return _contains_any(
        text,
        (
            "有什么可以分析",
            "有什么能分析",
            "可以分析什么",
            "探索性地",
            "探索性分析",
            "探索分析",
            "帮我分析一下这个数据",
            "帮我分析一下这张表",
            "自动分析",
            "自动探索",
            "看看有什么发现",
            "有什么发现",
            "有什么问题",
            "有什么趋势",
            "有什么亮点",
            "看看这个数据库",
            "看看这个数据",
            "开放探索",
        ),
    )


def _is_schema_qa_request(text: str) -> bool:
    """判断用户是否在询问数据源字段、列、指标或维度说明。"""

    explicit_field_tokens = (
        "字段",
        "列",
        "表头",
        "有哪些字段",
        "字段告诉我",
        "包含什么字段",
        "什么字段",
        "哪些字段",
        "字段是什么意思",
        "每个字段",
        "这张表",
        "这个表",
        "数据文件",
        "上传的文件",
        "field",
        "fields",
        "column",
        "columns",
        "schema qa",
        "data inspection",
    )
    if not _contains_any(text, explicit_field_tokens):
        return False
    if _is_open_exploration_request(text) and not _contains_any(
        text,
        (
            "字段",
            "列",
            "表头",
            "有哪些列",
            "有哪些字段",
            "字段告诉我",
            "字段是什么意思",
            "包含什么字段",
            "field",
            "fields",
            "column",
            "columns",
        ),
    ):
        return False
    return _contains_any(
        text,
        (
            "有哪些",
            "有什么",
            "告诉我",
            "说明",
            "意思",
            "可以分析",
            "指标",
            "维度",
            "上传",
            "文件",
            "表",
            "field",
            "fields",
            "column",
            "columns",
        ),
    )


def _has_data_analysis_intent(text: str) -> bool:
    """判断消息是否包含明确的数据分析意图信号。"""

    return _contains_any(
        text,
        (
            "revenue",
            "sales",
            "gmv",
            "trend",
            "top",
            "total",
            "sum",
            "average",
            "avg",
            "highest",
            "largest",
            "unit price",
            "price",
            "count",
            "order",
            "orders",
            "customer",
            "customers",
            "category",
            "product",
            "region",
            "channel",
            "monthly",
            "compare",
            "ranking",
            "metric",
            "销售",
            "收入",
            "营收",
            "趋势",
            "订单",
            "订单量",
            "品类",
            "商品",
            "产品",
            "地区",
            "渠道",
            "客户",
            "用户",
            "金额",
            "数量",
            "汇总",
            "总额",
            "平均",
            "单价",
            "均价",
            "最高",
            "最大",
            "排名",
            "前",
            "同比",
            "环比",
            "分布",
            "指标",
        ),
    )


def build_node_strategy_map(
    llm_strategy_config: LLMNodeStrategyConfig | None,
) -> dict[str, NodeStrategy]:
    """Convert app rollout config into graph node strategy names."""

    if llm_strategy_config is None:
        return {}
    node_strategies: dict[str, NodeStrategy] = {}
    for enabled_node in llm_strategy_config.enabled_nodes:
        for graph_node in NODE_STRATEGY_ALIASES.get(enabled_node, (enabled_node,)):
            node_strategies[graph_node] = "llm"
    return node_strategies


def strategy_for_configured_node(
    node_name: str,
    *,
    default_strategy: NodeStrategy = "rule",
    llm_strategy_config: LLMNodeStrategyConfig | None = None,
) -> NodeStrategy:
    """Return the rollout strategy for one named node."""

    return build_node_strategy_map(llm_strategy_config).get(node_name, default_strategy)


def _resolve_llm_client(
    *,
    strategy: NodeStrategy,
    llm_client: LLMClient | None,
    model_config: ModelConfig | None,
) -> LLMClient | None:
    """Build a real provider client only when LLM strategy is explicitly requested."""

    if llm_client is not None or strategy != "llm" or model_config is None:
        return llm_client
    if model_config.provider != "openai_compatible":
        raise ValueError(f"Unsupported LLM provider: {model_config.provider}")
    return OpenAICompatibleClient(model_config)
