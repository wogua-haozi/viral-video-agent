import asyncio
import contextvars
import hashlib
import json
import logging
import os
import socket
import sys
import uuid
from pathlib import Path

import pytest

import src.tools.transcript as transcript
from src.utils.asr_usage_tracker import asr_usage_tracker


URL = "https://www.bilibili.com/video/BV1xx411c7mD"


def install_media_process_fixture(monkeypatch, tmp_path, stage):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    heartbeat = tmp_path / "heartbeat"
    ready = tmp_path / "ready"
    original_run = transcript._run_media_process
    child_script = """
import sys,time
from pathlib import Path
heartbeat=Path(sys.argv[1])
while True:
    heartbeat.write_text(str(time.monotonic()))
    time.sleep(0.02)
"""
    parent_script = """
import json,subprocess,sys,time
from pathlib import Path
request=json.loads(sys.stdin.buffer.read())
temp_dir=Path(request['temp_dir'])
(temp_dir/'audio.mp3.partial').write_bytes(b'incomplete')
heartbeat=Path(sys.argv[1])
if sys.argv[3] == 'transcode':
    child=subprocess.Popen([sys.executable,'-c',sys.argv[4],str(heartbeat)])
    while not heartbeat.exists():
        time.sleep(0.01)
Path(sys.argv[2]).write_text('ready')
while True:
    if sys.argv[3] == 'download':
        heartbeat.write_text(str(time.monotonic()))
    time.sleep(0.02)
"""

    async def run(_command, payload):
        return await original_run([
            sys.executable, "-c", parent_script, str(heartbeat), str(ready), stage, child_script,
        ], payload)

    monkeypatch.setattr(transcript, "PROJECT_TMP", work_dir)
    monkeypatch.setattr(transcript, "_run_media_process", run)
    return work_dir, heartbeat, ready


async def wait_media_ready(heartbeat, ready):
    while not ready.exists() or not heartbeat.exists():
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_invalid_host_cannot_reuse_valid_bvid_cache(monkeypatch):
    async def cache_get(_key):
        raise AssertionError("invalid URLs must fail before any cache access")

    monkeypatch.setattr(transcript, "_cache_get", cache_get)
    with pytest.raises(transcript.AudioExtractionError):
        await transcript.get_transcript("https://evilbilibili.com/video/BV1xx411c7mD")


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_mcp_transcript_reuses_redis_cache_without_new_asr_usage(monkeypatch, backend):
    import redis.asyncio as redis
    from src.tools.mcp_server import get_transcript_tool

    redis_url = os.environ.get("PILOT_TEST_REDIS_URL") if backend == "redis" else "redis://redis:6379/0"
    if not redis_url:
        pytest.skip("PILOT_TEST_REDIS_URL requires a dedicated test Redis")
    real_from_url = redis.from_url
    namespace = f"pilot-transcript:{uuid.uuid4().hex}:"
    owned_keys = set()
    cache = {}
    connections = []
    completed_calls = []
    extracted = []

    class Redis:
        def __init__(self):
            self.client = real_from_url(redis_url, decode_responses=True) if backend == "redis" else None

        async def get(self, key):
            if self.client:
                return await self.client.get(namespace + key)
            return cache.get(key)

        async def set(self, key, value, ex):
            assert ex == 86400 * 30
            owned_keys.add(namespace + key)
            if self.client:
                await self.client.set(namespace + key, value, ex=ex)
            cache[key] = value

        async def aclose(self):
            if self.client:
                await self.client.aclose()
            connections.append("closed")

    def from_url(url, **kwargs):
        assert url == redis_url
        assert kwargs["socket_timeout"] == 2
        connections.append("opened")
        return Redis()

    class Provider:
        async def transcribe(self, **kwargs):
            completed_calls.append(kwargs)
            return {"text": "fixture transcript", "source_url": kwargs["video_url"]}

    async def extract(url):
        extracted.append(url)
        return b"fixture audio", "mp3", 42.0

    monkeypatch.setattr(transcript, "REDIS_URL", redis_url)
    monkeypatch.setattr(redis, "from_url", from_url)
    monkeypatch.setattr(transcript, "get_transcript_providers", lambda: [Provider()])
    monkeypatch.setattr(transcript, "_extract_audio", extract)

    state = asr_usage_tracker.reset()
    try:
        first = await get_transcript_tool(URL)
        second = await get_transcript_tool(URL)
        assert first["cache_hit"] is False and first["asr_seconds"] == 42
        assert second["cache_hit"] is True and second["asr_seconds"] == 0
        assert second["audio_seconds"] == 42 and second["asr_usage_receipt"] is None
        assert len(completed_calls) == len(extracted) == 1
        assert state.asr_seconds == 42
        assert connections.count("opened") == connections.count("closed")
        assert len(cache) == len(owned_keys) == 2
    finally:
        if backend == "redis" and owned_keys:
            cleanup = real_from_url(redis_url, decode_responses=True)
            try:
                await cleanup.delete(*owned_keys)
            finally:
                await cleanup.aclose()


