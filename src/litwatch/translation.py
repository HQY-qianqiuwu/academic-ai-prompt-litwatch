from __future__ import annotations

import re
import threading
from typing import Any


class LocalEnglishChineseTranslator:
    """Lazy offline English-to-Chinese translation with safe source fallback."""

    def __init__(self, model_name: str = "Helsinki-NLP/opus-mt-en-zh") -> None:
        self.model_name = model_name
        self._pipeline: Any | None = None
        self._lock = threading.Lock()

    def translate(self, text: str) -> str:
        source = " ".join(text.split())
        if not source or self._contains_chinese(source):
            return source
        translator = self._load_pipeline()
        chunks = self._chunks(source)
        translated = []
        for chunk in chunks:
            result = translator(chunk, max_length=512)[0]
            value = result.get("translation_text", result.get("generated_text", ""))
            translated.append(str(value).strip())
        return " ".join(item for item in translated if item) or source

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        with self._lock:
            if self._pipeline is None:
                from transformers import pipeline

                self._pipeline = pipeline(
                    "text2text-generation",
                    model=self.model_name,
                    tokenizer=self.model_name,
                    device=-1,
                )
        return self._pipeline

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        return bool(re.search(r"[\u3400-\u9fff]", text))

    @staticmethod
    def _chunks(text: str, limit: int = 900) -> list[str]:
        if len(text) <= limit:
            return [text]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > limit:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
        return chunks
