import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

# B站分区ID映射
CATEGORY_MAP = {
    "美妆": 155, "美食": 211, "游戏": 4, "科技": 188,
    "生活": 160, "音乐": 3, "舞蹈": 129, "知识": 36,
    "影视": 181, "动画": 1, "汽车": 223, "体育": 234,
    "娱乐": 5, "搞笑": 138, "动物": 217, "家居": 161,
    "时尚": 155, "美妆护肤": 155, "美食制作": 211,
}

# 关键词扩展映射：用户输入 → 相关关键词列表
_KEYWORD_EXPANSION = {
    "音乐": ["音乐", "MV", "翻唱", "原创音乐", "歌曲", "演唱会", "Live", "说唱", "民谣", "摇滚", "电音", "古风"],
    "美食": ["美食", "吃播", "探店", "做饭", "烘焙", "菜谱", "小吃", "火锅", "烧烤"],
    "游戏": ["游戏", "LOL", "王者", "原神", "绝地求生", "APEX", "英雄联盟", "手游", "端游"],
    "科技": ["科技", "数码", "手机", "电脑", "评测", "开箱", "AI", "编程"],
    "舞蹈": ["舞蹈", "宅舞", "街舞", "翻跳", "KPOP"],
    "搞笑": ["搞笑", "沙雕", "整活", "段子", "脱口秀"],
    "知识": ["知识", "科普", "学习", "教程", "考试", "考研"],
}


class BilibiliAccountIdentity(BaseModel):
    """Stable account identity carried by every parsed Bilibili video result."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    platform_account_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$", max_length=20)
    display_name: str = Field(default="", max_length=200)
    profile_url: str | None = None

    @model_validator(mode="after")
    def validate_profile_url(self):
        expected = (
            f"https://space.bilibili.com/{self.platform_account_id}"
            if self.platform_account_id
            else None
        )
        if self.profile_url != expected:
            raise ValueError("profile_url must be the canonical URL derived from platform_account_id")
        return self


def _normalize_bilibili_mid(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 and len(str(value)) <= 20 else None
    if isinstance(value, str):
        normalized = value.strip()
        if not re.fullmatch(r"[0-9]+", normalized):
            return None
        canonical = normalized.lstrip("0")
        return canonical if canonical and len(canonical) <= 20 else None
    return None


def _parse_bilibili_account_identity(owner: object) -> BilibiliAccountIdentity:
    owner_data = owner if isinstance(owner, dict) else {}
    platform_account_id = _normalize_bilibili_mid(owner_data.get("mid"))
    raw_name = owner_data.get("name")
    display_name = raw_name.strip()[:200] if isinstance(raw_name, str) else ""
    profile_url = (
        f"https://space.bilibili.com/{platform_account_id}"
        if platform_account_id
        else None
    )
    return BilibiliAccountIdentity(
        platform_account_id=platform_account_id,
        display_name=display_name,
        profile_url=profile_url,
    )


def _expand_keywords(keyword: str) -> list[str]:
    """扩展关键词：返回原始关键词 + 相关词列表。"""
    keywords = [keyword]
    for key, expansions in _KEYWORD_EXPANSION.items():
        if key in keyword:
            keywords.extend(expansions)
            break
    return keywords


def _match_keyword(video: dict, keywords: list[str]) -> bool:
    """检查视频标题是否匹配任意一个关键词。"""
    title = video.get("title", "")
    return any(kw in title for kw in keywords)


async def search_douyin(keyword: str, limit: int = 10) -> list[dict]:
    """搜索抖音视频数据。TODO: 接入抖音开放平台 API"""
    print("[search] 抖音搜索暂未实现，需要接入抖音开放平台 API")
    return []


async def search_bilibili(keyword: str, limit: int = 10) -> list[dict]:
    """搜索B站视频数据。排行榜接口 + 热门接口兜底。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com",
    }

    # 从关键词中匹配分区ID
    rid = 0
    for cat_name, cat_id in CATEGORY_MAP.items():
        if cat_name in keyword:
            rid = cat_id
            break

    # 扩展关键词用于过滤
    keywords = _expand_keywords(keyword) if keyword else []

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        # 尝试排行榜接口
        try:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/ranking/v2",
                params={"rid": rid, "type": "all"},
            )
            data = resp.json()
            if data.get("code") == 0:
                items = data.get("data", {}).get("list", [])
                all_videos = [_parse_bilibili(item) for item in items]
                if keywords:
                    filtered = [v for v in all_videos if _match_keyword(v, keywords)]
                    if filtered:
                        print(f"[search] 关键词过滤: {len(all_videos)} → {len(filtered)} 条 (关键词: {keywords[:3]}...)")
                        return filtered[:limit]
                    # 没有匹配的，返回空并提示
                    print(f"[search] 排行榜中没有匹配 '{keyword}' 的视频")
                    return []
                return all_videos[:limit]
            print(f"[search] 排行榜接口返回错误: {data.get('code')}，尝试热门接口")
        except Exception as e:
            print(f"[search] 排行榜接口失败: {e}，尝试热门接口")

        # 兜底：热门视频接口
        try:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/popular",
                params={"ps": 50, "pn": 1},
            )
            data = resp.json()
            if data.get("code") == 0:
                items = data.get("data", {}).get("list", [])
                all_videos = [_parse_bilibili(item) for item in items]
                if keywords:
                    filtered = [v for v in all_videos if _match_keyword(v, keywords)]
                    if filtered:
                        return filtered[:limit]
                    return []
                return all_videos[:limit]
            print(f"[search] 热门接口也返回错误: {data.get('code')}")
        except Exception as e:
            print(f"[search] 热门接口也失败: {e}")

        return []


async def search_videos(keyword: str, platforms: list[str], limit: int = 10) -> list[dict]:
    """统一搜索入口，按平台列表依次搜索。"""
    results = []
    for platform in platforms:
        if platform == "douyin":
            results.extend(await search_douyin(keyword, limit))
        elif platform == "bilibili":
            results.extend(await search_bilibili(keyword, limit))
        else:
            print(f"[search] 不支持的平台: {platform}")
    return results


def _parse_bilibili(item: dict) -> dict:
    stat = item.get("stat", {})
    identity = _parse_bilibili_account_identity(item.get("owner"))
    view_count = stat.get("view", 0)
    like_count = stat.get("like", 0)
    comment_count = stat.get("reply", 0)
    share_count = stat.get("share", 0)
    return {
        "platform": "bilibili",
        "bvid": item.get("bvid", ""),
        "aid": item.get("aid", ""),
        "title": item.get("title", ""),
        "platform_account_id": identity.platform_account_id,
        "display_name": identity.display_name,
        "profile_url": identity.profile_url,
        "author": identity.display_name,
        "view": view_count,
        "views": view_count,
        "play": view_count,
        "like": like_count,
        "likes": like_count,
        "comment": comment_count,
        "comments": comment_count,
        "reply": comment_count,
        "share": share_count,
        "shares": share_count,
        "coin": stat.get("coin", 0),
        "favorite": stat.get("favorite", 0),
        "duration": item.get("duration", 0),
        "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
    }
