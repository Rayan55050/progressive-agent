"""Debug test for frame-by-frame TTS video."""
import asyncio
import sys
import time
sys.path.insert(0, ".")


async def main():
    print("1. Importing TTSTool...", flush=True)
    from src.tools.tts_tool import TTSTool, PIL_AVAILABLE
    print(f"   PIL available: {PIL_AVAILABLE}", flush=True)

    tool = TTSTool()
    print(f"2. Provider: {tool.provider}, FFmpeg: {tool._ffmpeg}", flush=True)

    if not tool.available:
        print("ERROR: No TTS provider", flush=True)
        return

    # Step 1: Generate audio only
    print("3. Generating audio with edge-tts...", flush=True)
    t0 = time.time()

    import tempfile
    from pathlib import Path
    temp_dir = Path(tempfile.mkdtemp())
    audio_path = temp_dir / "speech.mp3"

    ok = await tool._generate_edge_tts(
        "Привет! Тестирую анимацию.", None, audio_path
    )
    print(f"   Audio generated: {ok} ({time.time()-t0:.1f}s)", flush=True)
    if not ok:
        print("ERROR: Audio generation failed", flush=True)
        return
    print(f"   Audio size: {audio_path.stat().st_size / 1024:.0f} KB", flush=True)

    # Step 2: Analyze audio
    print("4. Analyzing audio amplitudes...", flush=True)
    t0 = time.time()
    amps = tool._analyze_audio_sync(audio_path)
    print(f"   Frames: {len(amps)}, took {time.time()-t0:.1f}s", flush=True)
    if amps:
        print(f"   Amplitude range: {min(amps):.3f} - {max(amps):.3f}", flush=True)

    # Step 3: Test single frame render
    print("5. Testing single frame render...", flush=True)
    t0 = time.time()
    from PIL import Image, ImageDraw
    bg = tool._render_background(384)
    frame = bg.copy()
    draw = ImageDraw.Draw(frame)
    cx, cy = 192, 187
    tool._draw_head(draw, cx, cy, 0.0)
    tool._draw_eyes(draw, cx, cy, 0.0, 1.0)
    tool._draw_eyebrows(draw, cx, cy, 0.5)
    tool._draw_nose(draw, cx, cy)
    tool._draw_mouth(draw, cx, cy, 0.5)
    tool._draw_decorations(draw, cx, cy, 0.0, 0, 0.5)
    frame_bytes = frame.tobytes()
    print(f"   Frame: {len(frame_bytes)} bytes, took {time.time()-t0:.3f}s", flush=True)

    # Save test frame as PNG
    frame.save(str(temp_dir / "test_frame.png"))
    print(f"   Saved test frame: {temp_dir / 'test_frame.png'}", flush=True)

    # Step 4: Full video render
    print("6. Rendering full video...", flush=True)
    t0 = time.time()
    video_path = temp_dir / "circle.mp4"
    ok = tool._render_video_sync(audio_path, video_path)
    elapsed = time.time() - t0
    print(f"   Video rendered: {ok} ({elapsed:.1f}s)", flush=True)
    if ok:
        size_kb = video_path.stat().st_size / 1024
        print(f"   Video: {video_path} ({size_kb:.0f} KB)", flush=True)
    else:
        print("   ERROR: Video rendering failed!", flush=True)

    print("\nDONE!", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
