"""Quick import test for all new tools."""
import sys
sys.path.insert(0, ".")

from src.tools.weather_tool import WeatherTool
from src.tools.image_gen_tool import ImageGenTool
from src.tools.tts_tool import TTSTool
from src.tools.scheduler_tool import SchedulerService, SchedulerAddTool, SchedulerListTool, SchedulerRemoveTool

print("All imports OK")

w = WeatherTool()
print(f"WeatherTool: {w.definition.name}")

tts = TTSTool()
print(f"TTSTool available: {tts.available}")
print(f"TTSTool definition: {tts.definition.name}")

img = ImageGenTool(api_key="test")
print(f"ImageGenTool: {img.definition.name}")

print("\nAll tools instantiated successfully!")
