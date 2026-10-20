import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.tools.transcript as transcript_module
from src.config import _bounded_int
from src.tools.transcript import AudioExtractionError, AudioTooLargeError, MiMoASRProvider, _validate_public_bilibili_url
from src.worker import _select_transcript_candidates


class FakeMessage:
    content = "测试转写"


class FakeChoice:
    message = FakeMessage()


class FakeCompletion:
    choices = [FakeChoice()]


class FakeCompletions:
    def __init__(self): self.kwargs = None
    async def create(self, **kwargs): self.kwargs = kwargs; return FakeCompletion()


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


class FailingCompletions:
    async def create(self, **_kwargs):
        raise RuntimeError("provider failure")


class FailingClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FailingCompletions()})()


class NeverCalledProvider:
    name = "never-called"
    available = True

    async def transcribe(self, **_kwargs):
        raise AssertionError("provider must not be called on a BVID cache hit")


@pytest.mark.asyncio
async def test_mimo_asr_request_uses_input_audio_and_asr_options(monkeypatch):
    client = FakeClient()
    provider = MiMoASRProvider(client=client)
    result = await provider.transcribe(audio_bytes=b"audio", audio_format="mp3", audio_hash="abc", video_url="https://www.bilibili.com/video/BV1xx411c7mD")
    payload = client.chat.completions.kwargs
    assert payload["model"] == "mimo-v2.5-asr"
    assert payload["messages"][0]["content"][0]["type"] == "input_audio"
    assert payload["messages"][0]["content"][0]["input_audio"]["data"].startswith("data:audio/mpeg;base64,")
    assert payload["extra_body"]["asr_options"]["language"] in {"auto", "zh", "en"}
    assert result["provider"] == "mimo"


@pytest.mark.asyncio
async def test_mimo_asr_rejects_oversized_base64_before_api_call(monkeypatch):
    monkeypatch.setattr(transcript_module, "ASR_MAX_BASE64_BYTES", 4)
    client = FakeClient()
    provider = MiMoASRProvider(client=client)
    with pytest.raises(AudioTooLargeError):
        await provider.transcribe(audio_bytes=b"audio", audio_format="wav", audio_hash="abc", video_url="https://www.bilibili.com/video/BV1xx411c7mD")
    assert client.chat.completions.kwargs is None


@pytest.mark.asyncio
async def test_mimo_provider_errors_become_transcript_errors_for_fallback():
    provider = MiMoASRProvider(client=FailingClient())
    with pytest.raises(transcript_module.TranscriptError, match="RuntimeError"):
        await provider.transcribe(audio_bytes=b"audio", audio_format="mp3", audio_hash="abc", video_url="https://www.bilibili.com/video/BV1xx411c7mD")


@pytest.mark.parametrize("url", [
    "https://www.bilibili.com/video/BV1xx411c7mD",
    "https://bilibili.com/video/BV1xx411c7mD",
    "https://m.bilibili.com/video/BV1xx411c7mD",
    "https://WWW.BILIBILI.COM:443/video/BV1xx411c7mD",
    "https://b23.tv/example",
])
def test_audio_extraction_accepts_public_bilibili_https_urls(url):
    _validate_public_bilibili_url(url)


@pytest.mark.parametrize("url", [
    "http://www.bilibili.com/video/BV1xx411c7mD",
    "https://example.com/video.mp3",
    "https://evilbilibili.com/video/BV1xx411c7mD",
    "https://bilibili.com.attacker.example/video/BV1xx411c7mD",
    "https://evilb23.tv/example",
    "https://b23.tv.attacker.example/example",
    "https://user:password@www.bilibili.com/video/BV1xx411c7mD",
    "https://www.bilibili.com:8443/video/BV1xx411c7mD",
    "https://www.bilibili.com:invalid/video/BV1xx411c7mD",
    "https://127.0.0.1/video/BV1xx411c7mD",
])
def test_audio_extraction_rejects_other_hosts_credentials_or_ports(url):
    with pytest.raises(AudioExtractionError):
        _validate_public_bilibili_url(url)


