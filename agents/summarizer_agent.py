# -*- coding: utf-8 -*-
"""
agents/summarizer_agent.py — Агент суммаризации и обработки документов.

Умеет:
  • Суммаризировать длинные тексты (chunk + map-reduce)
  • Читать PDF и .txt файлы
  • Суммаризировать YouTube-видео по транскрипту (через yt-dlp / API)
  • Создавать тезисы и ключевые пункты
  • Переводить и адаптировать контент

Триггеры:
  «суммаризируй», «краткое содержание», «перескажи», «тезисы»,
  «summarize», «tldr», «key points»
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMProvider, LLMRequest

log = logging.getLogger("agents.summarizer")

CHUNK_SIZE = 3000       # символов в чанке
MAX_CHUNKS = 8          # максимум чанков


class SummarizerAgent(BaseAgent):
    """
    Агент суммаризации — обрабатывает длинные тексты и документы.
    """

    def __init__(self) -> None:
        super().__init__("summarizer")

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="summarizer",
            description="Суммаризирует тексты, документы, PDF, URL. Map-Reduce для длинных материалов.",
            capabilities=[
                "summarize_text", "summarize_url", "summarize_file",
                "extract_key_points", "translate_summarize", "tldr",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(суммаризируй|сумм|краткое содержание|перескажи|тезисы|выжимка)",
            r"(summarize|summary|tldr|tl;dr|key points|brief|digest)",
            r"(что главное|главное из|основная мысль|выдели главное)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            # URL в тексте?
            url_match = re.search(r"https?://[^\s]+", text)
            if url_match:
                return self._summarize_url(url_match.group(), text)

            # Путь к файлу?
            path_match = re.search(r'["\']?([a-zA-Z]:\\[^\s"\']+|\/[^\s"\']+\.(?:pdf|txt|md|py))["\']?', text)
            if path_match:
                return self._summarize_file(path_match.group(1), text)

            # Есть ли длинный текст для суммаризации?
            # Убираем команду, берём оставшийся текст
            content = re.sub(
                r"^(суммаризируй|сделай краткое содержание|перескажи|summarize|tldr|tl;dr)\s*",
                "", text, flags=re.IGNORECASE
            ).strip()

            if len(content) > 200:
                return self._summarize_text(content, text)

            # Просим пользователя предоставить контент
            return (
                "📄 **SummarizerAgent готов!**\n\n"
                "Предоставь:\n"
                "• URL страницы/статьи для суммаризации\n"
                "• Путь к файлу (PDF, TXT, MD)\n"
                "• Или вставь текст прямо в сообщение\n\n"
                "Пример: `суммаризируй https://example.com/article`"
            )

        except Exception as e:
            self._log_failure("summarize", str(e))
            return f"❌ Ошибка суммаризации: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── Суммаризация текста ───────────────────────────────────────────────────

    def _summarize_text(self, text: str, original_request: str = "") -> str:
        """Map-Reduce суммаризация длинного текста."""
        words_count = len(text.split())

        # Короткий текст — одним запросом
        if len(text) <= CHUNK_SIZE * 2:
            return self._single_summarize(text, original_request)

        # Длинный текст — chunk + reduce
        chunks = self._split_into_chunks(text)
        chunk_summaries = []

        for i, chunk in enumerate(chunks[:MAX_CHUNKS]):
            summary = self._chunk_summarize(chunk, i + 1, len(chunks))
            chunk_summaries.append(summary)

        # Финальное объединение
        combined = "\n\n".join(chunk_summaries)
        final = self._final_reduce(combined, original_request)

        return (
            f"📄 **Суммаризация** ({words_count} слов → резюме)\n\n"
            f"{final}\n\n"
            f"---\n"
            f"_Обработано {len(chunk_summaries)} частей через Map-Reduce_"
        )

    def _single_summarize(self, text: str, request: str = "") -> str:
        """Суммаризация одним запросом."""
        # Определить формат из запроса пользователя
        if re.search(r"(тезис|bullet|пункт|key point)", request, re.IGNORECASE):
            fmt = "маркированный список ключевых тезисов"
        elif re.search(r"(tldr|tl;dr|кратко|brief)", request, re.IGNORECASE):
            fmt = "1-2 предложения (TL;DR)"
        else:
            fmt = "структурированное резюме с заголовками и ключевыми мыслями"

        prompt = (
            f"Суммаризируй следующий текст.\n"
            f"Формат: {fmt}\n"
            f"Язык: русский (если текст на русском) или сохрани язык оригинала.\n\n"
            f"ТЕКСТ:\n{text[:4000]}"
        )
        result = self._ask_llm(prompt, task_type="analysis", require_quality=True)
        return f"📝 **Резюме**\n\n{result}"

    def _chunk_summarize(self, chunk: str, idx: int, total: int) -> str:
        """Суммаризация одного чанка."""
        prompt = (
            f"Выдели ключевые моменты из части {idx}/{total} текста:\n\n{chunk}\n\n"
            f"Дай краткие тезисы (3-5 пунктов). Только факты и выводы."
        )
        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="analysis",
            max_tokens=500,
            temperature=0.3,
            preferred_provider=LLMProvider.DEEPSEEK,
        ))
        return resp.content if resp.success else f"[Часть {idx} — ошибка]"

    def _final_reduce(self, combined_summaries: str, request: str = "") -> str:
        """Финальное объединение всех частей в единое резюме."""
        prompt = (
            f"Объедини эти тезисы из разных частей текста в единое структурированное резюме.\n"
            f"Оригинальный запрос: «{request[:100]}»\n\n"
            f"ТЕЗИСЫ ИЗ ЧАСТЕЙ:\n{combined_summaries[:3000]}\n\n"
            f"Формат финального резюме:\n"
            f"## Главная идея\n"
            f"## Ключевые факты\n"
            f"## Выводы и рекомендации"
        )
        return self._ask_llm(prompt, task_type="analysis", require_quality=True)

    # ── Суммаризация URL ──────────────────────────────────────────────────────

    def _summarize_url(self, url: str, request: str) -> str:
        """Загрузить URL и суммаризировать."""
        try:
            import httpx
            from bs4 import BeautifulSoup

            r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"},
                          timeout=20, verify=False, follow_redirects=True)
            soup = BeautifulSoup(r.text, "html.parser")

            # Убираем ненужное
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "ads"]):
                tag.decompose()

            # Приоритет: article > main > body
            content = (
                soup.find("article") or
                soup.find("main") or
                soup.find("div", class_=re.compile(r"content|article|post")) or
                soup.body
            )
            text = content.get_text(separator="\n", strip=True) if content else ""
            text = "\n".join(l for l in text.splitlines() if len(l) > 30)

            if len(text) < 100:
                return f"❌ Не удалось извлечь текст из {url}"

            title_el = soup.find("title")
            title = title_el.get_text(strip=True) if title_el else url

            summary = self._summarize_text(text, request)
            return f"🌐 **{title}**\n🔗 {url}\n\n{summary}"

        except Exception as e:
            return f"❌ Ошибка загрузки {url}: {e}"

    # ── Суммаризация файла ────────────────────────────────────────────────────

    def _summarize_file(self, file_path: str, request: str) -> str:
        """Прочитать файл и суммаризировать."""
        path = Path(file_path)
        if not path.exists():
            return f"❌ Файл не найден: {file_path}"

        try:
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                text = self._read_pdf(path)
            elif suffix in (".txt", ".md", ".py", ".js", ".ts", ".html"):
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                return f"❌ Тип файла {suffix} не поддерживается."

            if not text:
                return f"❌ Файл пустой: {file_path}"

            summary = self._summarize_text(text, request)
            return f"📂 **{path.name}** ({len(text)} символов)\n\n{summary}"

        except Exception as e:
            return f"❌ Ошибка чтения файла: {e}"

    def _read_pdf(self, path: Path) -> str:
        """Читаем PDF (требует pypdf2 или pdfplumber)."""
        # Пробуем разные библиотеки
        for lib in ["pypdf", "pypdf2", "pdfplumber"]:
            try:
                if lib == "pypdf":
                    import pypdf
                    reader = pypdf.PdfReader(str(path))
                    return "\n".join(page.extract_text() or "" for page in reader.pages)
                elif lib == "pypdf2":
                    import PyPDF2
                    reader = PyPDF2.PdfReader(str(path))
                    return "\n".join(page.extract_text() or "" for page in reader.pages)
                elif lib == "pdfplumber":
                    import pdfplumber
                    with pdfplumber.open(str(path)) as pdf:
                        return "\n".join(page.extract_text() or "" for page in pdf.pages)
            except ImportError:
                continue
            except Exception as e:
                log.debug("PDF read error (%s): %s", lib, e)
        return ""

    # ── Вспомогательные ──────────────────────────────────────────────────────

    def _split_into_chunks(self, text: str) -> List[str]:
        """Разбить текст на чанки по предложениям."""
        # Разбиваем по предложениям
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks, current = [], ""
        for sent in sentences:
            if len(current) + len(sent) > CHUNK_SIZE and current:
                chunks.append(current.strip())
                current = sent
            else:
                current += " " + sent
        if current.strip():
            chunks.append(current.strip())
        return chunks
