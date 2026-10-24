"""Проверка ключа Gemini: какие Flash-модели доступны именно вам. Запуск: python check_gemini.py"""
import asyncio

from google import genai

import config as cfg


async def main() -> None:
    c = cfg.load_config()
    client = genai.Client(api_key=c.gemini_api_key)
    names = []
    async for m in await client.aio.models.list():
        if "generateContent" in (m.supported_actions or []) and "flash" in m.name:
            names.append(m.name.removeprefix("models/"))
    print("Flash-модели, которые видит ваш ключ:", *sorted(names), sep="\n  ")
    for name in sorted(names):
        if any(x in name for x in ("image", "tts", "live", "audio", "robotics", "computer")):
            continue
        try:
            r = await client.aio.models.generate_content(model=name, contents="Say hi in 2 words.")
            print(f"[OK ] {name}: {r.text.strip()[:40]!r}")
        except Exception as e:
            print(f"[ERR] {name}: {str(e)[:110]}")


asyncio.run(main())
