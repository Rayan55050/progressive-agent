"""
DeepL translation tool — high-quality translations via DeepL API Free.

Free tier: 500,000 characters/month.
Uses aiohttp directly (no extra SDK dependency).

API docs: https://developers.deepl.com/docs/api-reference/translate
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"

# Supported language codes (most common)
SUPPORTED_LANGS = [
    "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FI", "FR",
    "HU", "ID", "IT", "JA", "KO", "LT", "LV", "NB", "NL", "PL",
    "PT", "RO", "RU", "SK", "SL", "SV", "TR", "UK", "ZH",
]


class DeepLTool:
    """Translate text using DeepL API (free tier)."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="translate",
            description=(
                "Translate text using DeepL — best machine translation quality. "
                "Free tier: 500K chars/month. Supports 29 languages. "
                "Auto-detects source language. "
                "Common codes: EN, RU, UK (Ukrainian), DE, FR, ES, JA, KO, ZH, PL."
            ),
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to translate",
                    required=True,
                ),
                ToolParameter(
                    name="target_lang",
                    type="string",
                    description="Target language code (e.g. 'EN', 'RU', 'UK', 'DE', 'FR')",
                    required=True,
                ),
                ToolParameter(
                    name="source_lang",
                    type="string",
                    description="Source language code (optional, auto-detected if omitted)",
                    required=False,
                ),
                ToolParameter(
                    name="formality",
                    type="string",
                    description="Formality level: 'default', 'more', 'less', 'prefer_more', 'prefer_less'",
                    required=False,
                    enum=["default", "more", "less", "prefer_more", "prefer_less"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._api_key:
            return ToolResult(
                success=False,
                error="DeepL API key not configured. Set DEEPL_API_KEY in .env",
            )

        text = kwargs.get("text", "").strip()
        if not text:
            return ToolResult(success=False, error="No text provided for translation")

        target_lang = kwargs.get("target_lang", "").strip().upper()
        if not target_lang:
            return ToolResult(success=False, error="target_lang is required (e.g. 'EN', 'RU')")

        if target_lang not in SUPPORTED_LANGS:
            return ToolResult(
                success=False,
                error=f"Unsupported target language: {target_lang}. Supported: {', '.join(SUPPORTED_LANGS)}",
            )

        # Build request payload
        payload: dict[str, str] = {
            "text": [text],
            "target_lang": target_lang,
        }

        source_lang = kwargs.get("source_lang", "").strip().upper()
        if source_lang:
            payload["source_lang"] = source_lang

        formality = kwargs.get("formality", "").strip().lower()
        if formality and formality != "default":
            payload["formality"] = formality

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"DeepL-Auth-Key {self._api_key}",
                    "Content-Type": "application/json",
                }
                async with session.post(
                    DEEPL_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 403:
                        return ToolResult(success=False, error="DeepL API key invalid or quota exceeded")
                    if resp.status == 456:
                        return ToolResult(success=False, error="DeepL quota exceeded (500K chars/month limit)")
                    if resp.status != 200:
                        body = await resp.text()
                        return ToolResult(success=False, error=f"DeepL API error {resp.status}: {body[:200]}")

                    data = await resp.json()

            translations = data.get("translations", [])
            if not translations:
                return ToolResult(success=False, error="No translation returned")

            translated = translations[0].get("text", "")
            detected_lang = translations[0].get("detected_source_language", "?")

            result = f"[{detected_lang} → {target_lang}]\n{translated}"
            logger.info(
                "DeepL: %d chars %s→%s translated",
                len(text), detected_lang, target_lang,
            )
            return ToolResult(success=True, data=result)

        except aiohttp.ClientError as e:
            logger.error("DeepL network error: %s", e)
            return ToolResult(success=False, error=f"DeepL network error: {e}")
        except Exception as e:
            logger.error("DeepL error: %s", e)
            return ToolResult(success=False, error=f"DeepL error: {e}")
