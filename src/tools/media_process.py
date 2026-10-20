"""Disposable yt-dlp/FFmpeg owner; the parent owns and cleans its directory."""

import json
import sys
from pathlib import Path

from src.tools.transcript import TranscriptError, _extract_audio_sync


def main() -> None:
    request = json.loads(sys.stdin.buffer.read())
    temp_dir = Path(request["temp_dir"])
    try:
        _audio, _format, duration = _extract_audio_sync(request["video_url"], str(temp_dir))
        result = {"duration": duration}
    except TranscriptError as exc:
        result = {"error": exc.code}
    (temp_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