@pytest.mark.asyncio
async def test_cache_failures_log_operation_and_type_without_secret(monkeypatch, caplog):
    import redis.asyncio as redis

    closed = []

    class Redis:
        async def get(self, _key):
            raise ConnectionError("redis://user:secret-password@private-host:6379")

        async def set(self, *_args, **_kwargs):
            raise ConnectionError("redis://user:secret-password@private-host:6379")

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(redis, "from_url", lambda *_args, **_kwargs: Redis())
    with caplog.at_level(logging.WARNING, logger=transcript.__name__):
        assert await transcript._cache_get("fixture") is None
        await transcript._cache_set(["fixture"], {"text": "fixture"})
    assert "cache read failed (ConnectionError)" in caplog.text
    assert "cache write failed (ConnectionError)" in caplog.text
    assert "secret-password" not in caplog.text
    assert "private-host" not in caplog.text
    assert len(closed) == 2


@pytest.mark.asyncio
async def test_extraction_reads_success_then_cleans_parent_owned_directory(monkeypatch, tmp_path):
    original_run = transcript._run_media_process
    script = (
        "import sys,json; from pathlib import Path; "
        "p=Path(json.loads(sys.stdin.buffer.read())['temp_dir']); "
        "(p/'audio.mp3').write_bytes(b'fixture-audio'); "
        "(p/'result.json').write_text(json.dumps({'duration': 30}))"
    )

    async def run(_command, payload):
        return await original_run([sys.executable, "-c", script], payload)

    monkeypatch.setattr(transcript, "PROJECT_TMP", tmp_path)
    monkeypatch.setattr(transcript, "_run_media_process", run)
    assert await transcript._extract_audio(URL) == (b"fixture-audio", "mp3", 30)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_cancellation_before_spawn_returns_still_reaps_child(monkeypatch):
    create = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    deliver_handle = asyncio.Event()
    processes = []

    async def delayed_create(*args, **kwargs):
        process = await create(*args, **kwargs)
        if args[0] == sys.executable:
            processes.append(process)
            spawned.set()
            await deliver_handle.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_create)
    task = asyncio.create_task(transcript._run_media_process([
        sys.executable, "-c", "import time; time.sleep(60)",
    ], b""))
    try:
        await asyncio.wait_for(spawned.wait(), 5)
        task.cancel()
        deliver_handle.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None
    finally:
        deliver_handle.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_spawn_failure_cleans_directory_without_exposing_exception(monkeypatch, tmp_path):
    async def fail_create(*_args, **_kwargs):
        raise OSError("http://user:secret-password@private-host/sse")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_create)
    monkeypatch.setattr(transcript, "PROJECT_TMP", tmp_path)
    with pytest.raises(transcript.AudioExtractionError, match="^OSError$"):
        await transcript._extract_audio(URL)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_spawn_failure_racing_with_cancel_preserves_cancellation(monkeypatch):
    spawning = asyncio.Event()
    fail_spawn = asyncio.Event()

    async def fail_create(*_args, **_kwargs):
        spawning.set()
        await fail_spawn.wait()
        raise OSError("injected process creation failure")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_create)
    task = asyncio.create_task(transcript._run_media_process([sys.executable], b""))
    await spawning.wait()
    task.cancel()
    fail_spawn.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_media_cleanup(monkeypatch):
    started = asyncio.Event()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleaned = []

    async def stop(_process):
        cleanup_started.set()
        await allow_cleanup.wait()
        cleaned.append(True)

    async def extraction():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await transcript._wait_media_cleanup(object())

    monkeypatch.setattr(transcript, "_stop_media_process", stop)
    task = asyncio.create_task(extraction())
    await started.wait()
    task.cancel()
    await cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    allow_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["no_ack", "transport_failure"])
