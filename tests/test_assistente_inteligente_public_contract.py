"""Contrato publico do Assistente; todos os providers deste arquivo sao fakes."""

from services.assistente_inteligente_service import (
    AssistenteInteligenteService,
    AssistenteRequest,
    AssistenteResponse,
)
import api_whatsapp


class _FakeProvider:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return AssistenteResponse(
            ok=True,
            text=self.text,
            provider="fake",
            used_fallback=False,
            error_message="",
        )


def test_mensagem_normal_chega_ao_provider_e_resposta_real_volta():
    provider = _FakeProvider(
        "Posso ajudar com dúvidas gerais de agronomia e rotina de campo."
    )
    service = AssistenteInteligenteService(provider=provider)

    response = service.generate(
        AssistenteRequest(
            sender_key="5500000000001",
            message="O que você é capaz de fazer?",
        )
    )

    assert [call.message for call in provider.calls] == [
        "O que você é capaz de fazer?"
    ]
    assert response.text == provider.text


def test_safety_input_e_output_sao_metadados_e_nao_chegam_ao_usuario():
    provider = _FakeProvider(
        "User Safety: safe\n"
        "Posso explicar princípios gerais de manejo integrado de pragas.\n"
        "Response Safety: safe"
    )
    service = AssistenteInteligenteService(provider=provider)

    response = service.generate(
        AssistenteRequest(sender_key="5500000000001", message="Fale de MIP")
    )

    assert response.ok is True
    assert response.text == (
        "Posso explicar princípios gerais de manejo integrado de pragas."
    )
    assert "User Safety" not in response.text
    assert "Response Safety" not in response.text
    assert service.get_history("5500000000001")[-1].text == response.text


def test_resposta_composta_somente_de_safety_nao_e_publicada():
    provider = _FakeProvider("User Safety: safe\nResponse Safety: safe")
    service = AssistenteInteligenteService(provider=provider)

    response = service.generate(
        AssistenteRequest(sender_key="5500000000001", message="Olá")
    )

    assert response.ok is False
    assert response.used_fallback is True
    assert "indisponível" in response.text
    assert "Safety" not in response.text
    assert service.get_history("5500000000001") == []


def test_mensagem_de_entrada_nao_anuncia_modo_de_teste():
    assert "Modo de teste ativado" not in api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE
    assert "Como posso ajudar" in api_whatsapp.ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE
