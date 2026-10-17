"""Offline contracts for honest sample data, scope enforcement and attribution."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.agents import analyst
from src.graph import v2
from src.reporting.validation import finalize_report, validate_claims
from src.tools.search import _parse_bilibili, _parse_bilibili_search_result


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
VIDEO_URL = "https://www.bilibili.com/video/BV1example"
EVIDENCE_ID = "ev_12345678"


def video(**overrides):
    return {
        "platform": "bilibili",
        "bvid": "BV1example",
        "title": "相机测评样本",
        "url": VIDEO_URL,
        **overrides,
    }


def video_evidence(**fields):
    return v2._build_evidence_items("search_videos", {}, [video(**fields)])[1][0]


def knowledge_evidence():
    return v2._build_evidence_items("rag_search", {}, [{
        "content": "历史标题设计方法论，不含本次实时样本。",
        "source": "knowledge/methods.md",
        "title": "标题方法论",
    }])[1][0]


def topic_spec():
    return {
        "topic": "相机",
        "target_content": ["相机测评"],
        "time_window_days": 7,
        "competitor_definition": "本周发布相机测评内容的账号",
        "platform": "bilibili",
        "confidence": 0.8,
    }


@pytest.mark.parametrize("parser, provided", [
    (_parse_bilibili_search_result, {"play": 0, "like": 0, "review": 0, "favorites": 0, "share": 0, "coin": 0}),
    (_parse_bilibili, {"stat": {"view": 0, "like": 0, "reply": 0, "favorite": 0, "share": 0, "coin": 0}}),
])
def test_missing_counters_are_unknown_and_explicit_zero_is_preserved(parser, provided):
    absent = parser({"bvid": "BV1example", "title": "sample"})
    zero = parser({"bvid": "BV1example", "title": "sample", **provided})

    for key in ("view", "views", "play", "like", "likes", "reply", "favorite", "share", "shares", "coin"):
        assert absent[key] is None
        assert zero[key] == 0
    assert absent["duration"] is None
    assert absent["pubdate"] is None
    assert absent["published_at"] is None


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "未知", "1.2万"])
def test_invalid_or_approximate_counters_do_not_become_zero(value):
    assert _parse_bilibili_search_result({"play": value})["view"] is None
    assert _parse_bilibili({"stat": {"view": value}})["view"] is None


@pytest.mark.parametrize("parser", [_parse_bilibili, _parse_bilibili_search_result])
def test_publication_timestamp_is_preserved_separately_from_collection_time(parser):
    parsed = parser({"pubdate": int(NOW.timestamp())})
    assert parsed["pubdate"] == int(NOW.timestamp())
    assert parsed["published_at"] == NOW.isoformat()


def test_time_window_excludes_unknown_old_and_future_publication_dates():
    cutoff = NOW - timedelta(days=7)
    accepted, result = v2._filter_video_time_window([
        video(bvid="BV1recent", pubdate=int((NOW - timedelta(days=1)).timestamp())),
        video(bvid="BV1boundary", pubdate=int(cutoff.timestamp())),
        video(bvid="BV1old", pubdate=int((cutoff - timedelta(seconds=1)).timestamp())),
        video(bvid="BV1unknown"),
        video(bvid="BV1invalid", pubdate=True),
        video(bvid="BV1future", pubdate=int((NOW + timedelta(seconds=1)).timestamp())),
    ], topic_spec(), now=NOW)

    assert [item["bvid"] for item in accepted] == ["BV1recent", "BV1boundary"]
    assert result["accepted_count"] == 2
    assert result["excluded_unknown_publication"] == 2
    assert result["excluded_outside_window"] == 2
    assert accepted[0]["_time_window"]["window_start"] == cutoff.isoformat()
    assert accepted[1]["published_at"] == cutoff.isoformat()


def test_fetch_timestamp_never_substitutes_for_missing_publication_date():
    accepted, result = v2._filter_video_time_window([
        video(fetched_at=NOW.isoformat()),
    ], topic_spec(), now=NOW)
    assert accepted == []
    assert result["excluded_unknown_publication"] == 1


def test_no_confirmed_time_scope_preserves_undated_samples_without_claiming_recency():
    sample = video()
    accepted, result = v2._filter_video_time_window([sample], None, now=NOW)
    assert accepted == [sample]
    assert result == {}
    report = finalize_report("# 报告", [], [video_evidence()])
    assert "没有已确认的结构化时间范围" in report


def test_empty_search_plus_rag_is_partial_for_sample_analysis():
    result = v2.evidence_gate_node({
        "user_request": "分析B站最近一周相机评测样本",
        "research_tasks": [{"evidence_type": "search"}, {"evidence_type": "knowledge"}],
        "evidence": [knowledge_evidence()],
        "tool_results": [{"tool": "search_videos", "status": "empty"}, {"tool": "rag_search", "status": "success"}],
    })
    assert result["data_sufficient"] is False
    assert result["termination_reason"] == "insufficient_evidence"
    assert "不能替代" in result["report_final"]
    assert "有效视频样本：0" in result["report_final"]


def test_methods_only_query_can_use_knowledge_evidence():
    result = v2.evidence_gate_node({
        "user_request": "分析B站标题设计方法论",
        "research_tasks": [{"evidence_type": "knowledge"}],
        "evidence": [knowledge_evidence()],
        "tool_results": [{"tool": "rag_search", "status": "success"}],
    })
    assert result == {"data_sufficient": True}


def test_model_plan_cannot_replace_topic_spec_samples_with_knowledge():
    result = v2.evidence_gate_node({
        "user_request": "相机",
        "topic_spec": topic_spec(),
        "research_tasks": [{"evidence_type": "knowledge"}],
        "evidence": [knowledge_evidence()],
    })
    assert result["data_sufficient"] is False


def test_fake_video_source_does_not_satisfy_sample_gate():
    sample = video_evidence()
    sample["source_url"] = "https://bilibili.com.attacker.invalid/video/BV1example"
    result = v2.evidence_gate_node({
        "user_request": "分析B站热门视频样本",
        "evidence": [sample, knowledge_evidence()],
    })
    assert result["data_sufficient"] is False


@pytest.mark.asyncio
async def test_collection_graph_records_filtered_samples_and_stops_before_synthesis(monkeypatch):
    calls = []

    class FakeLlm:
        def __init__(self, role):
            self.role = role

        async def ainvoke(self, messages):
            if self.role == "researcher":
                is_knowledge = "收集方法论资料" in messages[0].content
                result = {"tool": "rag_search", "params": {"query": "标题方法论"}} if is_knowledge else {
                    "tool": "search_videos", "params": {"keyword": "相机", "platforms": ["bilibili"]},
                }
            else:
                result = {"tasks": [
                    {"description": "收集近期视频样本", "evidence_type": "search"},
                    {"description": "收集方法论资料", "evidence_type": "knowledge"},
                ]}
            return SimpleNamespace(content=json.dumps(result, ensure_ascii=False))

    async def fake_tool(name, params):
        calls.append(name)
        if name == "search_videos":
            return [video(pubdate=int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())), video(bvid="BV1unknown")]
        return [{"content": "标题方法论", "source": "methods.md", "title": "方法论"}]

    monkeypatch.setattr(v2, "get_llm", lambda role="planner": FakeLlm(role))
    monkeypatch.setattr(v2, "call_tool_via_mcp", fake_tool)
    result = await v2.build_collection_graph_v2().ainvoke({
        "user_request": "相机",
        "platforms": ["bilibili"],
        "topic_spec": topic_spec(),
        "task_complete": False,
    })

    assert calls == ["search_videos", "rag_search"]
    assert result["data_sufficient"] is False
    assert result["termination_reason"] == "insufficient_evidence"
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["source_type"] == "knowledge_base"
    assert result["tool_results"][0]["time_filter"]["excluded_unknown_publication"] == 1
    assert "发布日期缺失 1 条、超出时间范围 1 条" in result["report_final"]


def test_partial_empty_claims_exception_does_not_bypass_invalid_attribution():
    evidence = [{"evidence_id": EVIDENCE_ID}]
    assert not validate_claims([], evidence)[0]
    assert validate_claims([], evidence, allow_empty=True)[0]
    claim = {"claim": "观察", "claim_type": "observation", "evidence_ids": ["ev_deadbeef"]}
    assert not validate_claims([claim], evidence, allow_empty=True)[0]


@pytest.mark.parametrize("override", [
    {"evidence_ids": EVIDENCE_ID},
    {"evidence_ids": [{}]},
    {"claim_type": []},
    {"claim_type": "fact"},
    {"claim": " "},
])
def test_malformed_claims_fail_cleanly(override):
    claim = {"claim": "观察", "claim_type": "observation", "evidence_ids": [EVIDENCE_ID], **override}
    assert not validate_claims([claim], [{"evidence_id": EVIDENCE_ID}])[0]


def test_report_programmatically_displays_unknowns_zero_and_both_timestamps():
    evidence = video_evidence(view=0, like=None, pubdate=int(NOW.timestamp()), published_at=NOW.isoformat())
    evidence["fetched_at"] = (NOW + timedelta(days=1)).isoformat()
    content = finalize_report("# 报告", [], [evidence])

    assert f"| {evidence['evidence_id']} | 0 | 未提供 |" in content
    assert "2026-07-26 12:00:00 UTC" in content
    assert "2026-07-27 12:00:00 UTC" in content
    assert VIDEO_URL in content
    assert "None" not in content
    assert "没有视频转写证据" in content


@pytest.mark.asyncio
async def test_analyst_preserves_invalid_references_for_validation(monkeypatch):
    class FakeLlm:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content=json.dumps({
                "claims": [{"claim": "样本观察", "claim_type": "observation", "evidence_ids": [EVIDENCE_ID, "ev_deadbeef"]}],
                "confidence": 0.8,
            }))

    monkeypatch.setattr(analyst, "get_llm", lambda _role: FakeLlm())
    result = await analyst.analyst_node({"raw_data": [{"_evidence_id": EVIDENCE_ID}]})
    claims = result["analysis"]["claims"]
    assert claims[0]["evidence_ids"] == [EVIDENCE_ID, "ev_deadbeef"]
    assert not validate_claims(claims, [{"evidence_id": EVIDENCE_ID}])[0]


@pytest.mark.asyncio
async def test_legacy_insights_are_not_automatically_attributed_to_all_sources(monkeypatch):
    class FakeLlm:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content=json.dumps({"insights": ["待验证建议"], "confidence": None}))

    monkeypatch.setattr(analyst, "get_llm", lambda _role: FakeLlm())
    result = await analyst.analyst_node({"raw_data": [{"_evidence_id": EVIDENCE_ID}]})
    assert result["analysis"]["claims"][0]["evidence_ids"] == []
    assert result["analysis_confidence"] == 0.0
