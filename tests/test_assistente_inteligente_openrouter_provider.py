"""Testes do provider OpenRouter do Assistente Inteligente (Modulo 2C).

Todos os cenarios usam uma funcao HTTP fake injetada via build_openrouter_provider(
generator=...). NENHUMA chamada real a OpenRouter/rede ocorre.

Cobre:
1. resposta valida;
2. modelo configurado e enviado;
3. endpoint correto e utilizado;
4. Bearer token e montado internamente;
5. chave nunca aparece na resposta;
6. prompt contem regras de somente leitura;
7. historico curto e enviado na ordem correta;
8. sender_key nao entra no payload;
9. nenhuma ferramenta/function calling entra no payload;
10. timeout e repassado;
11. limite de saida e aplicado;
12. chave ausente retorna fallback seguro sem rede;
13. timeout retorna fallback seguro;
14. excecao de conexao retorna fallback seguro;
15. HTTP 400 retorna fallback seguro;
16. HTTP 401 retorna fallback seguro;
17. HTTP 429 retorna fallback seguro;
18. HTTP 500 retorna fallback seguro;
19. JSON invalido retorna fallback seguro;
20. choices ausente retorna fallback seguro;
21. content vazio retorna fallback seguro;
22. erro bruto, endpoint, chave e stack trace nao aparecem para o usuario;
23. provider informado no envelope e openrouter;
24. used_fallback correto;
25. mock permanece padrao quando configuracao ausente;
26. openrouter so e selecionado explicitamente;
27. configuracao invalida continua usando _InvalidConfigProvider;
28. falha do openrouter nunca chama mock;
29. spy em requests.post confirma zero rede real;
30. resposta continua sendo somente texto e nunca e executada.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

from services.assistente_inteligente_openrouter_provider import (  # noqa: E402
    AssistenteInteligenteOpenRouterProvider,
    OPENROUTER_URL,
    build_openrouter_provider,
)
from services.assistente_inteligente_service import (  # noqa: E402
    AssistenteInteligenteService,
    AssistenteMessage,
    AssistenteRequest,
    AssistenteResponse,
)
from services.assistente_inteligente_provider import (  # noqa: E402
    MockAssistenteProvider,
    build_mock_provider,
)

DEFAULT_MODEL = "tencent/hy3:free"


# ---------------------------------------------------------------------------
# Response fake estilo requests.Response
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, raise_exc=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        if self.status_code >= 400:
            from requests.exceptions import HTTPError

            raise HTTPError(f"status {self.status_code}")

    def json(self):
        if self._json is _SENTINEL_INVALID:
            raise ValueError("JSON invalido")
        return self._json


_SENTINEL_INVALID = object()


def _content(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


# ---------------------------------------------------------------------------
# HTTP generator fake que registra a chamada
# ---------------------------------------------------------------------------

class _HttpFake:
    def __init__(
        self,
        response=None,
        raise_exc=None,
        capture=None,
        model_seen=None,
        timeout_seen=None,
    ):
        self._response = response
        self._raise_exc = raise_exc
        self._capture = capture if capture is not None else {}
        self._model_seen = model_seen
        self._timeout_seen = timeout_seen

    def __call__(self, url, *, headers=None, json=None, timeout=None):
        self._capture["url"] = url
        self._capture["headers"] = headers
        self._capture["json"] = json
        self._capture["timeout"] = timeout
        if self._model_seen is not None and json:
            self._model_seen.append(json.get("model"))
        if self._timeout_seen is not None and timeout is not None:
            self._timeout_seen.append(timeout)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


# ---------------------------------------------------------------------------
# 1) resposta valida
# ---------------------------------------------------------------------------

def test_resposta_valida(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    resp_fake = _FakeResponse(200, _content("Ola, sou consultivo."))
    provider = build_openrouter_provider(
        generator=_HttpFake(response=resp_fake),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is True
    assert resp.text == "Ola, sou consultivo."
    assert resp.provider == "openrouter"
    assert resp.used_fallback is False


# ---------------------------------------------------------------------------
# 2) modelo configurado e enviado
# ---------------------------------------------------------------------------

def test_modelo_configurado_enviado(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen = []
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("x")),
                             model_seen=seen),
        model="tencent/hy3:free",
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert seen == ["tencent/hy3:free"]


# ---------------------------------------------------------------------------
# 3) endpoint correto e utilizado
# ---------------------------------------------------------------------------

def test_endpoint_correto(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    capture = {}
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("x")),
                             capture=capture),
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert capture["url"] == OPENROUTER_URL


# ---------------------------------------------------------------------------
# 4) Bearer token e montado internamente
# ---------------------------------------------------------------------------

def test_bearer_token_montado(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    capture = {}
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("x")),
                             capture=capture),
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert capture["headers"]["Authorization"] == "Bearer sk-or-fake"
    assert capture["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# 5) chave nunca aparece na resposta
# ---------------------------------------------------------------------------

def test_chave_nao_aparece_na_resposta(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("ok"))),
        api_key="sk-or-super-secreto",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert "sk-or-super-secreto" not in resp.text
    assert "sk-or-super-secreto" not in resp.error_message


# ---------------------------------------------------------------------------
# 6) prompt contem regras de somente leitura
# ---------------------------------------------------------------------------

def test_prompt_contem_regras_somente_leitura(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    capture = {}
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("x")),
                             capture=capture),
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    messages = capture["json"]["messages"]
    system = messages[0]
    assert system["role"] == "system"
    instr = system["content"].lower()
    assert "assistente inteligente ciclus" in instr
    assert "exclusivamente consultivo" in instr
    assert "nao crie" in instr
    assert "nao execute comandos" in instr
    assert "hermes" not in instr  # nome interno nao vai ao usuario


# ---------------------------------------------------------------------------
# 7) historico curto e enviado na ordem correta
# ---------------------------------------------------------------------------

def test_historico_curto_enviado_ordem(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    capture = {}
    history = [
        AssistenteMessage(role="user", text="Quem e a Ciclus?"),
        AssistenteMessage(role="assistant", text="Empresa agricola."),
    ]
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("ok")),
                             capture=capture),
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(
            sender_key="5500000000001",
            message="E o RDV?",
            history=history,
        )
    )
    messages = capture["json"]["messages"]
    roles = [m["role"] for m in messages]
    # system + historico(user, assistant) + user atual
    assert roles == ["system", "user", "assistant", "user"]
    contents = [m["content"] for m in messages]
    assert "Quem e a Ciclus?" in contents
    assert "Empresa agricola." in contents
    assert "E o RDV?" in contents


# ---------------------------------------------------------------------------
# 8) sender_key nao entra no payload
# ---------------------------------------------------------------------------

def test_sender_key_nao_entra_no_payload(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    capture = {}
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("x")),
                             capture=capture),
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    dumped = str(capture["json"])
    assert "5500000000001" not in dumped


# ---------------------------------------------------------------------------
# 9) nenhuma ferramenta/function calling entra no payload
# ---------------------------------------------------------------------------

def test_sem_tools_functions_no_payload(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    capture = {}
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("x")),
                             capture=capture),
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    payload = capture["json"]
    assert "tools" not in payload
    assert "functions" not in payload
    assert "tool_choice" not in payload
    assert "function_call" not in payload
    assert "response_format" not in payload


# ---------------------------------------------------------------------------
# 10) timeout e repassado
# ---------------------------------------------------------------------------

def test_timeout_repassado(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen = []
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("x")),
                             timeout_seen=seen),
        timeout_seconds=7.0,
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert seen == [7.0]


# ---------------------------------------------------------------------------
# 11) limite de saida e aplicado
# ---------------------------------------------------------------------------

def test_limite_saida_aplicado(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    long_text = "x" * 5000
    provider = build_openrouter_provider(
        generator=_HttpFake(
            response=_FakeResponse(200, _content(long_text))
        ),
        max_output_chars=2000,
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is True
    assert len(resp.text) <= 2000 + len("\n[resposta truncada]")
    assert "truncada" in resp.text


# ---------------------------------------------------------------------------
# 12) chave ausente retorna fallback seguro sem rede
# ---------------------------------------------------------------------------

def test_chave_ausente_fallback_sem_rede(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    net = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: net.append(True))
    # sem api_key injetado nem env -> chave ausente
    provider = build_openrouter_provider()
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert resp.provider == "openrouter"
    assert net == []  # nenhuma rede real


# ---------------------------------------------------------------------------
# 13) timeout retorna fallback seguro
# ---------------------------------------------------------------------------

def test_timeout_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from requests.exceptions import Timeout

    provider = build_openrouter_provider(
        generator=_HttpFake(raise_exc=Timeout("tempo-esgotado-xyz")),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert "esgotado-xyz" not in resp.error_message
    assert "Timeout" not in resp.error_message


# ---------------------------------------------------------------------------
# 14) excecao de conexao retorna fallback seguro
# ---------------------------------------------------------------------------

def test_excecao_conexao_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from requests.exceptions import ConnectionError as ConnError

    provider = build_openrouter_provider(
        generator=_HttpFake(raise_exc=ConnError("falha de rede")),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert "falha de rede" not in resp.error_message
    assert "ConnectionError" not in resp.error_message


# ---------------------------------------------------------------------------
# 15-18) HTTP 4xx/5xx retornam fallback seguro
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_http_erros_fallback(status, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(status_code=status,
                                                    json_data={})),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert resp.provider == "openrouter"
    assert str(status) not in resp.error_message


# ---------------------------------------------------------------------------
# 19) JSON invalido retorna fallback seguro
# ---------------------------------------------------------------------------

def test_json_invalido_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _SENTINEL_INVALID)),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True


# ---------------------------------------------------------------------------
# 20) choices ausente retorna fallback seguro
# ---------------------------------------------------------------------------

def test_choices_ausente_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, {"id": "x"})),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True


# ---------------------------------------------------------------------------
# 21) content vazio retorna fallback seguro
# ---------------------------------------------------------------------------

def test_content_vazio_fallback(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("   "))),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True


# ---------------------------------------------------------------------------
# 22) erro bruto, endpoint, chave e stack trace nao aparecem para o usuario
# ---------------------------------------------------------------------------

def test_sem_vazamento_interno(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from requests.exceptions import HTTPError

    provider = build_openrouter_provider(
        generator=_HttpFake(
            response=_FakeResponse(
                status_code=401,
                json_data={"error": {"message": "secret-token-leak"}},
            )
        ),
        api_key="sk-or-super-secreto",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    blob = (resp.text + resp.error_message).lower()
    assert "secret-token-leak" not in blob
    assert "sk-or-super-secreto" not in blob
    assert "openrouter.ai" not in blob
    assert "openrouter" not in blob
    assert "hy3" not in blob
    assert "traceback" not in blob
    assert "401" not in blob


# ---------------------------------------------------------------------------
# 23) provider informado no envelope e openrouter
# ---------------------------------------------------------------------------

def test_provider_no_envelope_e_openrouter(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("ok"))),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.provider == "openrouter"


# ---------------------------------------------------------------------------
# 24) used_fallback correto
# ---------------------------------------------------------------------------

def test_used_fallback_correto(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # sucesso
    ok_provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("ok"))),
        api_key="sk-or-fake",
    )
    r_ok = ok_provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert r_ok.used_fallback is False
    # falha
    fail_provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(500, {})),
        api_key="sk-or-fake",
    )
    r_fail = fail_provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert r_fail.used_fallback is True


# ---------------------------------------------------------------------------
# 25) mock permanece padrao quando configuracao ausente
# ---------------------------------------------------------------------------

def test_mock_padrao_quando_config_ausente(monkeypatch):
    monkeypatch.delenv("ASSISTENTE_INTELIGENTE_PROVIDER", raising=False)
    service = AssistenteInteligenteService()
    assert isinstance(service._provider, MockAssistenteProvider)


# ---------------------------------------------------------------------------
# 26) openrouter so e selecionado explicitamente
# ---------------------------------------------------------------------------

def test_openrouter_somente_quando_explicito(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    service = AssistenteInteligenteService()
    assert isinstance(
        service._provider, AssistenteInteligenteOpenRouterProvider
    )


# ---------------------------------------------------------------------------
# 27) configuracao invalida continua usando _InvalidConfigProvider
# ---------------------------------------------------------------------------

def test_provider_invalido_usa_invalid_config(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_PROVIDER", "anthropic")
    service = AssistenteInteligenteService()
    # Nunca deve cair no mock como falsa resposta real.
    assert not isinstance(service._provider, MockAssistenteProvider)
    resp = service.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    # Nao finge ser resposta real do assistente.
    assert "Recebi sua pergunta" not in resp.text


# ---------------------------------------------------------------------------
# 28) falha do openrouter nunca chama mock
# ---------------------------------------------------------------------------

def test_falha_openrouter_nunca_chama_mock(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    service = AssistenteInteligenteService()
    # Forca o provider openrouter a falhar (HTTP 500) sem rede real.
    service._provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(500, {})),
        api_key="sk-or-fake",
    )
    resp = service.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert resp.ok is False
    assert resp.used_fallback is True
    assert resp.provider == "openrouter"
    # Nao e o texto do mock.
    assert "Recebi sua pergunta" not in resp.text


# ---------------------------------------------------------------------------
# 29) spy em requests.post confirma zero rede real
# ---------------------------------------------------------------------------

def test_nenhuma_rede_real(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    net = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: net.append(True))
    provider = build_openrouter_provider(
        generator=_HttpFake(response=_FakeResponse(200, _content("ok"))),
        api_key="sk-or-fake",
    )
    provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert net == []  # generator injetado substitui requests.post


# ---------------------------------------------------------------------------
# 30) resposta continua sendo somente texto e nunca e executada
# ---------------------------------------------------------------------------

def test_resposta_apenas_texto_nunca_comando(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = build_openrouter_provider(
        generator=_HttpFake(
            response=_FakeResponse(200, _content("A resposta e apenas texto."))
        ),
        api_key="sk-or-fake",
    )
    resp = provider.generate(
        AssistenteRequest(sender_key="5500000000001", message="Oi")
    )
    assert isinstance(resp.text, str)
    assert resp.text == "A resposta e apenas texto."
