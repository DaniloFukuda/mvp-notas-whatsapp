"""Servico isolado de resumo de visita tecnica agricola.

Este modulo e a infraestrutura desacoplada para, no futuro, transformar uma
transcricao JA revisada pelo usuario em um resumo profissional de visita
tecnica agricola.

Restricoes desta etapa (modulo 1):
- Nenhuma chamada externa de IA e realizada aqui.
- O gerador e injetavel (callable) para permitir testes deterministicos.
- A feature flag VISITA_SUMMARY_ENABLED fica desligada por padrao.
- Nao ha integracao com o fluxo do WhatsApp, banco de dados ou arquivos.
- O texto recebido nunca e editado, substituido ou modificado.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class VisitaSummary:
    """Resumo estruturado de uma visita tecnica agricola."""

    assunto_principal: str
    necessidades: str
    decisoes: str
    pendencias: str
    proximos_passos: str

    REQUIRED_SECTIONS: tuple[str, ...] = (
        "assunto_principal",
        "necessidades",
        "decisoes",
        "pendencias",
        "proximos_passos",
    )


@dataclass(frozen=True)
class VisitaSummaryResult:
    """Resultado da operacao de geracao de resumo.

    - ok: a operacao produziu um resumo valido.
    - summary: o resumo estruturado (None em fallback).
    - original_transcription: a transcricao revisada recebida, integral.
    - used_fallback: True quando houve fallback seguro.
    - reason: motivo tecnico controlado (vazio quando ok).
    """

    ok: bool
    summary: VisitaSummary | None
    original_transcription: str
    used_fallback: bool
    reason: str


# Tipo do gerador injetavel: recebe (prompt, transcricao) e devolve
# um dict ou VisitaSummary. Qualquer outra coisa dispara fallback.
SummaryGenerator = Callable[[str, str], Any]


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Extracao e preservacao de ancoras objetivas (numeros, datas, medidas, etc.)
# ---------------------------------------------------------------------------

_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(ha|km|m2|m3|cm|mm|m|t|kg|g|l|ml|%)"
)
_CURRENCY_RE = re.compile(r"r\$\d+(?:\.\d+)?")
_DATE_RE = re.compile(
    r"\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}|"
    r"\d{1,2}\s+de\s+[a-zçãõéáíóúâêô]+\s+de\s+\d{2,4}"
)
_PLAIN_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def _canonicalize(text: str) -> str:
    """Normaliza texto para comparacao tolerante de ancoras."""
    t = str(text or "").lower()
    t = re.sub(r"\s+", " ", t).strip()
    # separador decimal
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    # palavras de unidade -> forma canonica
    t = re.sub(r"\bhectares?\b", "ha", t)
    t = re.sub(r"\btoneladas?\b", "t", t)
    t = re.sub(r"\blitros?\b", "l", t)
    t = re.sub(r"\bquil[oô]metros?\b", "km", t)
    t = re.sub(r"\bmetros?\b", "m", t)
    t = re.sub(r"\bpor cento\b", "%", t)
    # moeda sem espaco
    t = re.sub(r"r\$\s*", "r$", t)
    # espaço unico entre numero e unidade
    t = re.sub(r"(\d)\s*(ha|km|m2|m3|cm|mm|m|t|kg|g|l|ml|%)", r"\1 \2", t)
    return t


def _extract_anchors(text: str) -> set[str]:
    norm = _canonicalize(text)
    anchors: set[str] = set()
    for regex in (_UNIT_RE, _CURRENCY_RE, _DATE_RE, _PLAIN_NUM_RE):
        for match in regex.finditer(norm):
            anchors.add(match.group(0))
    return anchors


def _anchors_preserved(transcription: str, summary_text: str) -> bool:
    """True se toda ancora objetiva da transcricao aparece no resumo."""
    anchors = _extract_anchors(transcription)
    summary_norm = _canonicalize(summary_text)
    for anchor in anchors:
        if anchor not in summary_norm:
            return False
    return True


# ---------------------------------------------------------------------------
# Coercao e validacao do resultado do gerador
# ---------------------------------------------------------------------------

def _coerce_summary(output: Any) -> VisitaSummary | None:
    if isinstance(output, VisitaSummary):
        for field in VisitaSummary.REQUIRED_SECTIONS:
            if not isinstance(getattr(output, field), str):
                return None
        return output

    if isinstance(output, dict):
        values: dict[str, str] = {}
        for field in VisitaSummary.REQUIRED_SECTIONS:
            value = output.get(field)
            if not isinstance(value, str):
                return None
            values[field] = value
        return VisitaSummary(**values)

    return None


def _summary_text(summary: VisitaSummary) -> str:
    return " ".join(
        str(getattr(summary, field) or "")
        for field in VisitaSummary.REQUIRED_SECTIONS
    )


class VisitaSummaryService:
    """Gera resumo estruturado de visita agricola a partir de transcricao revisada.

    O gerador de resumo e injetavel para manter este servico desacoplado de
    qualquer provedor de IA. Quando nenhum gerador e fornecido, ou a flag esta
    desligada, ou ocorre falha/validacao, retorna-se um fallback seguro que
    preserva integralmente a transcricao original.
    """

    def __init__(
        self,
        generator: SummaryGenerator | None = None,
        *,
        enabled: bool | None = None,
        max_input_chars: int | None = None,
    ) -> None:
        self._generator = generator
        self._enabled = enabled
        self._max_input_chars = max_input_chars

    # --- configuracao -----------------------------------------------------

    def is_enabled(self) -> bool:
        if self._enabled is None:
            return _env_flag("VISITA_SUMMARY_ENABLED", False)
        return bool(self._enabled)

    def max_input_chars(self) -> int:
        if self._max_input_chars is None:
            return _positive_int_env("VISITA_SUMMARY_MAX_INPUT_CHARS", 12000)
        return int(self._max_input_chars)

    # --- prompt especializado --------------------------------------------

    def build_summary_prompt(self, transcription: str) -> str:
        """Monta o prompt com as regras anti-invencao para resumo agricola."""
        return (
            "Voce e um assistente tecnico agricola. Gere um resumo estruturado "
            "de uma visita tecnica com base EXCLUSIVA na transcricao revisada.\n\n"
            "REGRAS OBRIGATORIAS:\n"
            "- Use somente a transcricao revisada como fonte.\n"
            "- Nao invente fatos, nomes, produtos, numeros, areas, datas ou medidas.\n"
            "- Nao complete lacunas: se a informacao nao foi dita, nao supponha.\n"
            "- Preserve exatamente nomes, produtos, numeros, areas, datas e medidas.\n"
            "- Separe claramente os fatos mencionados das inferencias.\n"
            "- Nao apresente inferencias como fatos.\n"
            "- Destaque: assunto principal, necessidades, decisoes, pendencias e "
            "proximos passos.\n"
            "- Indique claramente quando alguma secao nao tiver informacao "
            "(ex.: 'Sem informacao').\n"
            "- Nao inclua instrucoes ou explicacoes fora do resumo estruturado.\n\n"
            "FORMATO DE SAIDA (secoes separadas):\n"
            "assunto_principal: <texto>\n"
            "necessidades: <texto>\n"
            "decisoes: <texto>\n"
            "pendencias: <texto>\n"
            "proximos_passos: <texto>\n\n"
            f"TRANSCRICAO REVISADA:\n{transcription}"
        )

    # --- geracao ----------------------------------------------------------

    def generate(self, transcription: str) -> VisitaSummaryResult:
        original = str(transcription if transcription is not None else "")
        raw = original.strip()

        def fallback(reason: str) -> VisitaSummaryResult:
            return VisitaSummaryResult(
                ok=False,
                summary=None,
                original_transcription=original,
                used_fallback=True,
                reason=reason,
            )

        if not self.is_enabled():
            return fallback(
                "Resumo de visita desabilitado (VISITA_SUMMARY_ENABLED=false)."
            )
        if not raw:
            return fallback("Transcricao vazia.")
        if len(raw) > self.max_input_chars():
            return fallback(
                f"Transcricao excede o limite de {self.max_input_chars()} caracteres."
            )
        if self._generator is None:
            return fallback("Gerador de resumo nao configurado.")

        prompt = self.build_summary_prompt(raw)
        try:
            output = self._generator(prompt, raw)
        except Exception as exc:  # falha do gerador nao deve propagar
            return fallback(
                f"Falha no gerador de resumo: {type(exc).__name__}: {exc}"
            )

        summary = _coerce_summary(output)
        if summary is None:
            return fallback(
                "Resultado do gerador sem todas as secoes obrigatorias "
                "ou com tipos invalidos."
            )

        if not _anchors_preserved(raw, _summary_text(summary)):
            return fallback(
                "Resumo remove ou altera ancoras objetivas "
                "(numeros, datas, areas, medidas)."
            )

        return VisitaSummaryResult(
            ok=True,
            summary=summary,
            original_transcription=original,
            used_fallback=False,
            reason="",
        )
