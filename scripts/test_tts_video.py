"""Test animated video note generation."""
import asyncio
import sys
sys.path.insert(0, ".")

from src.tools.tts_tool import TTSTool


async def main():
    tool = TTSTool()
    print(f"Provider: {tool.provider}")
    print(f"Available: {tool.available}")

    if not tool.available:
        print("ERROR: No TTS provider available")
        return

    # Generate a test circle
    result = await tool.execute(
        text="Привет! Это тестовое сообщение. Проверяю анимированный видео-кружочек с визуализацией звука.",
        format="video_note",
    )
    print(f"Result: success={result.success}")
    if result.success:
        print(f"Data: {result.data}")
        if tool.pending_video_notes:
            path = tool.pending_video_notes[0]
            size_kb = path.stat().st_size / 1024
            print(f"Video: {path} ({size_kb:.0f} KB)")
        elif tool.pending_voice:
            path = tool.pending_voice[0]
            size_kb = path.stat().st_size / 1024
            print(f"Voice fallback: {path} ({size_kb:.0f} KB)")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
