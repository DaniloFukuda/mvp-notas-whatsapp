"""Adaptador isolado entre VisitaSummaryService e a camada generica de LLM.

Reutiliza services.llm_text_generation_service.generate_text (camada neutra),
enviando separadamente:
- instructions = o prompt de resumo construido pelo VisitaSummaryService;
- input_text   = a transcricao revisada (nunca como texto a revisar).

O adaptador NAO:
- conhece regras de validacao de ancoras (isso e do VisitaSummaryService);
- usa AGRO_REVIEW_INSTRUCTIONS ou review_transcription_with_llm;
- cria cliente global em tempo de importacao;
- registra o conteudo de instructions/input_text em logs.

Em qualquer falha (vazio, nao estruturado, excecao), retorna None para que o
VisitaSummaryService aplique seu fallback seguro.
"""

from __future__ import annotations

import logging
import re

from services.llm_text_generation_service import generate_text
from services.visita_summary_service import VisitaSummary

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(
    r"^\s*(assunto_principal|necessidades|decisoes|pendencias|proximos_passos)"
    r"\s*[:\-]\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_summary_sections(text: str) -> dict[str, str] | None:
    """Extrai as 5 secoes do texto retornado pelo LLM.

    Retorna None se faltar alguma secao obrigatoria. A validacao de tipos e
    ancoras permanece no VisitaSummaryService.
    """
    if not text:
        return None
    found: dict[str, str] = {}
    for match in _SECTION_RE.finditer(text):
        key = match.group(1).lower()
        value = (match.group(2) or "").strip()
        if key not in found:
            found[key] = value
    if not all(k in found for k in VisitaSummary.REQUIRED_SECTIONS):
        return None
    return {k: found[k] for k in VisitaSummary.REQUIRED_SECTIONS}


class VisitaSummaryLlmAdapter:
    """SummaryGenerator que usa a camada generica de LLM para gerar o resumo.

    Assinatura esperada por VisitaSummaryService: generator(prompt, transcription).
    """

    def __init__(
        self,
        generator=None,
        *,
        enabled: bool | None = None,
        max_input_chars: int | None = None,
    ) -> None:
        # generator: callable (instructions, input_text) -> LlmTextGenerationResult.
        # Default = generate_text (rede real), injetavel para testes.
        self._generator = generator
        self._enabled = enabled
        self._max_input_chars = max_input_chars

    # --- configuracao (flag propria do resumo) -----------------------------

    def _is_enabled(self) -> bool:
        if self._enabled is None:
            import os

            value = os.getenv("VISITA_SUMMARY_ENABLED")
            if value is None:
                return False
            return value.strip().lower() in {"1", "true", "yes", "sim", "on"}
        return bool(self._enabled)

    def _max_chars(self) -> int:
        if self._max_input_chars is None:
            import os

            try:
                value = int(os.getenv("VISITA_SUMMARY_MAX_INPUT_CHARS", "12000"))
                return value if value > 0 else 12000
            except (TypeError, ValueError):
                return 12000
        return int(self._max_input_chars)

    # --- interface SummaryGenerator ----------------------------------------

    def __call__(self, prompt: str, transcription: str) -> object:
        # Feature flag do resumo: desligada nao chama provider nenhum.
        if not self._is_enabled():
            return None

        generator = self._generator if self._generator is not None else generate_text
        try:
            result = generator(
                prompt,  # instructions
                transcription,  # input_text
                max_input_chars=self._max_chars(),
            )
        except Exception as exc:  # falha do provider -> fallback do servico
            logger.warning(
                "Falha no provider LLM de resumo (%s); usando fallback.",
                type(exc).__name__,
            )
            return None

        if result is None or not getattr(result, "ok", False):
            return None

        output_text = getattr(result, "output_text", "") or ""
        if not output_text.strip():
            return None  # resposta vazia

        # None se nao estruturado -> servico usa fallback.
        return _parse_summary_sections(output_text)
