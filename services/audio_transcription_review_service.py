"""Revisao local e conservadora de transcricoes de audio."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Mapping


DEFAULT_GLOSSARY = (
    "Codex",
    "WhatsApp",
    "botões",
    "listas",
    "Sim",
    "Não",
    "contentor",
    "contentores",
    "entrega",
    "recolha",
    "operador",
    "alugado",
    "disponível",
    "indisponível",
    "relatório",
    "visita técnica",
    "fazenda",
    "aplicação",
    "serviço",
    "PDF",
    "RDV",
    "comprovante",
)

_KNOWN_VARIANTS = {
    "cadax": "Codex",
    "codéx": "Codex",
    "whats app": "WhatsApp",
    "whatsapp": "WhatsApp",
    "botes": "botões",
    "bot oes": "botões",
    "contitor": "contentor",
    "contetor": "contentor",
    "contentor": "contentor",
    "contitores": "contentores",
    "contetores": "contentores",
    "contentores": "contentores",
    "velho gada": "alugado",
    "relatorio": "relatório",
    "visita tecnica": "visita técnica",
    "disponivel": "disponível",
    "indisponivel": "indisponível",
    "aplicacao": "aplicação",
    "servico": "serviço",
}

_CONTEXT_VARIANTS = {
    "visita_observacao": {"continer": "contentor", "container": "contentor"},
    "visita_descricao": {"continer": "contentor", "container": "contentor"},
    "relatorio_campo": {"continer": "contentor", "container": "contentor"},
}

_TECHNICAL_COMMANDS = {
    "menu",
    "visita",
    "iniciar visita",
    "nova visita",
    "finalizar observações",
    "fechar visita",
    "cancelar",
    "sair",
    "sim",
    "não",
    "nao",
}


@dataclass(frozen=True)
class ReviewedTranscription:
    raw_text: str
    reviewed_text: str
    changed: bool
    warnings: list[str]


def transcription_review_enabled() -> bool:
    """A revisao e habilitada por padrao e pode ser desligada por ambiente."""
    value = os.getenv("TRANSCRIPTION_REVIEW_ENABLED")
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


class AudioTranscriptionReviewService:
    """Primeira implementacao rule-based, sem chamadas a APIs externas."""

    def review(
        self,
        raw_text: str,
        *,
        context: str = "standalone",
        glossary: Iterable[str] | Mapping[str, str] | None = None,
    ) -> ReviewedTranscription:
        raw = str(raw_text or "").strip()
        if not raw:
            return ReviewedTranscription(raw, "", False, ["empty_transcription"])
        if not transcription_review_enabled():
            return ReviewedTranscription(raw, raw, False, [])

        text = self._normalize_spacing(raw)
        replacements = dict(_KNOWN_VARIANTS)
        replacements.update(_CONTEXT_VARIANTS.get(context, {}))
        replacements.update(self._glossary_replacements(glossary))
        text = self._replace_terms(text, replacements)
        text = self._remove_obvious_repetitions(text)
        if text.casefold() in _TECHNICAL_COMMANDS or re.fullmatch(r"\d+", text):
            return ReviewedTranscription(raw, text, text != raw, [])
        text = self._improve_punctuation(text)
        text = self._normalize_spacing(text)

        changed = text != raw
        warnings: list[str] = []
        similarity = SequenceMatcher(None, raw.casefold(), text.casefold()).ratio()
        if changed and similarity < 0.82:
            warnings.append("substantial_review")
        return ReviewedTranscription(raw, text, changed, warnings)

    @staticmethod
    def _glossary_replacements(
        glossary: Iterable[str] | Mapping[str, str] | None,
    ) -> dict[str, str]:
        if glossary is None:
            terms: Iterable[str] = DEFAULT_GLOSSARY
            return {term.casefold(): term for term in terms}
        if isinstance(glossary, Mapping):
            return {str(source).casefold(): str(target) for source, target in glossary.items()}
        return {str(term).casefold(): str(term) for term in glossary}

    @staticmethod
    def _replace_terms(text: str, replacements: Mapping[str, str]) -> str:
        for source in sorted(replacements, key=len, reverse=True):
            target = replacements[source]
            pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
            text = pattern.sub(target, text)
        return text

    @staticmethod
    def _remove_obvious_repetitions(text: str) -> str:
        return re.sub(
            r"\b([\wÀ-ÿ]+)(?:\s+\1\b)+",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _improve_punctuation(text: str) -> str:
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"([.;:!?]|,(?!\d))(?=\S)", r"\1 ", text)
        # Pausas conservadoras em transcricoes muito longas, sem tocar em numeros.
        if len(text) >= 100 and not re.search(r"[.!?]", text):
            text = re.sub(
                r"\s+(e\s+depois|depois|porém|mas|e\s+então|então)\s+",
                lambda match: (
                    f". {(match.group(1)[2:] if match.group(1).casefold().startswith('e ') else match.group(1)).capitalize()} "
                ),
                text,
                count=2,
                flags=re.IGNORECASE,
            )
        if 40 <= len(text) <= 300 and text[-1] not in ".!?":
            text += "."
        if text:
            text = text[0].upper() + text[1:]
        return text

    @staticmethod
    def _normalize_spacing(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return text.strip()
