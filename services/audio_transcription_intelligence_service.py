"""Camada de modos e providers para transcricoes avulsas."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Mapping

from services.audio_transcription_review_service import (
    AudioTranscriptionReviewService,
    transcription_review_enabled,
)
from services.transcription_llm_review_service import (
    LlmReviewResult,
    review_transcription_with_llm,
)


SUPPORTED_TRANSCRIPTION_MODES = {"literal", "revisada", "codex", "relatorio"}
DEFAULT_TRANSCRIPTION_MODE = "revisada"
ExternalProvider = Callable[[str, str], str]
LlmReviewer = Callable[[str, str], LlmReviewResult]


@dataclass(frozen=True)
class IntelligentTranscriptionResult:
    ok: bool
    raw_text: str
    output_text: str
    mode: str
    provider: str
    error_message: str | None = None
    used_fallback: bool = False


def transcription_review_provider() -> str:
    return os.getenv("TRANSCRIPTION_REVIEW_PROVIDER", "local").strip().lower() or "local"


def transcription_review_default_mode() -> str:
    configured = os.getenv(
        "TRANSCRIPTION_REVIEW_MODE_DEFAULT", DEFAULT_TRANSCRIPTION_MODE
    ).strip().lower()
    return configured if configured in SUPPORTED_TRANSCRIPTION_MODES else DEFAULT_TRANSCRIPTION_MODE


class AudioTranscriptionIntelligenceService:
    """Seleciona a saida e isola futuros providers externos.

    Providers externos somente sao chamados quando injetados explicitamente e
    selecionados por ambiente. O projeto nao realiza chamadas externas sozinho.
    """

    def __init__(
        self,
        *,
        local_reviewer: AudioTranscriptionReviewService | None = None,
        external_providers: Mapping[str, ExternalProvider] | None = None,
        llm_reviewer: LlmReviewer | None = None,
    ) -> None:
        self._local_reviewer = local_reviewer or AudioTranscriptionReviewService()
        self._external_providers = dict(external_providers or {})
        self._llm_reviewer = llm_reviewer or review_transcription_with_llm

    def process(
        self,
        raw_text: str,
        *,
        mode: str | None = None,
        provider: str | None = None,
        context: str | None = None,
    ) -> IntelligentTranscriptionResult:
        raw = str(raw_text or "").strip()
        selected_mode = self._normalize_mode(mode)
        selected_provider = (provider or transcription_review_provider()).strip().lower()
        if not raw:
            return IntelligentTranscriptionResult(
                False,
                raw,
                "",
                selected_mode,
                "local",
                "Transcrição vazia.",
            )
        if not transcription_review_enabled():
            return IntelligentTranscriptionResult(
                True, raw, raw, selected_mode, "local"
            )

        # O modo literal nunca transmite texto a um provider externo.
        if selected_mode == "literal":
            return self._process_local(raw, selected_mode, context=context)

        if selected_mode in {"revisada", "relatorio"}:
            llm_result = self._llm_reviewer(raw, context or "relatorio_agro")
            if llm_result.ok and llm_result.output_text.strip():
                return IntelligentTranscriptionResult(
                    True,
                    raw,
                    llm_result.output_text.strip(),
                    selected_mode,
                    llm_result.provider,
                )
            local = self._process_local(raw, selected_mode, context=context)
            if llm_result.used_fallback:
                return IntelligentTranscriptionResult(
                    local.ok,
                    raw,
                    local.output_text or raw,
                    selected_mode,
                    "local",
                    llm_result.error_message,
                    True,
                )
            if selected_provider == "local":
                return local

        if selected_provider != "local":
            try:
                external = self._external_providers[selected_provider]
                output = str(external(raw, selected_mode) or "").strip()
                if not output:
                    raise RuntimeError("provider externo retornou texto vazio")
                return IntelligentTranscriptionResult(
                    True, raw, output, selected_mode, selected_provider
                )
            except Exception as exc:
                local = self._process_local(raw, selected_mode, context=context)
                return IntelligentTranscriptionResult(
                    local.ok,
                    raw,
                    local.output_text or raw,
                    selected_mode,
                    "local",
                    f"Falha no provider {selected_provider}: {exc}",
                    True,
                )

        return self._process_local(raw, selected_mode, context=context)

    def _process_local(
        self, raw: str, mode: str, *, context: str | None = None
    ) -> IntelligentTranscriptionResult:
        try:
            review_context = context or (
                "codex_prompt"
                if mode == "codex"
                else ("relatorio_campo" if mode == "relatorio" else "standalone")
            )
            reviewed = self._local_reviewer.review(
                raw, context=review_context
            ).reviewed_text
            reviewed = reviewed or raw
            if mode == "codex":
                output = self._organize_codex(reviewed)
            elif mode == "relatorio":
                output = self._organize_report(reviewed)
            else:
                output = reviewed
            return IntelligentTranscriptionResult(
                True, raw, output or raw, mode, "local"
            )
        except Exception as exc:
            return IntelligentTranscriptionResult(
                True,
                raw,
                raw,
                mode,
                "local",
                f"Falha na revisão local: {exc}",
                True,
            )

    @staticmethod
    def _normalize_mode(mode: str | None) -> str:
        selected = str(mode or transcription_review_default_mode()).strip().lower()
        return selected if selected in SUPPORTED_TRANSCRIPTION_MODES else transcription_review_default_mode()

    @staticmethod
    def _organize_codex(text: str) -> str:
        items = [
            item.strip(" -.;")
            for item in re.split(
                r"(?:[.!?]\s+|\s+(?:e\s+depois|depois|além disso)\s+)",
                text,
                flags=re.IGNORECASE,
            )
            if item.strip(" -.;")
        ]
        if not items:
            return text

        sections: dict[str, list[str]] = {
            "Contexto": [],
            "Objetivo": [],
            "Mudanças desejadas": [],
            "Testes esperados": [],
            "Critérios de aceite": [],
        }
        patterns = (
            (
                "Testes esperados",
                r"\b(test(?:e|es|ar|ando)?|pytest|validar|validação)\b",
            ),
            (
                "Critérios de aceite",
                r"\b(critério|critérios|aceite|considerar pronto)\b",
            ),
            (
                "Contexto",
                r"\b(contexto|cenário|atualmente|problema|erro|falha)\b",
            ),
            (
                "Objetivo",
                r"\b(objetivo|precisamos|quero|queremos|finalidade)\b",
            ),
        )
        for item in items:
            section = next(
                (
                    name
                    for name, pattern in patterns
                    if re.search(pattern, item, re.IGNORECASE)
                ),
                "Mudanças desejadas",
            )
            sections[section].append(item)

        lines: list[str] = []
        for title, values in sections.items():
            if lines:
                lines.append("")
            lines.append(f"{title}:")
            if values:
                lines.extend(
                    f"- {AudioTranscriptionIntelligenceService._codex_item(value)}"
                    for value in values
                )
            else:
                lines.append("- não informado")
        return "\n".join(lines)

    @staticmethod
    def _codex_item(text: str) -> str:
        item = str(text or "").strip(" -.;")
        if not item:
            return "não informado"
        return f"{item[0].upper() + item[1:]}."

    @staticmethod
    def _organize_report(text: str) -> str:
        paragraphs = [
            part.strip()
            for part in re.split(r"\n{2,}", text)
            if part.strip()
        ]
        return "\n\n".join(paragraphs)
