---
name: tts
description: "Голосовые сообщения и видео-кружочки (TTS)"
tools:
  - tts
trigger_keywords:
  - скажи голосом
  - озвучь
  - voice
  - кружочек
  - кружок
  - video note
  - tts
  - запиши голосовое
  - голосом
  - аудио
  - запиши кружочек
  - ответь кружочком
---

# TTS Skill — Text-to-Speech & Animated Video Circles

## Tool: `tts`
Convert text to speech. Video circles show animated robot avatar with audio waveform.

### Providers
- **Primary**: OpenAI TTS (tts-1-hd) — most natural voice (needs OPENAI_API_KEY)
- **Free**: edge-tts Multilingual Neural — good quality, no API key needed

### Parameters
- `text` (required) — text to speak
- `voice` (optional):
  - OpenAI: `onyx` (deep male), `echo`, `fable`, `alloy`, `nova`, `shimmer`
  - edge-tts multilingual (best free): `brian` (deep male, default), `andrew` (warm male), `ava` (female), `emma` (female)
  - edge-tts standard: `ru-male`, `ru-female`, `en-male`, `en-female`, `uk-male`, `uk-female`
- `format` (optional) — `video_note` (animated circle, default) or `audio` (voice message)

### Rules
1. Default format is `video_note` — animated video with audio waveform on robot face
2. For long texts (>800 chars), text will be truncated to fit 60s video limit
3. Default voice is `brian` (Multilingual, natural sounding) — use it for most responses
4. The media is sent automatically after generation — just call the tool
5. Don't repeat the entire text in your message — just confirm it was generated
6. If user says "ответь кружочком" — summarize your response in a short text and send as video_note
7. When user sends a video circle, respond with a circle too (auto-hint is added)
8. Keep circle responses SHORT (2-4 sentences) — long text = long boring video
