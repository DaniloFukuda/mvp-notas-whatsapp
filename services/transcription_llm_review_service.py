"""Revisao opcional de transcricoes por LLM, com falha segura."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

DEFAULT_MODEL = "gpt-5.4-mini"

AGRO_REVIEW_INSTRUCTIONS = """Transforme o texto fornecido em texto profissional, claro e fiel ao contexto.

Regras obrigatórias:
- Corrija português, pontuação, clareza e frases quebradas.
- Corrija palavras claramente mal reconhecidas pelo sistema de fala quando o contexto
  indicar a forma correta com alta confiança.
- Mantenha rigorosamente o sentido original.
- Não invente fatos novos.
- Não adicione números, nomes, datas ou valores que não estejam no texto.
- Não invente áreas, hectares, culturas, produtos ou recomendações.
- Preserve nomes de fazendas, pessoas, talhões, culturas, valores, datas, números e unidades.
- Se houver ambiguidade, escreva de forma conservadora.
- Se o texto estiver muito incompreensível, corrompido ou sem sentido claro, retorne
  exatamente o texto original.
- Nunca traduza para outro idioma.
- Não use linguagem comercial exagerada.
- Não crie diagnóstico técnico que não tenha sido falado.
- Não mencione transcrição, IA, Whisper ou áudio.
- Retorne somente o texto final.

Vocabulário comum deste sistema e do contexto técnico:
WhatsApp, áudio, transcrição, Codex, OpenAI, ChatGPT, Python, Git, branch, commit,
pull request, deploy, servidor, webhook, Ciclus, OLT, contentor, aluguer, RDV,
visita técnica e relatório."""

_PORTUGUESE_ANCHOR_WORDS = {
    "a",
    "agora",
    "aqui",
    "as",
    "com",
    "da",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "eu",
    "foi",
    "na",
    "nao",
    "não",
    "no",
    "o",
    "os",
    "para",
    "por",
    "que",
    "se",
    "tem",
    "um",
    "uma",
    "vou",
}


@dataclass(frozen=True)
class LlmReviewResult:
    ok: bool
    provider: str
    model: str
    output_text: str
    error_message: str | None = None
    used_fallback: bool = False


def transcription_llm_review_enabled() -> bool:
    return os.getenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "sim",
        "on",
    }


def review_transcription_with_llm(
    raw_text: str, context: str = "relatorio_agro"
) -> LlmReviewResult:
    """Revisa apenas texto. O chamador aplica o fallback local em qualquer falha.

    Wrapper especifico de revisao: usa a camada generica de geracao de texto
    (services.llm_text_generation_service) e aplica a heuristica de revisao
    localmente, preservando o comportamento observavel anterior.
    """
    raw = str(raw_text or "").strip()
    provider = os.getenv("TRANSCRIPTION_LLM_PROVIDER", "openai").strip().lower() or "openai"
    model = os.getenv("TRANSCRIPTION_LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    def fallback(message: str) -> LlmReviewResult:
        return LlmReviewResult(False, provider, model, "", message, True)

    if not transcription_llm_review_enabled():
        return LlmReviewResult(
            False, provider, model, "", "Revisão por LLM desabilitada.", False
        )
    if not raw:
        return fallback("Transcrição vazia.")

    from services.llm_text_generation_service import generate_text

    result = generate_text(
        AGRO_REVIEW_INSTRUCTIONS,
        f"Contexto: {context}\n\nTexto a revisar:\n{raw}",
    )
    if not result.ok:
        return LlmReviewResult(
            False, result.provider, result.model, "", result.error_message, True
        )
    if _looks_like_bad_review(raw, result.output_text):
        return fallback("OpenAI retornou uma revisão possivelmente corrompida.")
    return LlmReviewResult(
        True, result.provider, result.model, result.output_text
    )


def _looks_like_bad_review(raw_text: str, output_text: str) -> bool:
    """Evita aceitar resposta revisada com cara de texto corrompido/alucinado."""
    raw = str(raw_text or "").strip()
    output = str(output_text or "").strip()
    if not output:
        return True

    raw_words = _words(raw)
    output_words = _words(output)
    if not output_words:
        return True

    if len(output) > max(len(raw) * 4, 240) and len(raw) < 160:
        return True

    # Áudio curto não deve virar uma resposta longa, cheia de termos não falados.
    if len(raw_words) <= 10 and len(output_words) > max(22, len(raw_words) * 4):
        return True

    unknown_ratio = _unknown_word_ratio(raw_words, output_words)
    if len(raw_words) >= 3 and unknown_ratio > 0.75 and len(output_words) > len(raw_words) + 4:
        return True

    uppercase_tokens = re.findall(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3,}\b", output)
    if output_words and len(uppercase_tokens) / len(output_words) > 0.35:
        return True

    weird_chars = re.findall(r"[^\w\s.,;:!?()/%ºª°$+-]", output, flags=re.UNICODE)
    if len(weird_chars) >= 2:
        return True

    if len(output_words) >= 8:
        anchor_count = sum(1 for word in output_words if word.lower() in _PORTUGUESE_ANCHOR_WORDS)
        if anchor_count == 0:
            return True

    return False


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ÿ0-9]+", text or "")


def _unknown_word_ratio(raw_words: list[str], output_words: list[str]) -> float:
    raw_set = {_normalize_word(word) for word in raw_words if _normalize_word(word)}
    if not raw_set:
        return 0.0
    output_set = [_normalize_word(word) for word in output_words if _normalize_word(word)]
    if not output_set:
        return 1.0
    unknown = [word for word in output_set if word not in raw_set]
    return len(unknown) / len(output_set)


def _normalize_word(word: str) -> str:
    return str(word or "").strip().lower()
