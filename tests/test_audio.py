import json
import shutil
import subprocess

import pytest

from services.audio import AudioError, mp3_to_ogg_opus
from services.tts import TTSService

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg не установлен")


def make_mp3(path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    str(path)], check=True)


async def test_mp3_to_ogg_opus(tmp_path):
    src, dst = tmp_path / "a.mp3", tmp_path / "a.ogg"
    make_mp3(src)
    await mp3_to_ogg_opus(src, dst)
    assert dst.stat().st_size > 0
    assert dst.read_bytes()[:4] == b"OggS"
    if shutil.which("ffprobe"):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(dst)],
                             capture_output=True, text=True, check=True).stdout
        stream = json.loads(out)["streams"][0]
        assert stream["codec_name"] == "opus"
        assert stream["channels"] == 1


async def test_bad_input_raises(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(AudioError):
        await mp3_to_ogg_opus(bad, tmp_path / "x.ogg")


def test_cache_key_depends_on_rate_and_voice():
    k = TTSService.cache_key
    assert k("Hello", "v", 0) == k("Hello", "v", 0)
    assert k("Hello", "v", 0) != k("Hello", "v", -30)
    assert k("Hello", "v", 0) != k("Hello", "w", 0)


async def test_tts_uses_cache(tmp_path, monkeypatch):
    svc = TTSService(tmp_path)
    cached = tmp_path / f"{svc.cache_key('Hi', 'v', 0)}.ogg"
    cached.write_bytes(b"OggS")
    assert await svc.synth("Hi", "v", 0) == cached  # без сети: файл уже в кеше
