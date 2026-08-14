import pytest
from pydantic import ValidationError

from src.graph.v2 import _build_evidence_items
from src.tools.search import BilibiliAccountIdentity, _parse_bilibili, search_bilibili


def _video(mid, name="示例账号", bvid="BV1stable") -> dict:
    return {
        "bvid": bvid,
        "aid": 123,
        "title": "真实视频标题",
        "owner": {"mid": mid, "name": name},
        "stat": {"view": 10, "like": 2},
    }


@pytest.mark.parametrize("mid", [12345, "12345", " 0012345 "])
def test_bilibili_identity_uses_canonical_mid_and_profile_url(mid):
    parsed = _parse_bilibili(_video(mid))

    assert parsed["platform_account_id"] == "12345"
    assert parsed["display_name"] == "示例账号"
    assert parsed["profile_url"] == "https://space.bilibili.com/12345"
    assert parsed["author"] == parsed["display_name"]


@pytest.mark.parametrize("mid", [None, "", "0", 0, -1, "12x", 12.0, True])
def test_invalid_mid_does_not_guess_identity_from_display_name(mid):
    parsed = _parse_bilibili(_video(mid, name="同名账号"))

    assert parsed["platform_account_id"] is None
    assert parsed["profile_url"] is None
    assert parsed["display_name"] == "同名账号"


def test_same_display_name_with_different_mids_keeps_distinct_identities():
    first = _parse_bilibili(_video(1001, name="同名账号", bvid="BV1first"))
    second = _parse_bilibili(_video(2002, name="同名账号", bvid="BV1second"))

    assert first["display_name"] == second["display_name"]
    assert first["platform_account_id"] == "1001"
    assert second["platform_account_id"] == "2002"
    assert first["profile_url"] != second["profile_url"]


def test_identity_contract_rejects_extra_fields_and_mismatched_profile_url():
    with pytest.raises(ValidationError):
        BilibiliAccountIdentity(
            platform_account_id="12345",
            display_name="示例账号",
            profile_url="https://space.bilibili.com/99999",
        )
    with pytest.raises(ValidationError):
        BilibiliAccountIdentity(
            platform_account_id="12345",
            display_name="示例账号",
            profile_url="https://space.bilibili.com/12345",
            followers=100,
        )
    with pytest.raises(ValidationError):
        BilibiliAccountIdentity(
            platform_account_id=12345,
            display_name="示例账号",
            profile_url="https://space.bilibili.com/12345",
        )


def test_evidence_preserves_stable_account_identity_projection():
    parsed = _parse_bilibili(_video(12345))

    normalized, evidence = _build_evidence_items(
        "search_videos",
        {"keyword": "测试", "platforms": ["bilibili"]},
        [parsed],
    )

    assert normalized[0]["platform_account_id"] == "12345"
    assert evidence[0]["raw_data"]["platform_account_id"] == "12345"
    assert evidence[0]["data_fields"] == {
        "bvid": "BV1stable",
        "author": "示例账号",
        "platform_account_id": "12345",
        "display_name": "示例账号",
        "profile_url": "https://space.bilibili.com/12345",
        "view": 10,
        "like": 2,
        "reply": 0,
        "favorite": 0,
        "coin": 0,
        "share": 0,
        "duration": 0,
        "aid": 123,
    }


@pytest.mark.asyncio
async def test_search_bilibili_carries_owner_mid_without_real_network(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"code": 0, "data": {"list": [_video(54321)]}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, params):
            assert params == {"rid": 0, "type": "all"}
            return FakeResponse()

    monkeypatch.setattr("src.tools.search.httpx.AsyncClient", lambda **_kwargs: FakeClient())

    results = await search_bilibili("", limit=1)

    assert results[0]["platform_account_id"] == "54321"
    assert results[0]["profile_url"] == "https://space.bilibili.com/54321"


@pytest.mark.asyncio
async def test_search_bilibili_uses_keyword_search_and_normalizes_identity(monkeypatch):
    class FakeResponse:
        def json(self):
            return {
                "code": 0,
                "data": {
                    "result": [{
                        "aid": 456,
                        "bvid": "BV1search",
                        "mid": 67890,
                        "author": "搜索账号",
                        "title": '<em class="keyword">AI</em>编程教程',
                        "arcurl": "https://www.bilibili.com/video/BV1search",
                        "play": "1,234",
                        "like": 56,
                        "review": 7,
                        "favorites": 8,
                        "duration": "01:23",
                    }],
                },
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params):
            assert url.endswith("/wbi/search/type")
            assert params == {"search_type": "video", "keyword": "AI编程", "page": 1}
            return FakeResponse()

    monkeypatch.setattr("src.tools.search.httpx.AsyncClient", lambda **_kwargs: FakeClient())

    results = await search_bilibili("AI编程", limit=1)

    assert results == [{
        "platform": "bilibili",
        "bvid": "BV1search",
        "aid": 456,
        "title": "AI编程教程",
        "platform_account_id": "67890",
        "display_name": "搜索账号",
        "profile_url": "https://space.bilibili.com/67890",
        "author": "搜索账号",
        "view": 1234,
        "views": 1234,
        "play": 1234,
        "like": 56,
        "likes": 56,
        "comment": 7,
        "comments": 7,
        "reply": 7,
        "share": 0,
        "shares": 0,
        "coin": 0,
        "favorite": 8,
        "duration": 83,
        "url": "https://www.bilibili.com/video/BV1search",
    }]


@pytest.mark.asyncio
async def test_search_bilibili_falls_back_to_ranking_when_keyword_search_fails(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params):
            if url.endswith("/wbi/search/type"):
                assert params == {"search_type": "video", "keyword": "AI编程", "page": 1}
                return FakeResponse({"code": -412, "message": "request blocked"})
            assert url.endswith("/ranking/v2")
            assert params == {"rid": 0, "type": "all"}
            return FakeResponse({
                "code": 0,
                "data": {"list": [_video(24680, name="回退账号", bvid="BV1fallback") | {
                    "title": "AI编程排行榜视频",
                }]},
            })

    monkeypatch.setattr("src.tools.search.httpx.AsyncClient", lambda **_kwargs: FakeClient())

    results = await search_bilibili("AI编程", limit=1)

    assert len(results) == 1
    assert results[0]["bvid"] == "BV1fallback"
    assert results[0]["platform_account_id"] == "24680"
    assert results[0]["profile_url"] == "https://space.bilibili.com/24680"
