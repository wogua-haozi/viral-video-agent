import hashlib
import json
from collections import OrderedDict

from src.candidates.schemas import (
    CANDIDATE_SNAPSHOT_VERSION,
    COLLECTION_SNAPSHOT_VERSION,
    MAX_CANDIDATES,
    CandidateProjection,
    CandidateTopicSummary,
    deterministic_candidate_id,
)


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def topic_summary(topic_spec: dict | None, fallback_query: str = "") -> CandidateTopicSummary:
    data = topic_spec or {}
    return CandidateTopicSummary(
        topic=str(data.get("topic") or fallback_query or "未命名研究范围")[:120],
        target_content=[str(item)[:120] for item in data.get("target_content", [])[:8]],
        competitor_definition=str(data.get("competitor_definition") or "")[:500],
        time_window_days=data.get("time_window_days"),
        assumptions=[str(item)[:300] for item in data.get("assumptions", [])[:8]],
    )


def extract_candidates(evidence: list[dict], max_candidates: int = MAX_CANDIDATES) -> list[CandidateProjection]:
    grouped: OrderedDict[str, dict] = OrderedDict()
    for index, item in enumerate(evidence):
        if not isinstance(item, dict) or item.get("tool") != "search_videos":
            continue
        raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
        data_fields = item.get("data_fields") if isinstance(item.get("data_fields"), dict) else {}
        platform = str(item.get("platform") or raw_data.get("platform") or "")
        platform_account_id = data_fields.get("platform_account_id") or raw_data.get("platform_account_id")
        if platform != "bilibili" or not isinstance(platform_account_id, str):
            continue
        if not platform_account_id.isdigit() or platform_account_id.startswith("0") or len(platform_account_id) > 20:
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        display_name = str(data_fields.get("display_name") or raw_data.get("display_name") or "")[:200]
        title = str(item.get("title") or raw_data.get("title") or "")[:300]
        candidate = grouped.setdefault(
            platform_account_id,
            {
                "first_index": index,
                "display_name": display_name,
                "source_evidence_ids": [],
                "sample_titles": [],
                "evidence_links": [],
            },
        )
        if not candidate["display_name"] and display_name:
            candidate["display_name"] = display_name
        if evidence_id not in candidate["source_evidence_ids"]:
            candidate["source_evidence_ids"].append(evidence_id)
        if title and title not in candidate["sample_titles"] and len(candidate["sample_titles"]) < 3:
            candidate["sample_titles"].append(title)
        source_url = item.get("source_url")
        if (
            title
            and isinstance(source_url, str)
            and source_url.startswith("https://")
            and len(candidate["evidence_links"]) < 3
        ):
            candidate["evidence_links"].append({
                "evidence_id": evidence_id,
                "title": title,
                "source_url": source_url[:1000],
            })

    ranked = sorted(
        grouped.items(),
        key=lambda pair: (
            -len(pair[1]["source_evidence_ids"]),
            pair[1]["first_index"],
            pair[0],
        ),
    )[:max_candidates]
    return [
        CandidateProjection(
            candidate_id=deterministic_candidate_id(platform_account_id),
            platform_account_id=platform_account_id,
            display_name=values["display_name"],
            profile_url=f"https://space.bilibili.com/{platform_account_id}",
            source_evidence_ids=values["source_evidence_ids"],
            matched_video_count=len(values["source_evidence_ids"]),
            sample_titles=values["sample_titles"] or ["未提供标题"],
            evidence_links=values["evidence_links"],
            why_surfaced=[f"搜索样本中有{len(values['source_evidence_ids'])}条视频来自该账号"],
        )
        for platform_account_id, values in ranked
    ]


def collection_snapshot_payload(*, source_execution_version: int, result: dict, collection_usage: dict) -> dict:
    return {
        "schema_version": COLLECTION_SNAPSHOT_VERSION,
        "source_execution_version": source_execution_version,
        "workflow_version": result.get("workflow_version", "v2"),
        "topic_spec": result.get("topic_spec") or {},
        "plan": result.get("plan") or [],
        "raw_data": result.get("raw_data") or [],
        "evidence": result.get("evidence") or [],
        "tool_results": result.get("tool_results") or [],
        "search_queries_used": result.get("search_queries_used") or [],
        "collection_usage": collection_usage,
    }


def candidate_snapshot_payload(
    *,
    source_execution_version: int,
    collection_snapshot_hash: str,
    topic: CandidateTopicSummary,
    candidates: list[CandidateProjection],
    max_candidates: int = MAX_CANDIDATES,
) -> dict:
    return {
        "schema_version": CANDIDATE_SNAPSHOT_VERSION,
        "source_execution_version": source_execution_version,
        "collection_snapshot_hash": collection_snapshot_hash,
        "topic_spec": topic.model_dump(mode="json"),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "max_candidates": max_candidates,
    }


def decision_payload_hash(snapshot_id: str, decisions: list[dict]) -> str:
    normalized = sorted(
        (
            {
                "candidate_id": str(item["candidate_id"]),
                "decision": str(item["decision"]),
                "reason": str(item.get("reason") or "").strip(),
            }
            for item in decisions
        ),
        key=lambda item: item["candidate_id"],
    )
    return canonical_hash({"snapshot_id": snapshot_id, "decisions": normalized})
