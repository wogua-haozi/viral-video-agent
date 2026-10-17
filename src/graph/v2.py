"""Architecture v2：确定性主流程 + 证据门禁。"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from src.agents.analyst import analyst_node
from src.agents.researcher import call_tool_via_mcp
from src.agents.supervisor import _direct_answer, extract_text, get_llm
from src.agents.writer import writer_node
from src.briefing.schemas import TopicSpec
from src.config import (
    ANALYSIS_CONFIDENCE_THRESHOLD,
    V2_ANALYST_MAX_ITERATIONS,
    V2_MIN_EVIDENCE_ITEMS,
)
from src.graph.state import AgentState
from src.memory.short_term import get_checkpointer
from src.prompts.manager import prompt_manager
from src.tools.capabilities import (
    ToolUnavailableError,
    capability_snapshot,
    normalize_tool_params,
    render_available_tools,
)
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker


def _parse_json_object(text: str) -> dict:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(clean)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(clean[start:end + 1])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def requires_analysis_workflow(user_request: str) -> bool:
    """对明确的短视频分析/检索请求走确定性主流程。"""
    normalized = (user_request or "").strip().lower()
    if not normalized:
        return False
    domain_terms = (
        "视频", "爆款", "热门", "b站", "bilibili", "哔哩哔哩",
        "抖音", "快手", "小红书", "短视频",
    )
    action_terms = (
        "分析", "搜索", "查找", "检索", "对比", "复盘", "拆解", "提炼", "报告", "规律", "样本",
    )
    return any(term in normalized for term in domain_terms) and any(
        term in normalized for term in action_terms
    )


def requires_current_video_data(user_request: str) -> bool:
    normalized = (user_request or "").strip().lower()
    current_data_terms = (
        "搜索", "查找", "热门视频", "爆款视频", "最近", "近期", "当前",
        "排行榜", "排行", "样本", "视频数据",
    )
    return any(term in normalized for term in current_data_terms)


def requested_platforms(user_request: str, platforms: list[str]) -> set[str]:
    normalized = (user_request or "").lower()
    detected = {item.lower() for item in (platforms or [])}
    aliases = {
        "b站": "bilibili",
        "bilibili": "bilibili",
        "哔哩哔哩": "bilibili",
        "抖音": "douyin",
        "快手": "kuaishou",
        "小红书": "xiaohongshu",
    }
    for marker, platform in aliases.items():
        if marker in normalized:
            detected.add(platform)
    return detected or {"bilibili"}


async def entry_node(state: AgentState) -> dict:
    """只在入口做一次意图判断；正常工作流不再反复调用Supervisor。"""
    trace_tracker.start_agent("entry")
    user_request = state.get("user_request", "")
    raw_topic_spec = state.get("topic_spec")
    result = {
        "workflow_version": "v2",
        "available_capabilities": capability_snapshot(),
    }
    validated_topic_spec = None
    if raw_topic_spec:
        try:
            validated_topic_spec = TopicSpec.model_validate(raw_topic_spec)
        except ValidationError:
            result.update({
                "report_final": (
                    "# 研究范围无效\n\n"
                    "已确认的 TopicSpec 未通过严格校验，因此没有扩大范围或继续采集。"
                ),
                "task_complete": True,
                "termination_reason": "invalid_topic_spec",
            })
            trace_tracker.end_agent("entry")
            return result
        result["topic_spec"] = validated_topic_spec.model_dump(mode="json")

    unsupported = requested_platforms(user_request, state.get("platforms", [])) - {"bilibili"}
    if validated_topic_spec is None and requires_current_video_data(user_request) and unsupported:
        result.update({
            "report_final": (
                "# 当前能力不支持\n\n"
                f"当前真实视频搜索只接入 bilibili，暂不支持 {', '.join(sorted(unsupported))} "
                "的实时热门视频样本，因此没有继续生成分析报告。"
            ),
            "task_complete": True,
            "termination_reason": "unsupported_platform",
        })
        trace_tracker.end_agent("entry")
        return result
    if validated_topic_spec is None and not requires_analysis_workflow(user_request):
        result.update({
            "report_final": await _direct_answer(user_request),
            "task_complete": True,
        })
    trace_tracker.end_agent("entry")
    return result


def route_entry(state: AgentState) -> str:
    return "end" if state.get("task_complete") else "planner_v2"


async def planner_v2_node(state: AgentState) -> dict:
    trace_tracker.start_agent("planner_v2")
    user_request = state.get("user_request", "")
    platforms = state.get("platforms") or ["bilibili"]
    prompt = prompt_manager.get(
        "planner_v2",
        user_request=user_request,
        platforms=platforms,
    )
    if state.get("topic_spec"):
        prompt += "\n\n已确认的结构化研究范围 TopicSpec：\n" + json.dumps(
            state["topic_spec"], ensure_ascii=False, sort_keys=True
        )
    response = await get_llm().ainvoke([HumanMessage(content=prompt)])
    parsed = _parse_json_object(extract_text(response))
    tasks = []
    for item in parsed.get("tasks", [])[:3]:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if description:
            tasks.append({
                "description": description,
                "evidence_type": str(item.get("evidence_type", "search")),
            })
    if not tasks:
        tasks = [{
            "description": f"获取回答该需求所需的B站真实视频样本或知识库证据：{user_request}",
            "evidence_type": "search",
        }]
        fallback_counter.log("planner_v2", "fallback")
    else:
        fallback_counter.log("planner_v2", "json")
    trace_tracker.end_agent("planner_v2")
    return {
        "research_tasks": tasks,
        "plan": [task["description"] for task in tasks],
        "current_step": 0,
    }


def stable_evidence_id(tool_name: str, item: dict) -> str:
    identity = _data_identity(item)
    return f"ev_{hashlib.sha256(f'{tool_name}|{identity}'.encode()).hexdigest()[:16]}"


def _video_published_at(item: dict) -> datetime | None:
    """Read a supplied publication date; collection time is never a substitute."""
    timestamp = item.get("pubdate")
    if not isinstance(timestamp, bool) and isinstance(timestamp, (int, float, str)):
        try:
            if float(timestamp) > 0:
                return datetime.fromtimestamp(float(timestamp), timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    value = item.get("published_at")
    if isinstance(value, str):
        try:
            published_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if published_at.tzinfo is not None:
                return published_at.astimezone(timezone.utc)
        except ValueError:
            pass
    return None


def _filter_video_time_window(
    data: list, topic_spec: dict | None, *, now: datetime | None = None
) -> tuple[list, dict]:
    if not topic_spec:
        return data, {}
    days = topic_spec.get("time_window_days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("validated TopicSpec must include time_window_days")
    window_end = now or datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=days)
    window = {
        "time_window_days": days,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }
    outcome = {
        **window,
        "received_count": len(data),
        "accepted_count": 0,
        "excluded_unknown_publication": 0,
        "excluded_outside_window": 0,
    }
    accepted = []
    for item in data:
        published_at = _video_published_at(item) if isinstance(item, dict) else None
        if published_at is None:
            outcome["excluded_unknown_publication"] += 1
        elif not window_start <= published_at <= window_end:
            outcome["excluded_outside_window"] += 1
        else:
            accepted.append({
                **item,
                "pubdate": int(published_at.timestamp()),
                "published_at": published_at.isoformat(),
                "_time_window": window,
            })
    outcome["accepted_count"] = len(accepted)
    return accepted, outcome


def _build_evidence_items(tool_name: str, params: dict, data: list) -> tuple[list, list[dict]]:
    normalized_data, evidence_items = [], []
    fetched_at = datetime.now(timezone.utc).isoformat()
    source_type = {"search_videos": "bilibili_video", "rag_search": "knowledge_base", "get_transcript": "transcript", "get_trend_data": "trend_data"}.get(tool_name, "tool_result")
    data_field_names = {
        "bvid", "author", "platform_account_id", "display_name", "profile_url",
        "view", "danmaku", "reply", "favorite", "coin", "share", "like",
        "duration", "pubdate", "published_at", "aid",
    }
    for raw_item in data:
        if not isinstance(raw_item, dict):
            continue
        item = raw_item
        if tool_name == "get_transcript" and (
            not item.get("text") or not (item.get("source_url") or item.get("url"))
        ):
            continue
        evidence_id = stable_evidence_id(tool_name, item)
        annotated = {**item, "_evidence_id": evidence_id}
        normalized_data.append(annotated)
        source_urls = item.get("source_urls") or []
        source_url = item.get("url") or item.get("source_url") or (source_urls[0] if source_urls else None)
        evidence_items.append({
            "evidence_id": evidence_id,
            "tool": tool_name,
            "source_type": source_type,
            "title": str(item.get("title") or item.get("source") or params.get("query") or params.get("keyword") or "Evidence"),
            "source_url": source_url,
            "platform": str(item.get("platform") or ("bilibili" if tool_name == "search_videos" else "local")),
            "fetched_at": fetched_at,
            "raw_data": item,
            "summary": item.get("summary") or item.get("content", "")[:300] or None,
            "data_fields": {key: value for key, value in item.items() if key in data_field_names},
            "transcript_segment": item.get("transcript_segment"),
        })
    return normalized_data, evidence_items


def _data_identity(item) -> str:
    if isinstance(item, dict):
        for key in ("url", "bvid", "video_id", "source"):
            if item.get(key):
                return f"{key}:{item[key]}"
        return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
    return str(item)


def dedupe_new_data(data: list, existing_data: list) -> list:
    seen = {_data_identity(item) for item in existing_data}
    unique = []
    for item in data:
        identity = _data_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(item)
    return unique


async def researcher_v2_node(state: AgentState) -> dict:
    trace_tracker.start_agent("researcher_v2")
    tasks = state.get("research_tasks", [])
    current_step = state.get("current_step", 0)
    if current_step >= len(tasks):
        trace_tracker.end_agent("researcher_v2")
        return {}

    task = tasks[current_step]
    platforms = state.get("platforms") or ["bilibili"]
    prompt = prompt_manager.get(
        "researcher_dynamic",
        task=task["description"],
        platforms=platforms,
        available_tools=render_available_tools(),
    )
    response = await get_llm("researcher").ainvoke([HumanMessage(content=prompt)])
    decision = _parse_json_object(extract_text(response))
    tool_name = decision.get("tool", "none")
    params = decision.get("params", {})
    outcome = {
        "task": task["description"],
        "tool": tool_name,
        "params": params if isinstance(params, dict) else {},
        "status": "skipped",
        "error": "",
    }
    raw_data = []
    evidence = []

    if tool_name not in (None, "none"):
        try:
            if tool_name == "rag_search" and isinstance(params, dict) and not params.get("platform"):
                params = {**params, "platform": platforms[0] if len(platforms) == 1 else None}
            normalized_params = normalize_tool_params(tool_name, params)
            outcome["params"] = normalized_params
            raw_result = await call_tool_via_mcp(tool_name, normalized_params)
            fetched_data = raw_result if isinstance(raw_result, list) else ([] if raw_result is None else [raw_result])
            eligible_data = fetched_data
            if tool_name == "search_videos":
                eligible_data, time_filter = _filter_video_time_window(fetched_data, state.get("topic_spec"))
                if time_filter:
                    outcome["time_filter"] = time_filter
            unique_data = dedupe_new_data(eligible_data, state.get("raw_data", []))
            raw_data, evidence = _build_evidence_items(tool_name, normalized_params, unique_data)
            if raw_data:
                outcome["status"] = "success"
            elif unique_data:
                outcome["status"] = "invalid_result"
            elif eligible_data:
                outcome["status"] = "duplicate_only"
            elif fetched_data:
                outcome["status"] = "outside_time_scope"
            else:
                outcome["status"] = "empty"
            fallback_counter.log("researcher_v2", "json")
        except ToolUnavailableError as exc:
            outcome.update(status="unavailable", error=str(exc))
            fallback_counter.log("researcher_v2", "unavailable")
        except (ValueError, TypeError) as exc:
            outcome.update(status="invalid_params", error=str(exc))
            fallback_counter.log("researcher_v2", "invalid_params")
        except Exception as exc:
            outcome.update(status="error", error=str(exc))
            fallback_counter.log("researcher_v2", "error")

    trace_tracker.end_agent("researcher_v2")
    return {
        "raw_data": raw_data,
        "tool_results": [outcome],
        "evidence": evidence,
        "search_queries_used": [task["description"]],
        "current_step": current_step + 1,
    }


def route_research(state: AgentState) -> str:
    if state.get("current_step", 0) < len(state.get("research_tasks", [])):
        return "researcher_v2"
    return "evidence_gate"


def _is_bilibili_video_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}
            and parsed.path.startswith("/video/")
        )
    except ValueError:
        return False


def _is_video_sample(item: dict) -> bool:
    fields = item.get("data_fields") or {}
    raw = item.get("raw_data") or {}
    return bool(
        item.get("tool") == "search_videos"
        and item.get("source_type") == "bilibili_video"
        and item.get("platform") == "bilibili"
        and (fields.get("bvid") or raw.get("bvid"))
        and item.get("title")
        and _is_bilibili_video_url(item.get("source_url"))
    )


def _requires_video_samples(state: AgentState) -> bool:
    return bool(
        state.get("topic_spec")
        or requires_current_video_data(state.get("user_request", ""))
        or any(
            task.get("evidence_type") in {"search", "transcript", "trend"}
            for task in state.get("research_tasks", [])
        )
        or any(item.get("tool") == "search_videos" for item in state.get("tool_results", []))
    )


def evidence_gate_node(state: AgentState) -> dict:
    evidence = [item for item in state.get("evidence", []) if isinstance(item, dict) and item.get("evidence_id")]
    video_samples = [item for item in evidence if _is_video_sample(item)]
    transcript_samples = [
        item for item in evidence
        if not state.get("topic_spec")
        and item.get("tool") == "get_transcript"
        and _is_bilibili_video_url(item.get("source_url"))
        and ((item.get("raw_data") or {}).get("text") or (item.get("transcript_segment") or {}).get("text"))
    ]
    requires_samples = _requires_video_samples(state)
    sample_urls = {urlsplit(item["source_url"]).path.rstrip("/") for item in video_samples + transcript_samples}
    supporting_count = len(sample_urls) if requires_samples else len(evidence)
    if supporting_count >= max(1, V2_MIN_EVIDENCE_ITEMS):
        return {"data_sufficient": True}

    outcomes = state.get("tool_results", [])
    statuses = sorted({item.get("status", "unknown") for item in outcomes})
    reason = "tool_unavailable" if "unavailable" in statuses else "insufficient_evidence"
    knowledge_count = sum(item.get("source_type") == "knowledge_base" for item in evidence)
    message = (
        "# 分析未完成\n\n"
        "本次未获得研究范围内足以支持结论的证据，已保留可用资料，没有生成爆款规律或竞品结论。\n\n"
        f"有效视频样本：{len(video_samples)} 条；知识库方法论或历史资料：{knowledge_count} 条。\n\n"
    )
    if requires_samples and knowledge_count:
        message += "知识库资料仅提供方法论或历史背景，不能替代本次请求所需的视频样本。\n\n"
    filters = [item["time_filter"] for item in outcomes if item.get("time_filter")]
    if state.get("topic_spec"):
        days = state["topic_spec"].get("time_window_days")
        unknown = sum(item["excluded_unknown_publication"] for item in filters)
        outside = sum(item["excluded_outside_window"] for item in filters)
        message += (
            f"时间范围：采集时点之前 {days} 天。发布日期缺失 {unknown} 条、超出时间范围 {outside} 条，均未纳入分析。\n\n"
        )
    message += (
        f"工具结果状态：{', '.join(statuses) if statuses else 'no_tool_result'}。\n\n"
        "可调整研究主题或时间范围，或稍后重新采集；当前资料不代表整个平台或整个行业。"
    )
    return {
        "data_sufficient": False,
        "task_complete": True,
        "termination_reason": reason,
        "report_final": message,
    }


def route_evidence(state: AgentState) -> str:
    return "analyst" if state.get("data_sufficient") else "end"


def route_analyst(state: AgentState) -> str:
    confidence = state.get("analysis_confidence", 0.0)
    iterations = state.get("analysis_iterations", 0)
    if confidence >= ANALYSIS_CONFIDENCE_THRESHOLD or iterations >= V2_ANALYST_MAX_ITERATIONS:
        return "writer"
    return "analyst"


def route_writer(state: AgentState) -> str:
    return "end" if state.get("report_final") else "writer"


def build_graph_v2():
    graph = StateGraph(AgentState)
    graph.add_node("entry", entry_node)
    graph.add_node("planner_v2", planner_v2_node)
    graph.add_node("researcher_v2", researcher_v2_node)
    graph.add_node("evidence_gate", evidence_gate_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)

    graph.add_edge(START, "entry")
    graph.add_conditional_edges("entry", route_entry, {"planner_v2": "planner_v2", "end": END})
    graph.add_edge("planner_v2", "researcher_v2")
    graph.add_conditional_edges(
        "researcher_v2",
        route_research,
        {"researcher_v2": "researcher_v2", "evidence_gate": "evidence_gate"},
    )
    graph.add_conditional_edges(
        "evidence_gate",
        route_evidence,
        {"analyst": "analyst", "end": END},
    )
    graph.add_conditional_edges("analyst", route_analyst, {"analyst": "analyst", "writer": "writer"})
    graph.add_conditional_edges("writer", route_writer, {"writer": "writer", "end": END})

    return graph.compile(checkpointer=get_checkpointer())


def build_collection_graph_v2():
    """Run the existing v2 collection nodes and stop at the Evidence Gate."""
    graph = StateGraph(AgentState)
    graph.add_node("entry", entry_node)
    graph.add_node("planner_v2", planner_v2_node)
    graph.add_node("researcher_v2", researcher_v2_node)
    graph.add_node("evidence_gate", evidence_gate_node)

    graph.add_edge(START, "entry")
    graph.add_conditional_edges("entry", route_entry, {"planner_v2": "planner_v2", "end": END})
    graph.add_edge("planner_v2", "researcher_v2")
    graph.add_conditional_edges(
        "researcher_v2",
        route_research,
        {"researcher_v2": "researcher_v2", "evidence_gate": "evidence_gate"},
    )
    graph.add_edge("evidence_gate", END)
    return graph.compile()


def build_synthesis_graph_v2():
    """Run the existing Analyst and Writer nodes from a durable snapshot state."""
    graph = StateGraph(AgentState)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)
    graph.add_edge(START, "analyst")
    graph.add_conditional_edges("analyst", route_analyst, {"analyst": "analyst", "writer": "writer"})
    graph.add_conditional_edges("writer", route_writer, {"writer": "writer", "end": END})
    return graph.compile()
