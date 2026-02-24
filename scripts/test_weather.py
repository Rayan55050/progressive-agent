"""Quick functional test for weather tool."""
import asyncio
import sys
import traceback
sys.path.insert(0, ".")

from src.tools.weather_tool import WeatherTool

async def main():
    tool = WeatherTool(default_city="London")
    try:
        result = await tool.execute()
        print(f"Success: {result.success}")
        if result.success:
            print(result.data)
        else:
            print(f"Error: {result.error}")
    except Exception as e:
        traceback.print_exc()

    # Also test raw request
    import aiohttp
    print("\n--- Raw request test ---")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://wttr.in/London?format=j1",
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "progressive-agent/1.0"},
            ) as resp:
                print(f"Status: {resp.status}")
                text = await resp.text()
                print(f"Response length: {len(text)}")
                print(text[:500])
    except Exception as e:
        traceback.print_exc()

asyncio.run(main())
