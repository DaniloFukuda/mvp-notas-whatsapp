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


SUPPORTED_TRANSCRIPTION_MODES = {"literal", "revisada", "codex", "relatorio"}
DEFAULT_TRANSCRIPTION_MODE = "revisada"
ExternalProvider = Callable[[str, str], str]


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
    ) -> None:
        self._local_reviewer = local_reviewer or AudioTranscriptionReviewService()
        self._external_providers = dict(external_providers or {})

    def process(
        self,
        raw_text: str,
        *,
        mode: str | None = None,
        provider: str | None = None,
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
                local = self._process_local(raw, selected_mode)
                return IntelligentTranscriptionResult(
                    local.ok,
                    raw,
                    local.output_text or raw,
                    selected_mode,
                    "local",
                    f"Falha no provider {selected_provider}: {exc}",
                    True,
                )

        return self._process_local(raw, selected_mode)

    def _process_local(
        self, raw: str, mode: str
    ) -> IntelligentTranscriptionResult:
        try:
            context = "codex_prompt" if mode == "codex" else (
                "relatorio_campo" if mode == "relatorio" else "standalone"
            )
            reviewed = self._local_reviewer.review(raw, context=context).reviewed_text
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

        errors = [
            item for item in items
            if re.search(r"\b(erro|falha|inválid|alugad|indisponível)\w*", item, re.IGNORECASE)
        ]
        rules = [item for item in items if item not in errors]
        lines = ["Ajustes necessários:", ""]
        for index, item in enumerate(rules or items, start=1):
            lines.append(f"{index}. {item[0].upper() + item[1:]}.")
        if errors:
            lines.extend(["", "Mensagens e comportamentos de erro:", ""])
            lines.extend(f"- {item[0].upper() + item[1:]}." for item in errors)
        lines.extend(["", "Critérios de aceite:", ""])
        lines.extend(
            f"- Confirmar que {item[0].lower() + item[1:]}."
            for item in items
        )
        return "\n".join(lines)

    @staticmethod
    def _organize_report(text: str) -> str:
        paragraphs = [
            part.strip()
            for part in re.split(r"\n{2,}", text)
            if part.strip()
        ]
        return "\n\n".join(paragraphs)
