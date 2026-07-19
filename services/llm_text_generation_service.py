"""Camada generica de geracao de texto via LLM (OpenAI Responses API).

Esta camada e deliberadamente neutra: NAO conhece revisao de transcricao,
resumo de visita, secoes agricolas, heuristicas de revisao nem fluxo do
WhatsApp. Ela apenas envia (instructions, input_text) ao provider configurado
e devolve o texto gerado, com tratamento de erro e fallback seguro.

Cada chamador e responsavel por sua propria feature flag (ex.:
TRANSCRIPTION_LLM_REVIEW_ENABLED, VISITA_SUMMARY_ENABLED). Esta camada nao
consulta flags de funcionalidade especifica.

Reaproveita: provider, modelo, OPENAI_API_KEY, endpoint, timeout, extracao de
output_text e o tratamento de HTTP/erros/vazio da abstracao anterior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

import requests


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_INPUT_CHARS = 12000


@dataclass(frozen=True)
class LlmTextGenerationResult:
    """Resultado neutro de geracao de texto via LLM."""

    ok: bool
    provider: str
    model: str
    output_text: str
    error_message: str | None = None
    used_fallback: bool = False


# Assinatura do gerador injetavel: (instructions, input_text) -> LlmTextGenerationResult
TextGeneratorCallable = Callable[[str, str], "LlmTextGenerationResult"]


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value.strip() if value else default


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _extract_output_text(data) -> str:
    """Extrai o texto de saida da resposta da OpenAI Responses API."""
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


def generate_text(
    instructions: str,
    input_text: str,
    *,
    generator: TextGeneratorCallable | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    max_input_chars: int | None = None,
) -> LlmTextGenerationResult:
    """Gera texto generico via LLM com instrucoes e input separados.

    Nao aplica nenhuma heuristica de negocio. Cada chamador deve validar o
    resultado e aplicar sua propria feature flag antes de chamar esta funcao.
    """
    provider = (provider or _env_str("TRANSCRIPTION_LLM_PROVIDER", "openai")).strip().lower() or "openai"
    model = (model or _env_str("TRANSCRIPTION_LLM_MODEL", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    api_key = api_key if api_key is not None else _env_str("OPENAI_API_KEY", "")
    resolved_timeout = timeout if timeout is not None else _positive_float_env(
        "TRANSCRIPTION_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
    )
    resolved_max = max_input_chars if max_input_chars is not None else _positive_int_env(
        "TRANSCRIPTION_LLM_MAX_INPUT_CHARS", DEFAULT_MAX_INPUT_CHARS
    )

    def fallback(message: str) -> LlmTextGenerationResult:
        return LlmTextGenerationResult(False, provider, model, "", message, True)

    if not instructions.strip() and not input_text.strip():
        return fallback("Instrucoes e texto de entrada vazios.")

    if provider != "openai":
        return fallback(f"Provider de LLM nao suportado: {provider}.")

    if len(input_text) > resolved_max:
        return fallback(
            f"Texto de entrada excede o limite de {resolved_max} caracteres."
        )

    if generator is not None:
        # Gerador injetado: determinístico e sem rede (usado em testes/mocks).
        # Contorna a exigência de api_key/HTTP, mas ainda respeita as validações
        # de entrada acima.
        try:
            result = generator(instructions, input_text)
        except Exception as exc:
            return fallback(f"Falha no gerador injetado: {type(exc).__name__}: {exc}")
        if result is None or not getattr(result, "ok", False):
            return fallback(getattr(result, "error_message", None) or "Gerador injetado retornou fallback.")
        output = getattr(result, "output_text", "") or ""
        if not output.strip():
            return fallback("Gerador injetado retornou resposta vazia.")
        return result

    if not api_key:
        return fallback("OPENAI_API_KEY nao configurada.")

    def http_generate() -> LlmTextGenerationResult:
        payload = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
        }
        try:
            response = requests.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=resolved_timeout,
            )
            response.raise_for_status()
            output = _extract_output_text(response.json())
            if not output:
                return fallback("OpenAI retornou uma resposta vazia.")
            return LlmTextGenerationResult(True, provider, model, output)
        except Exception as exc:  # erro HTTP, timeout, JSON inesperado, etc.
            return fallback(f"Falha na geracao OpenAI: {type(exc).__name__}: {exc}")

    return http_generate()
