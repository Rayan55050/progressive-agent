---
name: image_gen
description: "Генерация изображений через DALL-E 3"
tools:
  - image_gen
trigger_keywords:
  - нарисуй
  - сгенерируй картинку
  - image
  - generate image
  - draw
  - создай изображение
  - картинка
  - арт
  - dalle
  - аватар
  - иллюстрация
---

# Image Generation Skill

## Tool: `image_gen`
Generates images using DALL-E 3. Image is automatically sent as a file after generation.

### Parameters
- `prompt` (required) — description of the image. English prompts produce better results with DALL-E.
- `size` (optional) — `1024x1024` (default), `1792x1024` (landscape), `1024x1792` (portrait)
- `quality` (optional) — `standard` (default) or `hd` (costs more, better detail)

### Rules
1. Translate user's description to English for better DALL-E results, but keep your text response in user's language
2. Be creative with the prompt — add details, style, lighting, mood
3. If user gives a vague request, ask for clarification or enhance the prompt yourself
4. After generation, briefly describe what was created
5. One image per request (DALL-E 3 limitation)
6. The image is sent automatically — do NOT call file_send separately
