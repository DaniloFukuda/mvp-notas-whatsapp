"""Revisao opcional de transcricoes por LLM, com falha segura."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_INPUT_CHARS = 12000

AGRO_REVIEW_INSTRUCTIONS = """Transforme o texto fornecido em texto profissional para relatório agro.

Regras obrigatórias:
- Corrija português, pontuação e clareza e organize frases quebradas.
- Mantenha rigorosamente o sentido original.
- Não invente fatos, valores, nomes, datas, áreas, hectares, culturas, produtos ou recomendações.
- Preserve nomes de fazendas, pessoas, talhões, culturas, valores, datas, números e unidades.
- Se houver ambiguidade, escreva de forma conservadora.
- Não use linguagem comercial exagerada.
- Não crie diagnóstico técnico que não tenha sido falado.
- Produza texto natural, profissional e pronto para relatório de visita técnica.
- Não mencione transcrição, IA, Whisper ou áudio.
- Retorne somente o texto revisado."""


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
    """Revisa apenas texto. O chamador aplica o fallback local em qualquer falha."""
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
    if provider != "openai":
        return fallback(f"Provider de revisão LLM não suportado: {provider}.")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return fallback("OPENAI_API_KEY não configurada.")

    max_chars = _positive_int_env(
        "TRANSCRIPTION_LLM_MAX_INPUT_CHARS", DEFAULT_MAX_INPUT_CHARS
    )
    if len(raw) > max_chars:
        return fallback(
            f"Transcrição excede o limite de {max_chars} caracteres para revisão por LLM."
        )

    timeout = _positive_float_env(
        "TRANSCRIPTION_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
    )
    payload = {
        "model": model,
        "instructions": AGRO_REVIEW_INSTRUCTIONS,
        "input": f"Contexto: {context}\n\nTexto a revisar:\n{raw}",
    }
    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        output = _extract_output_text(response.json())
        if not output:
            return fallback("OpenAI retornou uma resposta vazia.")
        return LlmReviewResult(True, provider, model, output)
    except Exception as exc:
        return fallback(f"Falha na revisão OpenAI: {type(exc).__name__}: {exc}")


def _extract_output_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = str(data.get("output_text") or "").strip()
    if direct:
        return direct
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = str(content.get("text") or "").strip()
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default
