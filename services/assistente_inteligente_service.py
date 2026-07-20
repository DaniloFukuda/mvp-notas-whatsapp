"""Serviço isolado de conversa do Assistente Inteligente Ciclus (Módulo 2A).

Este módulo substitui a resposta simulada diretamente escrita no handler
(Módulo 1) por uma interface isolada de geração de respostas. Nesta etapa
o provider é simulado (mock) e NENHUMA chamada externa é realizada.

Restrições permanentes do Assistente Inteligente Ciclus:
- exclusivamente consultivo;
- nunca cria, altera ou exclui registros;
- nunca executa SQL livre, shell, ou altera código/configurações;
- não faz commit, push, deploy ou reinício de serviços;
- não modifica usuários nem executa sugestões de alteração.

Este módulo:
- não importa OpenAI nem Hermes;
- não acessa banco ou esquema;
- mantém histórico curto EM MEMÓRIA, separado por telefone normalizado;
- usa apenas defaults seguros quando variáveis de ambiente estão ausentes;
- em falha do provider, devolve fallback sem expor detalhes internos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from services.assistente_inteligente_provider import build_mock_provider


# Defaults seguros (valores ausentes usam estes).
DEFAULT_PROVIDER = "mock"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_INPUT_CHARS = 2000
DEFAULT_MAX_HISTORY_TURNS = 6

# Fallback amigável quando o provider falha.
_FALLBACK_TEXT = (
    "⚠️ O Assistente Inteligente está temporariamente indisponível.\n\n"
    "Tente novamente em alguns instantes ou envie *sair* para voltar ao menu."
)


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AssistenteMessage:
    """Uma fala do histórico (autor + texto)."""

    role: str  # "user" | "assistant"
    text: str


@dataclass(frozen=True)
class AssistenteRequest:
    """Entrada do serviço.

    - sender_key: telefone normalizado (chave de isolamento).
    - message: texto já recebido do usuário (pode vir truncado pelo limite).
    - history: turnos anteriores daquele usuário (opcional).
    """

    sender_key: str
    message: str
    history: Sequence[AssistenteMessage] = field(default_factory=tuple)


@dataclass(frozen=True)
class AssistenteResponse:
    """Saída do serviço.

    - ok: operação produziu resposta válida.
    - text: texto a ser enviado (pode ser fallback).
    - provider: nome do provider usado ("mock").
    - used_fallback: True quando houve fallback seguro.
    - error_message: motivo controlado (vazio quando ok).
    """

    ok: bool
    text: str
    provider: str
    used_fallback: bool
    error_message: str


class AssistenteInteligenteService:
    """Gera respostas do Assistente Inteligente via provider injetável.

    O handler do WhatsApp NÃO conhece detalhes do provider: só chama
    generate(request). O provider é injetável para permitir testes
    determinísticos e para, no futuro, trocar o mock por Hermes/OpenAI.
    """

    # Comandos de saída não chegam aqui (tratados no handler).
    def __init__(
        self,
        provider=None,
        *,
        max_input_chars: int | None = None,
        max_history_turns: int | None = None,
    ) -> None:
        self._provider = provider if provider is not None else build_mock_provider(
            timeout_seconds=_env_float(
                "ASSISTENTE_INTELIGENTE_TIMEOUT_SECONDS",
                DEFAULT_TIMEOUT_SECONDS,
            )
        )
        self._max_input_chars = (
            max_input_chars
            if max_input_chars is not None
            else _env_int(
                "ASSISTENTE_INTELIGENTE_MAX_INPUT_CHARS",
                DEFAULT_MAX_INPUT_CHARS,
            )
        )
        self._max_history_turns = (
            max_history_turns
            if max_history_turns is not None
            else _env_int(
                "ASSISTENTE_INTELIGENTE_MAX_HISTORY_TURNS",
                DEFAULT_MAX_HISTORY_TURNS,
            )
        )
        # Histórico em memória, por telefone normalizado. Nunca compartilhado.
        self._history: dict[str, List[AssistenteMessage]] = {}

    # --- configuração -------------------------------------------------

    @property
    def provider_name(self) -> str:
        return _env_str("ASSISTENTE_INTELIGENTE_PROVIDER", DEFAULT_PROVIDER)

    def max_input_chars(self) -> int:
        return int(self._max_input_chars)

    def max_history_turns(self) -> int:
        return int(self._max_history_turns)

    # --- histórico ----------------------------------------------------

    def _history_key(self, sender_key: str) -> str:
        return (sender_key or "").strip()

    def get_history(self, sender_key: str) -> List[AssistenteMessage]:
        return list(self._history.get(self._history_key(sender_key), []))

    def _trim_history(self, sender_key: str) -> None:
        key = self._history_key(sender_key)
        turns = self._history.get(key, [])
        limit = self.max_history_turns()
        if limit > 0 and len(turns) > limit:
            # Mantém os turnos mais recentes.
            self._history[key] = turns[-limit:]

    def clear_history(self, sender_key: str) -> None:
        """Limpa o histórico daquele usuário (ao sair do Assistente)."""
        self._history.pop(self._history_key(sender_key), None)

    # --- geração ------------------------------------------------------

    def generate(self, request: AssistenteRequest) -> AssistenteResponse:
        sender_key = request.sender_key
        # 1) trim de espaços externos.
        raw = (request.message or "").strip()
        # 2) rejeitar texto vazio (não chama provider).
        if not raw:
            return AssistenteResponse(
                ok=False,
                text="",
                provider=self.provider_name,
                used_fallback=False,
                error_message="Mensagem vazia.",
            )
        # 3) limitar a entrada (não registrar nem ecoar o texto completo).
        if len(raw) > self.max_input_chars():
            return AssistenteResponse(
                ok=False,
                text=(
                    "Sua mensagem está um pouco longa para esta etapa de teste. "
                    "Tente resumir sua pergunta ou envie *sair* para voltar ao menu."
                ),
                provider=self.provider_name,
                used_fallback=False,
                error_message=(
                    f"Entrada excede o limite de {self.max_input_chars()} caracteres."
                ),
            )

        history = self.get_history(sender_key)
        try:
            response = self._provider.generate(
                AssistenteRequest(
                    sender_key=sender_key,
                    message=raw,
                    history=history,
                )
            )
        except Exception:
            # Falha do provider NÃO deve propagar para o webhook.
            return AssistenteResponse(
                ok=False,
                text=_FALLBACK_TEXT,
                provider=self.provider_name,
                used_fallback=True,
                error_message="Falha temporária do provider.",
            )

        if not getattr(response, "ok", False) or not str(
            getattr(response, "text", "") or ""
        ).strip():
            return AssistenteResponse(
                ok=False,
                text=_FALLBACK_TEXT,
                provider=getattr(response, "provider", self.provider_name)
                or self.provider_name,
                used_fallback=True,
                error_message="Resposta vazia ou inválida do provider.",
            )

        # Sucesso: registra turno no histórico (user + assistant) e trima.
        key = self._history_key(sender_key)
        turns = self._history.setdefault(key, [])
        turns.append(AssistenteMessage(role="user", text=raw))
        turns.append(
            AssistenteMessage(role="assistant", text=str(response.text))
        )
        self._trim_history(sender_key)

        return AssistenteResponse(
            ok=True,
            text=str(response.text),
            provider=getattr(response, "provider", self.provider_name)
            or self.provider_name,
            used_fallback=bool(getattr(response, "used_fallback", False)),
            error_message="",
        )
