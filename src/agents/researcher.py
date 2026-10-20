import asyncio
import json
import logging
from langchain_core.messages import HumanMessage
from src.agents.supervisor import get_llm, extract_text
from src.graph.state import AgentState
from src.mcp.client import call_tool
from src.utils.fallback_counter import fallback_counter
from src.utils.trace_tracker import trace_tracker
from src.prompts.manager import prompt_manager
from src.config import MCP_SERVER_URL
from src.utils.asr_usage_tracker import asr_usage_tracker


ALLOWED_TOOLS = {"search_videos", "rag_search", "get_transcript", "get_trend_data"}
logger = logging.getLogger(__name__)
_MCP_CANCEL_WAIT_SECONDS = 3


class _ToolRequestStream:
    """Observe the public JSON-RPC envelope without SDK private request state."""

    def __init__(self, stream):
        self.stream = stream
        self.request_id = None

    async def send(self, message):
        request = message.message.root
        if getattr(request, "method", None) == "tools/call":
            self.request_id = request.id
        await self.stream.send(message)

    async def aclose(self):
        await self.stream.aclose()

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)


async def _cancel_remote_tool(session, request_id, request, tool_name, cleanup_completed):
    """Deliver protocol cancellation before closing SSE; never wait forever."""
    from mcp import types

    async def cancel_and_drain():
        if request_id is not None and not request.done():
            await session.send_notification(types.ClientNotification(types.CancelledNotification(
                params=types.CancelledNotificationParams(requestId=request_id, reason="Task cancelled"),
            )))
        try:
            result = await request
            if tool_name == "get_transcript":
                asr_usage_tracker.record(_unwrap_mcp_result(result))
        except Exception:
            # A cancellation response is an MCP error. A failed transport is
            # also not permission to start the work again through fallback.
            if tool_name == "get_transcript":
                await cleanup_completed.wait()
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)

    cleanup = asyncio.create_task(asyncio.wait_for(cancel_and_drain(), timeout=_MCP_CANCEL_WAIT_SECONDS))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    try:
        await cleanup
    except Exception as exc:
        logger.warning("MCP cancellation cleanup not confirmed (%s)", type(exc).__name__)
    finally:
        if not request.done():
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)


class MCPToolExecutionError(RuntimeError):
    pass


def _parse_text_content(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _unwrap_mcp_result(result):
    """把 MCP CallToolResult 转为项目内部使用的 list/dict/string。"""
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        raise MCPToolExecutionError("MCP tool execution failed")
    for attr in ("structured_content", "structuredContent"):
        value = getattr(result, attr, None)
        if value is not None:
            # FastMCP 会把函数返回值包装为 {"result": ...}。
            if isinstance(value, dict) and set(value) == {"result"}:
                return value["result"]
            return value

    content = getattr(result, "content", None)
    if not isinstance(content, list):
        return result

    values = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text is not None:
            values.append(_parse_text_content(text))

    if len(values) == 1:
        return values[0]
    flattened = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return flattened


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


async def call_tool_via_mcp(tool_name: str, params: dict):
    """通过 MCP Client 调用工具，失败时回退到直接调用。"""
    try:
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(MCP_SERVER_URL) as (read, write):
            tracked_write = _ToolRequestStream(write)
            cleanup_completed = asyncio.Event()

            async def on_log(params):
                data = params.data
                if (
                    params.logger == "viral-video.transcript" and isinstance(data, dict)
                    and data.get("requestId") == tracked_write.request_id
                    and data.get("cleanup_complete") is True
                ):
                    cleanup_completed.set()

            async with ClientSession(read, tracked_write, logging_callback=on_log) as session:
                await session.initialize()
                request = asyncio.create_task(session.call_tool(tool_name, params))
                try:
                    result = await asyncio.shield(request)
                except asyncio.CancelledError:
                    await _cancel_remote_tool(session, tracked_write.request_id, request, tool_name, cleanup_completed)
                    raise
                value = _unwrap_mcp_result(result)
                if tool_name == "get_transcript":
                    # Record before transport cleanup can await/cancel. This
                    # non-throwing recorder also deduplicates local transports.
                    asr_usage_tracker.record(value)
    except MCPToolExecutionError:
        raise
    except Exception as e:
        print(f"[Researcher] MCP调用失败，回退到直接调用: {type(e).__name__}")
        return await call_tool(tool_name, params)
    return value


async def researcher_node(state: AgentState) -> dict:
    trace_tracker.start_agent("researcher")
    llm = get_llm("researcher")
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    platforms = state.get("platforms") or ["bilibili"]

    if current_step >= len(plan):
        trace_tracker.end_agent("researcher")
        return {"data_sufficient": True}

    task = plan[current_step]
    print(f"[Researcher] exec: {task}")

    prompt = prompt_manager.get("researcher", task=task, platforms=platforms)

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = extract_text(response)

    # 解析LLM输出，兜底到硬编码
    tool_name = "search_videos"
    params = {"keyword": task, "platforms": platforms, "limit": 5}
    try:
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        decision = json.loads(clean)
        tool_name = decision.get("tool", "search_videos")
        params = decision.get("params", params)
        if tool_name in (None, "none"):
            tool_name = "none"
        elif tool_name not in ALLOWED_TOOLS:
            raise ValueError(f"不支持的工具: {tool_name}")
        if tool_name == "search_videos" and not params.get("platforms"):
            params["platforms"] = platforms
        fallback_counter.log("researcher", "json")
        print(f"[Researcher] LLM选择工具: {tool_name}")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        fallback_counter.log("researcher", "default")
        print(f"[Researcher] LLM输出解析失败，使用默认: {e}")

    raw_data = [] if tool_name == "none" else _as_list(await call_tool_via_mcp(tool_name, params))
    existing_data = state.get("raw_data", [])
    completed_all_steps = current_step + 1 >= len(plan)

    trace_tracker.end_agent("researcher")
    return {
        "raw_data": raw_data,
        "search_queries_used": [task],
        "data_sufficient": bool(existing_data or raw_data) or completed_all_steps,
        "current_step": current_step + 1,
    }
