"""Generate AI avatar for TTS video circles using DALL-E 3."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv()


async def main():
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key)

    prompt = (
        "A sleek, futuristic AI assistant avatar for a messaging app. "
        "Circular portrait composition, centered face. "
        "A stylized humanoid face with soft glowing blue/cyan eyes, "
        "smooth metallic silver skin with subtle circuit-like patterns, "
        "dark background with a subtle blue gradient glow. "
        "Modern, clean, minimalist design. Digital art style. "
        "The expression is calm, friendly, and intelligent. "
        "No text, no logos, no watermarks."
    )

    print("Generating avatar with DALL-E 3...")
    response = await client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="hd",
        n=1,
        response_format="url",
    )

    image_url = response.data[0].url
    print(f"Generated: {image_url}")

    # Download and save
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as resp:
            if resp.status == 200:
                data = await resp.read()
                out_path = Path("data/avatar.png")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(data)
                print(f"Saved to {out_path} ({len(data) // 1024} KB)")
            else:
                print(f"Download failed: HTTP {resp.status}")


if __name__ == "__main__":
    asyncio.run(main())