async def test_mcp_unconfirmed_cleanup_is_bounded_and_logs_no_credentials(monkeypatch, caplog, failure):
    import src.agents.researcher as researcher
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    class Session:
        async def send_notification(self, notification):
            assert notification.root.params.requestId == 123
            if failure == "transport_failure":
                raise ConnectionError("http://user:secret-password@private-host/sse")

    async def request_result():
        if failure == "no_ack":
            raise McpError(ErrorData(code=0, message="cancel started"))
        await asyncio.Event().wait()

    monkeypatch.setattr(researcher, "_MCP_CANCEL_WAIT_SECONDS", 0.05)
    request = asyncio.create_task(request_result())
    with caplog.at_level(logging.WARNING, logger=researcher.__name__):
        await asyncio.wait_for(researcher._cancel_remote_tool(
            Session(), 123, request, "get_transcript", asyncio.Event(),
        ), 1)
    assert request.done()
    assert "cleanup not confirmed" in caplog.text
    assert "secret-password" not in caplog.text and "private-host" not in caplog.text


@pytest.mark.asyncio
async def test_mcp_completed_result_racing_with_cancel_still_records_usage():
    from types import SimpleNamespace
    from src.agents.researcher import _cancel_remote_tool

    class Session:
        async def send_notification(self, _notification):
            raise AssertionError("an already completed call needs no cancellation")

    async def result():
        return SimpleNamespace(structured_content={"result": {
            "text": "fixture", "asr_usage_receipt": {"id": "completed-during-cancel", "seconds": 37},
        }})

    state = asr_usage_tracker.reset()
    request = asyncio.create_task(result())
    await request
    await _cancel_remote_tool(Session(), 123, request, "get_transcript", asyncio.Event())
    assert state.asr_seconds == 37


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["download", "transcode"])
@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_cancel_or_timeout_stops_media_tree_and_removes_partial_files(monkeypatch, tmp_path, stage, stop):
    """Use real local processes; no download, FFmpeg, provider or network IO."""
    work_dir, heartbeat, ready = install_media_process_fixture(monkeypatch, tmp_path, stage)
    state = asr_usage_tracker.reset()
    task = asyncio.create_task(transcript._extract_audio(URL))
    try:
        await asyncio.wait_for(wait_media_ready(heartbeat, ready), 5)
        assert list(work_dir.glob("asr-*/audio.mp3.partial"))
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 0.03)
        final_heartbeat = heartbeat.read_text()
        await asyncio.sleep(0.1)
        assert heartbeat.read_text() == final_heartbeat
        assert list(work_dir.iterdir()) == []
        assert state.asr_seconds == 0
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["download", "transcode"])
@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_mcp_sse_cancellation_stops_media_and_waits_for_server_cleanup(monkeypatch, tmp_path, stage, stop):
    """Exercise the real MCP SSE transport using loopback and local processes."""
    import uvicorn
    import src.agents.researcher as researcher
    from src.tools.mcp_server import mcp

    work_dir, heartbeat, ready = install_media_process_fixture(monkeypatch, tmp_path, stage)
    extraction_cancelled = asyncio.Event()
    extraction_finished = asyncio.Event()
    original_extract = transcript._extract_audio
    original_stop = transcript._stop_media_process

    class Provider:
        async def transcribe(self, **_kwargs):
            raise AssertionError("cancelled extraction must never call a provider")

    async def extract(url):
        try:
            return await original_extract(url)
        except asyncio.CancelledError:
            extraction_cancelled.set()
            raise
        finally:
            extraction_finished.set()

    async def no_cache(_key):
        return None

    async def no_fallback(*_args, **_kwargs):
        raise AssertionError("client cancellation must not start a local fallback")

    async def delayed_stop(process):
        await asyncio.sleep(0.15)
        await original_stop(process)

    monkeypatch.setattr(transcript, "get_transcript_providers", lambda: [Provider()])
    monkeypatch.setattr(transcript, "_extract_audio", extract)
    monkeypatch.setattr(transcript, "_cache_get", no_cache)
    monkeypatch.setattr(transcript, "_stop_media_process", delayed_stop)
    monkeypatch.setattr(researcher, "call_tool", no_fallback)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    monkeypatch.setattr(researcher, "MCP_SERVER_URL", f"http://127.0.0.1:{port}/sse")
    server = uvicorn.Server(uvicorn.Config(
        mcp.sse_app(), host="127.0.0.1", port=port, log_level="warning",
        lifespan="off", timeout_graceful_shutdown=1,
    ))
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    task = None
    try:
        async def wait_started():
            while not server.started:
                if server_task.done():
                    await server_task
                    raise AssertionError("SSE fixture failed to start")
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_started(), 5)
        task = asyncio.create_task(researcher.call_tool_via_mcp("get_transcript", {"video_url": URL}))
        await asyncio.wait_for(wait_media_ready(heartbeat, ready), 5)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 0.03)
        # A protocol cancellation response means cancellation has started.
        # The caller must also wait for the server's cleanup completion ACK.
        assert extraction_finished.is_set()
        await asyncio.wait_for(extraction_finished.wait(), 5)
        assert extraction_cancelled.is_set()
        assert list(work_dir.iterdir()) == []
        final_heartbeat = heartbeat.read_text()
        await asyncio.sleep(0.1)
        assert heartbeat.read_text() == final_heartbeat
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        server.should_exit = True
        await asyncio.wait_for(server_task, 5)
        listener.close()


