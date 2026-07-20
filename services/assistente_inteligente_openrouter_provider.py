"""Provider generico do OpenRouter para o Assistente Inteligente Ciclus.

Este modulo implementa a MESMA interface dos providers mock e OpenAI:
    generate(request: AssistenteRequest) -> AssistenteResponse

Fala com o endpoint de chat completions do OpenRouter via HTTP
(requests.post), usando a OPENROUTER_API_KEY do projeto (futuramente
propria do projeto). O modelo e configuravel e NAO fica hardcoded.

Diretriz permanente: o Assistente Inteligente Ciclus e EXCLUSIVAMENTE
consultivo e somente leitura. Este provider:

- nunca cria, altera, exclui ou corrige dados;
- nunca executa SQL, shell, codigo ou ferramentas;
- nao envia tools, functions, tool_choice, function_call nem qualquer
  formato de acao executavel;
- nao inclui sender_key, telefone, dados de RDV/KM/visitas ou quaisquer
  identificadores internos no payload;
- envia apenas o prompt-base de seguranca, um historico curto validado e a
  mensagem atual;
- trunca a saida em ASSISTENTE_INTELIGENTE_MAX_OUTPUT_CHARS;
- em ausencia de chave, timeout, excecao de conexao, HTTP 4xx/5xx, JSON
  invalido, estrutura invalida ou texto vazio, retorna ok=False com
  error_message CONTROLADO (sem expor OpenRouter/Hy3/Hermes/chave/endpoint/
  status HTTP/token/stack/payload/request ID);
- e injetavel: em testes usa um gerador HTTP fake, jamais toca a rede.

O prompt-base reutiliza as regras ja validadas no provider OpenAI
(services.assistente_inteligente_openai_provider._SYSTEM_INSTRUCTIONS),
mantendo um unico ponto de verdade para as restricoes consultivas.
O nome interno "Hermes" NUNCA aparece no prompt nem na resposta.
"""

from __future__ import annotations

import os

import requests

# Reutiliza o prompt-base de seguranca ja validado no provider OpenAI.
# Nao altera aquele modulo: apenas importa a constante existente.
from services.assistente_inteligente_openai_provider import (  # noqa: E402
    _SYSTEM_INSTRUCTIONS,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "tencent/hy3:free"


# ---------------------------------------------------------------------------
# Helpers de ambiente (mesmos defaults seguros dos demais providers)
# ---------------------------------------------------------------------------

def _env_str(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _env_float(name, default):
    try:
        raw = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if raw > 0:
        return raw
    return default


def _positive_int_env(name, default):
    try:
        raw = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if raw > 0:
        return raw
    return default


def _build_messages(request):
    """Monta as mensagens: system + historico curto + usuario atual.

    Nunca inclui sender_key, telefone ou quaisquer identificadores.
    O historico respeita as roles ja normalizadas ('user'/'assistant').
    """
    messages = [{"role": "system", "content": _SYSTEM_INSTRUCTIONS}]
    history = list(getattr(request, "history", []) or [])
    for msg in history:
        role = (msg.role or "user").strip().lower()
        if role not in ("user", "assistant"):
            role = "user"
        text = (msg.text or "").strip()
        if not text:
            continue
        messages.append({"role": role, "content": text})
    current = (getattr(request, "message", "") or "").strip()
    if current:
        messages.append({"role": "user", "content": current})
    return messages


def _truncate(text, limit):
    if limit > 0 and len(text) > limit:
        return text[:limit].rstrip() + "\n[resposta truncada]"
    return text


def _extract_content(data):
    """Extrai somente choices[0].message.content de forma defensiva."""
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    msg = first.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if not isinstance(content, str):
        return ""
    return content.strip()


class AssistenteInteligenteOpenRouterProvider:
    """Provider isolado do OpenRouter (chat/completions).

    Assinatura esperada por AssistenteInteligenteService:
        generate(request) -> AssistenteResponse
    """

    def __init__(
        self,
        generator=None,
        *,
        model=None,
        timeout_seconds=None,
        max_output_chars=None,
        api_key=None,
    ):
        # generator: assinatura requests.post-like:
        #   (url, *, headers=..., json=..., timeout=...) -> response-like
        #   (deve expor .raise_for_status() e .json()).
        # Default = requests.post (rede real), injetavel para testes.
        self._generator = generator
        if model is not None:
            self._model = model
        else:
            self._model = _env_str(
                "ASSISTENTE_INTELIGENTE_OPENROUTER_MODEL",
                DEFAULT_OPENROUTER_MODEL,
            ) or DEFAULT_OPENROUTER_MODEL
        if timeout_seconds is not None:
            self._timeout = timeout_seconds
        else:
            self._timeout = _env_float(
                "ASSISTENTE_INTELIGENTE_TIMEOUT_SECONDS", 20.0
            )
        if max_output_chars is not None:
            self._max_output = max_output_chars
        else:
            self._max_output = _positive_int_env(
                "ASSISTENTE_INTELIGENTE_MAX_OUTPUT_CHARS", 2000
            )
        # api_key injetavel (testes) ou None -> lida do env em generate().
        self._api_key = api_key

    def generate(self, request):
        # Import local para evitar import circular com o servico
        # (que ja importa este provider no topo).
        from services.assistente_inteligente_service import (
            AssistenteResponse,
        )

        # Chave injetada em testes ou, caso contrario, do ambiente.
        # Nunca e empacotada no payload nem exposta na resposta.
        api_key = (
            self._api_key
            if self._api_key
            else _env_str("OPENROUTER_API_KEY", "")
        )

        if not api_key:
            return AssistenteResponse(
                ok=False,
                text="",
                provider="openrouter",
                used_fallback=True,
                error_message="Credencial do provider ausente.",
            )

        messages = _build_messages(request)
        payload = {"model": self._model, "messages": messages}

        http = (
            self._generator if self._generator is not None else requests.post
        )
        try:
            response = http(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            # Falha de rede/timeout/JSON: erro controlado, sem detalhes.
            return AssistenteResponse(
                ok=False,
                text="",
                provider="openrouter",
                used_fallback=True,
                error_message="Indisponibilidade temporaria do provider.",
            )

        raw = _extract_content(data)
        if not raw:
            return AssistenteResponse(
                ok=False,
                text="",
                provider="openrouter",
                used_fallback=True,
                error_message="Resposta vazia ou invalida do provider.",
            )

        return AssistenteResponse(
            ok=True,
            text=_truncate(raw, int(self._max_output)),
            provider="openrouter",
            used_fallback=False,
            error_message="",
        )


def build_openrouter_provider(
    generator=None,
    *,
    model=None,
    timeout_seconds=None,
    max_output_chars=None,
    api_key=None,
):
    """Construtor injetavel usado pelo servico e pelos testes."""
    provider = AssistenteInteligenteOpenRouterProvider(
        generator=generator,
        model=model,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
    if api_key is not None:
        provider._api_key = api_key
    return provider
