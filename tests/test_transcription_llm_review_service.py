from services.transcription_llm_review_service import (
    AGRO_REVIEW_INSTRUCTIONS,
    review_transcription_with_llm,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _enable(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "true")
    monkeypatch.setenv("TRANSCRIPTION_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_llm_desligado_nao_chama_api(monkeypatch):
    called = []
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "false")
    monkeypatch.setattr(
        "services.transcription_llm_review_service.requests.post",
        lambda *args, **kwargs: called.append(True),
    )

    result = review_transcription_with_llm("texto bruto")

    assert result.ok is False
    assert result.used_fallback is False
    assert called == []


def test_llm_ligado_sem_api_key_usa_fallback(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_LLM_REVIEW_ENABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = review_transcription_with_llm("texto bruto")

    assert result.ok is False
    assert result.used_fallback is True
    assert "OPENAI_API_KEY" in result.error_message


def test_llm_ligado_retorna_texto_revisado(monkeypatch):
    _enable(monkeypatch)
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _FakeResponse({"output_text": "Texto profissional revisado."})

    monkeypatch.setattr(
        "services.transcription_llm_review_service.requests.post", fake_post
    )

    result = review_transcription_with_llm("texto bruto", "visita_observacao")

    assert result.ok is True
    assert result.provider == "openai"
    assert result.output_text == "Texto profissional revisado."
    assert captured["timeout"] == 20.0
    assert "texto bruto" in captured["json"]["input"]
    assert "audio" not in captured["json"]


def test_prompt_permite_corrigir_reconhecimento_sem_inventar_informacoes():
    assert "alta confiança" in AGRO_REVIEW_INSTRUCTIONS
    assert "Não invente fatos novos" in AGRO_REVIEW_INSTRUCTIONS
    assert "Não adicione números, nomes, datas ou valores" in AGRO_REVIEW_INSTRUCTIONS
    assert "Codex, OpenAI, ChatGPT, WhatsApp, API, Python, Git" in (
        AGRO_REVIEW_INSTRUCTIONS
    )
    assert "Ciclus, OLT, contentor, aluguer, RDV e visita técnica" in (
        AGRO_REVIEW_INSTRUCTIONS
    )
    assert "Retorne somente o texto final" in AGRO_REVIEW_INSTRUCTIONS


def test_erro_da_api_usa_fallback(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        "services.transcription_llm_review_service.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
    )

    result = review_transcription_with_llm("texto bruto")

    assert result.ok is False
    assert result.used_fallback is True
    assert "TimeoutError" in result.error_message


def test_resposta_vazia_da_api_usa_fallback(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        "services.transcription_llm_review_service.requests.post",
        lambda *args, **kwargs: _FakeResponse({"output": []}),
    )

    result = review_transcription_with_llm("texto bruto")

    assert result.ok is False
    assert result.used_fallback is True
    assert "vazia" in result.error_message


def test_resposta_corrompida_da_api_usa_fallback(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        "services.transcription_llm_review_service.requests.post",
        lambda *args, **kwargs: _FakeResponse(
            {
                "output_text": (
                    "Fragen-se deixa eu? rear no eu Não aepherd ESP UP RESERRE "
                    "IP INDesd licence O chip AB ROM EU irre복 AD E ROM INESD NFP ROM ISDE."
                )
            }
        ),
    )

    result = review_transcription_with_llm("deixa eu testar esse áudio")

    assert result.ok is False
    assert result.used_fallback is True
    assert "corrompida" in result.error_message


def test_texto_acima_do_limite_nao_chama_api(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("TRANSCRIPTION_LLM_MAX_INPUT_CHARS", "10")
    called = []
    monkeypatch.setattr(
        "services.transcription_llm_review_service.requests.post",
        lambda *args, **kwargs: called.append(True),
    )

    result = review_transcription_with_llm("texto com mais de dez caracteres")

    assert result.ok is False
    assert result.used_fallback is True
    assert "limite" in result.error_message
    assert called == []
