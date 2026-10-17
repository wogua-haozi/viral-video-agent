import re
from datetime import datetime, timezone


EVIDENCE_REF_RE = re.compile(r"\b(ev_[a-f0-9]{8,32})\b")


def validate_claims(
    claims: list[dict], evidence: list[dict], *, allow_empty: bool = False
) -> tuple[bool, str]:
    """Validate structure and attribution, not the truth of arbitrary prose.

    ``allow_empty`` is reserved for explicitly partial collection outcomes.
    It never permits an invalid claim or an unknown evidence reference.
    """
    if not isinstance(claims, list):
        return False, "claims must be a list"
    if not isinstance(evidence, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("evidence_id"), str) or not item["evidence_id"]
        for item in evidence
    ):
        return False, "evidence must have a non-empty evidence_id"
    valid_ids = {item["evidence_id"] for item in evidence}
    if evidence and not claims and not allow_empty:
        return False, "evidence exists but analysis has no structured claims"
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim"), str) or not claim["claim"].strip():
            return False, "claim must contain non-empty text"
        if not isinstance(claim.get("claim_type"), str) or claim["claim_type"] not in {"observation", "inference", "recommendation"}:
            return False, "claim has an unknown claim_type"
        evidence_ids = claim.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or any(not isinstance(item, str) for item in evidence_ids):
            return False, "claim evidence_ids must be a list of strings"
        if any(item not in valid_ids for item in evidence_ids):
            return False, "claim references unknown evidence_id"
        if claim.get("claim_type") == "observation" and not evidence_ids:
            return False, "observation has no evidence"
    return True, ""


def validate_report_references(content: str, evidence: list[dict]) -> tuple[bool, str]:
    valid_ids = {item["evidence_id"] for item in evidence}
    unknown = sorted(set(EVIDENCE_REF_RE.findall(content)) - valid_ids)
    if unknown:
        return False, f"report references unknown evidence_id: {', '.join(unknown)}"
    return True, ""


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _fields(item: dict) -> dict:
    raw = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    fields = item.get("data_fields") if isinstance(item.get("data_fields"), dict) else {}
    return {**raw, **fields}


def _format_time(value: object) -> str:
    try:
        if isinstance(value, bool) or value is None:
            return "未提供"
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            return "未提供"
        if parsed.tzinfo is None:
            return "未提供"
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, TypeError, ValueError):
        return "未提供"


def _data_boundary(evidence: list[dict]) -> str:
    videos = [item for item in evidence if item.get("source_type") == "bilibili_video"]
    transcripts = sum(item.get("source_type") == "transcript" for item in evidence)
    knowledge = sum(item.get("source_type") == "knowledge_base" for item in evidence)
    lines = [
        "## 本次数据边界（程序生成）",
        f"公开视频样本 {len(videos)} 条，转写 {transcripts} 份，知识库方法论或历史资料 {knowledge} 条。",
        "“未提供”表示本次采集没有该字段，不按 0 参与计算；0 表示采集记录中的零值，两者含义不同。",
        "发布时间与采集时间分开记录。播放、互动等指标是采集时点的快照，不能单独证明历史增长、完播率或因果关系。",
    ]
    windows = {
        (_fields(item).get("_time_window") or {}).get("time_window_days")
        for item in videos
    } - {None}
    if windows:
        days = "、".join(str(value) for value in sorted(windows))
        lines.append(f"视频样本按各次采集时点向前 {days} 天的时间范围筛选；发布日期缺失或超出范围的结果未纳入分析。")
    elif videos:
        lines.append("本次没有已确认的结构化时间范围，样本不据此保证属于某个近期时间窗口。")
    if not transcripts:
        lines.append("本次没有视频转写证据，内容观察限于已采集的标题和元数据；口播、剪辑和画面表现未在本次采集中验证。")
    else:
        lines.append("转写证据用于核对文字内容；画面、剪辑和 BGM 仍需观看原视频核实。")
    if videos:
        metrics = [("view", "播放量"), ("like", "点赞"), ("reply", "评论"), ("favorite", "收藏"), ("coin", "投币"), ("share", "分享")]
        lines.extend([
            "\n### 可核对的样本指标\n",
            "| 编号 | " + " | ".join(label for _, label in metrics) + " |",
            "|---|" + "---|" * len(metrics),
        ])
        for item in videos:
            fields = _fields(item)
            values = ["未提供" if fields.get(key) is None else _cell(fields[key]) for key, _ in metrics]
            lines.append(f"| {item['evidence_id']} | " + " | ".join(values) + " |")
    return "\n\n".join(lines[:3]) + "\n\n" + "\n".join(lines[3:])


def finalize_report(content: str, claims: list[dict], evidence: list[dict]) -> str:
    claim_lines = []
    for index, claim in enumerate(claims, 1):
        refs = " ".join(f"[{item}]" for item in claim.get("evidence_ids", [])) or "（无直接数值证据）"
        label = {"observation": "数据观察", "inference": "分析推断", "recommendation": "行动建议"}.get(claim.get("claim_type"), "分析推断")
        claim_lines.append(f"{index}. **{label}**：{claim.get('claim', '')} {refs}")
    evidence_lines = ["| 编号 | 类型 | 标题 | 发布时间 | 采集时间 | 来源 |", "|---|---|---|---|---|---|"]
    for item in evidence:
        title = _cell(item.get("title", "Evidence"))
        url = item.get("source_url")
        source = f"[打开来源]({url})" if url else "本地知识库"
        fields = _fields(item)
        published_at = _format_time(fields.get("published_at") or fields.get("pubdate"))
        fetched_at = _format_time(item.get("fetched_at"))
        evidence_lines.append(f"| {item['evidence_id']} | {item.get('source_type', '')} | {title} | {published_at} | {fetched_at} | {source} |")
    appendix = "\n\n## 结构化结论与引用\n\n" + ("\n".join(claim_lines) if claim_lines else "当前没有通过校验的结构化结论。")
    appendix += "\n\n## 数据附录（程序生成）\n\n" + "\n".join(evidence_lines)
    appendix += "\n\n" + _data_boundary(evidence)
    appendix += "\n\n> 局限：结论仅适用于本次采集到的证据，不代表整个平台或整个行业。引用校验只确认来源编号存在，不代表模型对所有事实或因果关系的判断已被验证。"
    return content.rstrip() + appendix
