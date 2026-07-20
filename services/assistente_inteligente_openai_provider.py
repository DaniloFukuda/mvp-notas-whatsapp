"""Provider real (OpenAI) do Assistente Inteligente Ciclus (Modulo 2B.1).

Este modulo implementa a MESMA interface de MockAssistenteProvider:
    generate(request: AssistenteRequest) -> AssistenteResponse

Reutiliza a camada neutra services.llm_text_generation_service.generate_text,
ja existente no projeto, que por sua vez fala com a OpenAI Responses API
via HTTP (sem SDK pesado). O provider aqui:

- e EXCLUSIVAMENTE consultivo (nunca escreve/executa/alteracao);
- nao envia tools, functions ou qualquer definicao de acao;
- nao inclui sender_key, telefone ou identificadores no prompt;
- envia apenas a mensagem do usuario e um historico curto;
- trunca a saida em ASSISTENTE_INTELIGENTE_MAX_OUTPUT_CHARS;
- em ausencia de chave, timeout, excecao ou resposta vazia, retorna
  ok=False com error_message CONTROLADO (sem expor OpenAI/token/stack/URL);
- e injetavel: em testes usa um generator fake, jamais toca a rede.

O nome interno "Hermes" NUNCA aparece no prompt nem na resposta.
"""

from __future__ import annotations

import os

from services.llm_text_generation_service import (
    DEFAULT_MODEL,
    generate_text,
)


# Prompt-base fixo e seguro. Define nome externo, comportamento consultivo
# e as proibicoes permanentes. Nao menciona "Hermes".
_SYSTEM_INSTRUCTIONS = (
    "Voce e o Assistente Inteligente Ciclus, um auxiliar consultivo da "
    "Ciclus Agro.\n\n"
    "REGRA OBRIGATORIA: voce e EXCLUSIVAMENTE consultivo.\n"
    "- Nao crie, altere, exclua ou corrija dados, codigo, configuracoes, "
    "usuarios ou registros.\n"
    "- Nao execute comandos, SQL, shell, codigo ou ferramentas.\n"
    "- Nao use tool calling, function calling ou quaisquer acoes externas.\n"
    "- Nao afirme que realizou uma mudanca.\n"
    "- Se o usuario pedir uma alteracao, EXPLIQUE apenas: (1) o problema, "
    "(2) a justificativa, (3) o impacto e (4) a alteracao sugerida. "
    "Nunca a execute.\n"
    "- Diferencie fatos, interpretacao e sugestao.\n"
    "- Se faltar informacao, admita a limitacao; nao invente dados da Ciclus.\n"
    "- Responda em portugues do Brasil, de forma curta e clara.\n"
)


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


def _build_input(request):
    """Monta o texto de entrada: apenas mensagem + historico curto.

    Nunca inclui sender_key, telefone ou quaisquer identificadores.
    """
    parts = []
    history = list(getattr(request, "history", []) or [])
    for msg in history:
        role = (msg.role or "usuario").strip().lower()
        text = (msg.text or "").strip()
        if not text:
            continue
        label = "Usuario" if role == "user" else "Assistente"
        parts.append(f"{label}: {text}")
    current = (getattr(request, "message", "") or "").strip()
    if current:
        parts.append(f"Usuario: {current}")
    return "\n".join(parts).strip()


def _truncate(text, limit):
    if limit > 0 and len(text) > limit:
        # Trunca com seguranca, sem quebrar palavras de forma perigosa.
        return text[:limit].rstrip() + "\n[resposta truncada]"
    return text


class AssistenteInteligenteOpenAIProvider:
    """Provider real (OpenAI) isolado e configuravel.

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
    ):
        # generator: assinatura (instructions, input_text) -> LlmTextGenerationResult.
        # Default = generate_text (rede real), injetavel para testes.
        self._generator = generator
        if model is not None:
            self._model = model
        else:
            self._model = _env_str(
                "ASSISTENTE_INTELIGENTE_MODEL", DEFAULT_MODEL
            ) or DEFAULT_MODEL
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

    def generate(self, request):
        # Import local para evitar import circular com o servico
        # (que ja importa este provider no topo).
        from services.assistente_inteligente_service import (
            AssistenteResponse,
        )

        instructions = _SYSTEM_INSTRUCTIONS
        input_text = _build_input(request)

        generator = (
            self._generator if self._generator is not None else generate_text
        )
        try:
            result = generator(
                instructions,
                input_text,
                model=self._model,
                timeout=self._timeout,
            )
        except Exception:
            # Falha de rede/timeout/JSON: erro controlado, sem detalhes.
            return AssistenteResponse(
                ok=False,
                text="",
                provider="openai",
                used_fallback=True,
                error_message="Indisponibilidade temporaria do provider.",
            )

        if result is None or not getattr(result, "ok", False):
            return AssistenteResponse(
                ok=False,
                text="",
                provider="openai",
                used_fallback=True,
                error_message="Resposta invalida ou vazia do provider.",
            )

        raw = str(getattr(result, "output_text", "") or "").strip()
        if not raw:
            return AssistenteResponse(
                ok=False,
                text="",
                provider="openai",
                used_fallback=True,
                error_message="Resposta vazia do provider.",
            )

        return AssistenteResponse(
            ok=True,
            text=_truncate(raw, int(self._max_output)),
            provider="openai",
            used_fallback=False,
            error_message="",
        )


def build_openai_provider(
    generator=None,
    *,
    model=None,
    timeout_seconds=None,
    max_output_chars=None,
):
    """Construtor injetavel usado pelo servico e pelos testes."""
    return AssistenteInteligenteOpenAIProvider(
        generator=generator,
        model=model,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
