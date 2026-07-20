"""Provider simulado do Assistente Inteligente Ciclus (Módulo 2A).

Este módulo NÃO:
- faz chamada externa (OpenAI, Hermes, requests, httpx);
- importa OpenAI ou Hermes;
- acessa banco de dados ou esquema;
- executa comandos de shell;
- altera código, configurações, usuários ou registros.

O provider mock apenas reproduz o comportamento do Módulo 1: devolve uma
resposta fixa e segura, sem consultar dados reais da Ciclus. A interface
aceita histórico, mas o mock não o utiliza nesta etapa.
"""

from __future__ import annotations

from dataclasses import dataclass

# NOTA: nao importamos services.assistente_inteligente_service no topo
# para evitar import circular (o servico ja importa este provider).
# A anotacao de retorno e lazy (from __future__ import annotations).


# Resposta fixa e segura do canal simulado.
_MOCK_REPLY = (
    "🤖 Recebi sua pergunta.\n\n"
    "O canal do Assistente Inteligente está funcionando. A conexão com o "
    "serviço de conversa será adicionada na próxima etapa.\n\n"
    "Para voltar ao menu, envie *sair*."
)


@dataclass(frozen=True)
class MockAssistenteProvider:
    """Provider simulado, sem qualquer dependência externa.

    Implementa a mesma assinatura esperada por AssistenteInteligenteService:
    generate(request: AssistenteRequest) -> AssistenteResponse.
    """

    # Sem timeout/config: o mock é determinístico e local.
    timeout_seconds: float = 20.0

    def generate(self, request: AssistenteRequest) -> AssistenteResponse:
        # Import local para evitar import circular com o servico
        # (que ja importa este provider no topo).
        from services.assistente_inteligente_service import AssistenteResponse

        # Não valida o texto (o serviço já validou antes de chamar).
        # Não usa o histórico nesta etapa.
        return AssistenteResponse(
            ok=True,
            text=_MOCK_REPLY,
            provider="mock",
            used_fallback=False,
            error_message="",
        )


def build_mock_provider(
    timeout_seconds: float = 20.0,
) -> MockAssistenteProvider:
    """Construtor injetável usado pelo serviço e pelos testes."""
    return MockAssistenteProvider(timeout_seconds=timeout_seconds)