def test_mimo_asr_requires_an_explicit_backend_authorized_key(monkeypatch):
    monkeypatch.setattr(transcript_module, "MIMO_API_KEY", "")
    assert MiMoASRProvider().available is False


def test_asr_max_videos_accepts_only_one_to_five(monkeypatch):
    monkeypatch.setenv("ASR_MAX_VIDEOS", "1")
    assert _bounded_int("ASR_MAX_VIDEOS", 5, 1, 5) == 1
    monkeypatch.setenv("ASR_MAX_VIDEOS", "5")
    assert _bounded_int("ASR_MAX_VIDEOS", 5, 1, 5) == 5
    monkeypatch.setenv("ASR_MAX_VIDEOS", "0")
    with pytest.raises(ValueError, match="ASR_MAX_VIDEOS"):
        _bounded_int("ASR_MAX_VIDEOS", 5, 1, 5)
    monkeypatch.setenv("ASR_MAX_VIDEOS", "6")
    with pytest.raises(ValueError, match="ASR_MAX_VIDEOS"):
        _bounded_int("ASR_MAX_VIDEOS", 5, 1, 5)


def test_transcript_candidates_are_unique_bilibili_urls_and_respect_limit():
    first = "https://www.bilibili.com/video/BV1xx411c7mD"
    second = "https://www.bilibili.com/video/BV1yy411c7mE"
    raw_data = [
        {"url": "https://www.bilibili.com/video/BV1zz411c7mF", "duration": 601},
        {"url": first, "duration": 120},
        {"source_url": first},
        {"url": "https://example.com/video"},
        {"source_url": second, "duration": 300},
    ]
    assert _select_transcript_candidates(raw_data, 1, 600) == [first]
    assert _select_transcript_candidates(raw_data, 5, 600) == [first, second]


@pytest.mark.asyncio
async def test_bvid_cache_hit_skips_audio_extraction_and_provider(monkeypatch):
    cached = {
        "text": "缓存转写",
        "provider": "mimo",
        "model": "mimo-v2.5-asr",
        "audio_hash": "abc",
        "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "asr_seconds": 60,
        "asr_usage_receipt": {"id": "old-cached-call", "seconds": 60},
    }

    async def fake_cache_get(key):
        return cached if key == "transcript:bvid:BV1xx411c7mD" else None

    async def fail_extract(_url):
        raise AssertionError("audio extraction must not run on a BVID cache hit")

    monkeypatch.setattr(transcript_module, "get_transcript_providers", lambda: [NeverCalledProvider()])
    monkeypatch.setattr(transcript_module, "_cache_get", fake_cache_get)
    monkeypatch.setattr(transcript_module, "_extract_audio", fail_extract)

    result = await transcript_module.get_transcript(cached["source_url"])

    assert result["text"] == cached["text"]
    assert result["audio_seconds"] == 60
    assert result["asr_seconds"] == 0
    assert result["asr_usage_receipt"] is None
    assert result["cache_hit"] is True
    assert cached["asr_seconds"] == 60  # Reading a cache must not mutate its payload.


def test_audio_extraction_limits_compressed_output_not_source_file(monkeypatch, tmp_path):
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download=True):
            assert download is True
            Path(captured["outtmpl"].replace("%(ext)s", "mp3")).write_bytes(b"compressed-audio")
            return {"duration": 120}

    monkeypatch.setattr(transcript_module, "PROJECT_TMP", tmp_path)
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    data, audio_format, duration = transcript_module._extract_audio_sync("https://www.bilibili.com/video/BV1xx411c7mD", str(tmp_path))

    assert data == b"compressed-audio"
    assert audio_format == "mp3"
    assert duration == 120
    assert "max_filesize" not in captured
    assert captured["postprocessors"][0]["preferredquality"] == "64"