@pytest.mark.asyncio
async def test_mcp_sse_reuses_dedicated_redis_transcript_without_new_usage(monkeypatch):
    import redis.asyncio as redis
    import uvicorn
    import src.agents.researcher as researcher
    from src.tools.mcp_server import mcp

    redis_url = os.environ.get("PILOT_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("PILOT_TEST_REDIS_URL requires a dedicated test Redis")
    bvid = f"BV{uuid.uuid4().hex[:10]}"
    url = f"https://www.bilibili.com/video/{bvid}"
    audio = uuid.uuid4().bytes
    keys = [f"transcript:bvid:{bvid}", f"transcript:audio:{hashlib.sha256(audio).hexdigest()}"]
    redis_client = redis.from_url(redis_url, decode_responses=True)
    owned_keys = False
    calls = {"extractor": 0, "provider": 0}

    class Provider:
        async def transcribe(self, **kwargs):
            calls["provider"] += 1
            return {"text": "loopback SSE fixture transcript", "source_url": kwargs["video_url"]}

    async def extract(_url):
        calls["extractor"] += 1
        return audio, "mp3", 42.0

    async def no_fallback(*_args, **_kwargs):
        raise AssertionError("the real SSE transport must succeed without local fallback")

    monkeypatch.setattr(transcript, "REDIS_URL", redis_url)
    monkeypatch.setattr(transcript, "get_transcript_providers", lambda: [Provider()])
    monkeypatch.setattr(transcript, "_extract_audio", extract)
    monkeypatch.setattr(researcher, "call_tool", no_fallback)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    monkeypatch.setattr(researcher, "MCP_SERVER_URL", f"http://127.0.0.1:{port}/sse")
    server = uvicorn.Server(uvicorn.Config(
        mcp.sse_app(), host="127.0.0.1", port=port, log_level="warning",
        lifespan="off", timeout_graceful_shutdown=1,
    ))
    # Keep the server and caller receipt ledgers separate, as with real MCP
    # processes. The caller must account the returned receipt itself.
    server_context = contextvars.copy_context()
    server_usage = server_context.run(asr_usage_tracker.reset)
    server_task = server_context.run(asyncio.create_task, server.serve(sockets=[listener]))
    caller_usage = asr_usage_tracker.reset()
    try:
        assert await redis_client.exists(*keys) == 0
        owned_keys = True

        async def wait_started():
            while not server.started:
                if server_task.done():
                    await server_task
                    raise AssertionError("SSE fixture failed to start")
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_started(), 5)
        first = await asyncio.wait_for(researcher.call_tool_via_mcp("get_transcript", {"video_url": url}), 5)
        assert first["cache_hit"] is False and first["asr_seconds"] == 42
        assert first["asr_usage_receipt"]["seconds"] == 42
        assert caller_usage.asr_seconds == server_usage.asr_seconds == 42
        second = await asyncio.wait_for(researcher.call_tool_via_mcp("get_transcript", {"video_url": url}), 5)
        assert second["cache_hit"] is True and second["asr_seconds"] == 0
        assert second["audio_seconds"] == 42 and second["asr_usage_receipt"] is None
        assert calls == {"extractor": 1, "provider": 1}
        assert caller_usage.asr_seconds == server_usage.asr_seconds == 42
        assert await redis_client.exists(*keys) == 2
    finally:
        if owned_keys:
            await redis_client.delete(*keys)
        await redis_client.aclose()
        server.should_exit = True
        await asyncio.wait_for(server_task, 5)
        listener.close()
