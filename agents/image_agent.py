# -*- coding: utf-8 -*-
"""
agents/image_agent.py — Агент работы с изображениями.

Возможности:
  • Анализ изображений через Claude Vision (описание, OCR, объекты)
  • Генерация изображений через Together AI / Stability AI
  • Анализ скриншотов (ошибки, UI, код)
  • Чтение текста с изображений (OCR)
  • Поиск похожих изображений

Провайдеры:
  • Claude claude-3-5-sonnet-20241022 — анализ изображений (Vision)
  • Together AI (via API) — генерация FLUX/SDXL
  • Stability AI (via API) — Stable Diffusion

Триггеры:
  «проанализируй изображение», «что на картинке», «OCR», «сгенерируй изображение»
"""

from __future__ import annotations

import base64
import logging
import re
from pathlib import Path
from typing import Optional

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMProvider, LLMRequest

log = logging.getLogger("agents.image")


class ImageAgent(BaseAgent):
    """
    Агент обработки изображений — анализ через Claude Vision + генерация.
    """

    def __init__(self) -> None:
        super().__init__("image")

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="image",
            description="Анализирует изображения (Claude Vision), читает текст с фото (OCR), генерирует картинки.",
            capabilities=[
                "analyze_image", "ocr", "describe_image",
                "generate_image", "screenshot_analysis",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(проанализируй|посмотри|опиши|что на|что это)\s+.*(изображен|картинк|фото|скриншот)",
            r"(analyze|look at|describe|what is|what's in)\s+.*(image|picture|photo|screenshot)",
            r"(ocr|распознай текст|прочитай с фото|text from image)",
            r"(сгенерируй|нарисуй|создай).*(изображен|картинку|картину|арт|фото)",
            r"(generate|draw|create).*(image|picture|art|photo)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            # Генерация изображений
            if re.search(r"(сгенерируй|нарисуй|создай|generate|draw|create)", text, re.IGNORECASE):
                return self._generate_image(text)

            # Анализ по пути файла
            path_match = re.search(
                r'["\']?([a-zA-Z]:\\[^\s"\']+\.(?:png|jpg|jpeg|gif|webp|bmp))["\']?',
                text, re.IGNORECASE
            )
            if path_match:
                return self._analyze_file(path_match.group(1), text)

            # Анализ без файла — помощь пользователю
            return (
                "🖼 **ImageAgent готов!**\n\n"
                "Для анализа изображения:\n"
                "• Укажи путь к файлу: `проанализируй C:\\путь\\к\\файлу.png`\n"
                "• Или вставь изображение в следующем сообщении\n\n"
                "Для генерации изображения:\n"
                "• `нарисуй [описание]` — создаст изображение через AI\n\n"
                "💡 Поддерживаемые форматы: PNG, JPG, JPEG, GIF, WEBP"
            )
        except Exception as e:
            self._log_failure("image", str(e))
            return f"❌ Ошибка ImageAgent: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    def analyze_image_bytes(self, image_bytes: bytes, prompt: str = "") -> str:
        """
        Анализ изображения из байтов через Claude Vision.
        Вызывается напрямую из GUI когда пользователь прикрепляет файл.
        """
        return self._analyze_with_claude_vision(image_bytes, prompt)

    # ── Анализ файла ──────────────────────────────────────────────────────────

    def _analyze_file(self, file_path: str, request: str) -> str:
        """Загрузить файл и проанализировать через Claude Vision."""
        path = Path(file_path)
        if not path.exists():
            return f"❌ Файл не найден: {file_path}"

        try:
            image_bytes = path.read_bytes()
            user_prompt = re.sub(
                r'["\']?[a-zA-Z]:\\[^\s"\']+\.(?:png|jpg|jpeg|gif|webp|bmp)["\']?',
                '', request, flags=re.IGNORECASE
            ).strip() or "Опиши это изображение подробно."

            result = self._analyze_with_claude_vision(image_bytes, user_prompt)
            return f"🖼 **Анализ: {path.name}**\n\n{result}"
        except Exception as e:
            return f"❌ Ошибка чтения файла: {e}"

    def _analyze_with_claude_vision(self, image_bytes: bytes,
                                     prompt: str = "") -> str:
        """Анализ изображения через Claude Vision API."""
        from core.config import cfg
        if not cfg.claude_api_key:
            return self._analyze_with_local_fallback(image_bytes, prompt)

        try:
            import httpx
            # Определяем MIME тип
            mime_type = "image/jpeg"
            if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                mime_type = "image/png"
            elif image_bytes[:4] == b'GIF8':
                mime_type = "image/gif"
            elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
                mime_type = "image/webp"

            b64_image = base64.b64encode(image_bytes).decode()
            user_prompt = prompt or (
                "Опиши это изображение подробно. Укажи: что изображено, "
                "текст если есть, объекты, цвета, контекст."
            )

            payload = {
                "model": "claude-sonnet-4-5",
                "max_tokens": 1500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_image,
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                }],
            }

            http = httpx.Client(timeout=60, verify=False)
            r = http.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": cfg.claude_api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
            return f"❌ Claude Vision error: {r.status_code} — {r.text[:200]}"

        except Exception as e:
            log.error("Claude Vision error: %s", e)
            return self._analyze_with_local_fallback(image_bytes, prompt)

    def _analyze_with_local_fallback(self, image_bytes: bytes, prompt: str) -> str:
        """Fallback анализ без Vision API."""
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            mode = img.mode
            fmt = img.format or "Unknown"
            return (
                f"🖼 **Анализ изображения** (базовый — Vision API недоступен)\n\n"
                f"• Размер: {w}×{h} px\n"
                f"• Формат: {fmt}\n"
                f"• Цветовая модель: {mode}\n\n"
                f"ℹ️ Для полного анализа нужен Claude API key (Vision)"
            )
        except Exception as e:
            return f"❌ Не удалось проанализировать изображение: {e}"

    # ── Генерация изображений ─────────────────────────────────────────────────

    def _generate_image(self, text: str) -> str:
        # MaxAI: Use professional prompt system for quality ads
        try:
            import sys as _sys
            _sys.path.insert(0, '/root/my_personal_ai/projects/hyperion_engine_v11_monorepo')
            from maxai.image_system import MaxAIImageSystem
            img_sys = MaxAIImageSystem()
            path = img_sys.generate_from_user_request(text)
            if path:
                return (
                    f"\U0001f3a8 **MaxAI Professional Image Generated!**\n\n"
                    f"Template auto-selected based on your request.\n"
                    f"\U0001f4c1 Saved: `{path}`\n"
                    f"Model: FLUX.1-schnell | Steps: 28 | Professional brand style"
                )
        except Exception as _e:
            pass  # Fall through to legacy method
        # Legacy method below:
        return self._generate_image_legacy(text)

    def _generate_image_legacy(self, text: str) -> str:
        """Генерация через Together AI или заглушка."""
        # Извлекаем описание
        description = re.sub(
            r"^(сгенерируй|нарисуй|создай|generate|draw|create)\s+",
            "", text, flags=re.IGNORECASE
        ).strip()

        from core.config import cfg

        # Together AI (если есть ключ)
        together_key = getattr(cfg, 'together_api_key', None) or \
                       __import__('os').environ.get('TOGETHER_API_KEY', '')
        if together_key:
            return self._generate_together(description, together_key)

        # Stability AI
        stability_key = getattr(cfg, 'stability_api_key', None) or \
                        __import__('os').environ.get('STABILITY_API_KEY', '')
        if stability_key:
            return self._generate_stability(description, stability_key)

        # Нет ключей — инструкция
        return (
            f"🎨 **Генерация изображения**\n\n"
            f"Промт: «{description}»\n\n"
            f"⚠️ Нет ключей для генерации. Добавь в .env:\n"
            f"• `TOGETHER_API_KEY` — Together AI (FLUX, SDXL) — бесплатный tier\n"
            f"• `STABILITY_API_KEY` — Stability AI — платный\n\n"
            f"Получить: https://api.together.xyz"
        )

    def _generate_together(self, prompt: str, api_key: str) -> str:
        """Генерация через Together AI (FLUX-1)."""
        try:
            import httpx, json
            from pathlib import Path
            from datetime import datetime

            r = httpx.post(
                "https://api.together.xyz/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": "black-forest-labs/FLUX.1-schnell",
                    "prompt": prompt,
                    "width": 1024, "height": 1024,
                    "steps": 4, "n": 1,
                    "response_format": "b64_json",
                },
                timeout=60, verify=False
            )
            data = r.json()
            b64 = data["data"][0].get("b64_json", "")
            if b64:
                # Сохраняем файл
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out = Path(__file__).parent.parent / "data" / f"gen_{ts}.png"
                out.write_bytes(base64.b64decode(b64))
                return (
                    f"🎨 **Изображение сгенерировано!**\n\n"
                    f"Промт: «{prompt}»\n"
                    f"📁 Сохранено: `{out}`\n"
                    f"Модель: FLUX.1-schnell (Together AI)"
                )
            return f"❌ Together AI вернул пустой ответ: {data}"
        except Exception as e:
            return f"❌ Ошибка генерации (Together AI): {e}"

    def _generate_stability(self, prompt: str, api_key: str) -> str:
        """Генерация через Stability AI."""
        try:
            import httpx
            from pathlib import Path
            from datetime import datetime

            r = httpx.post(
                "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json",
                         "Accept": "application/json"},
                json={
                    "text_prompts": [{"text": prompt, "weight": 1}],
                    "cfg_scale": 7, "height": 1024, "width": 1024,
                    "samples": 1, "steps": 30,
                },
                timeout=60, verify=False
            )
            data = r.json()
            artifacts = data.get("artifacts", [])
            if artifacts:
                b64 = artifacts[0]["base64"]
                ts = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
                out = Path(__file__).parent.parent / "data" / f"gen_{ts}.png"
                out.write_bytes(base64.b64decode(b64))
                return (
                    f"🎨 **Изображение сгенерировано!**\n\n"
                    f"Промт: «{prompt}»\n"
                    f"📁 Сохранено: `{out}`\n"
                    f"Модель: SDXL 1.0 (Stability AI)"
                )
            return f"❌ Stability AI: нет результатов"
        except Exception as e:
            return f"❌ Ошибка генерации (Stability AI): {e}"