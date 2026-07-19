"""Testes do servico isolado de resumo de visita agricola (modulo 1).

Nenhum teste realiza chamada externa de rede ou IA. O gerador de resumo e
sempre injetado (callable fake) para manter o cenario deterministico.
"""

from __future__ import annotations

import os

import pytest

from services.visita_summary_service import (
    VisitaSummary,
    VisitaSummaryResult,
    VisitaSummaryService,
    _anchors_preserved,
    _extract_anchors,
)


# ---------------------------------------------------------------------------
# Geradores fake (sem rede)
# ---------------------------------------------------------------------------

def _valid_dict_generator(prompt: str, transcription: str) -> dict:
    return {
        "assunto_principal": "Reuniao sobre plantio",
        "necessidades": "Precisa de 12 kg de fertilizante",
        "decisoes": "Aplicar na area de 5 ha",
        "pendencias": "Aguardar orcamento",
        "proximos_passos": "Visita em 12/05/2026",
    }


def _valid_object_generator(prompt: str, transcription: str) -> VisitaSummary:
    return VisitaSummary(
        assunto_principal="Reuniao sobre plantio",
        necessidades="Precisa de 12 kg de fertilizante",
        decisoes="Aplicar na area de 5 ha",
        pendencias="Aguardar orcamento",
        proximos_passos="Visita em 12/05/2026",
    )


# ---------------------------------------------------------------------------
# 1. feature flag desligada nao chama o gerador
# ---------------------------------------------------------------------------

def test_feature_flag_desligada_nao_chama_gerador(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "false")
    calls = []

    def generator(prompt, transcription):
        calls.append(transcription)
        return _valid_dict_generator(prompt, transcription)

    service = VisitaSummaryService(generator)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.used_fallback is True
    assert result.summary is None
    assert calls == []  # gerador nunca foi invocado


def test_feature_flag_ligada_chama_gerador(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is True


# ---------------------------------------------------------------------------
# 2. transcricao vazia
# ---------------------------------------------------------------------------

def test_transcricao_vazia(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate("   ")
    assert result.ok is False
    assert result.used_fallback is True
    assert result.original_transcription == "   "
    assert result.summary is None


def test_transcricao_none_nao_quebra(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate(None)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.original_transcription == ""


# ---------------------------------------------------------------------------
# 3. entrada acima do limite
# ---------------------------------------------------------------------------

def test_entrada_acima_do_limite(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("VISITA_SUMMARY_MAX_INPUT_CHARS", "10")
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert "limite" in result.reason.lower()
    assert result.summary is None


# ---------------------------------------------------------------------------
# 4. geracao valida
# ---------------------------------------------------------------------------

def test_geracao_valida_dict(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is True
    assert result.used_fallback is False
    assert isinstance(result.summary, VisitaSummary)
    assert result.summary is not None
    assert result.summary.assunto_principal == "Reuniao sobre plantio"


def test_geracao_valida_objeto(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_object_generator)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is True
    assert result.summary is not None
    assert result.summary.decisoes == "Aplicar na area de 5 ha"


# ---------------------------------------------------------------------------
# 5. estrutura retornada incompleta
# ---------------------------------------------------------------------------

def test_estrutura_incompleta(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")

    def incomplete(prompt, transcription):
        return {
            "assunto_principal": "x",
            "necessidades": "y",
            # ausentes: decisoes, pendencias, proximos_passos
        }

    service = VisitaSummaryService(incomplete)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None
    assert "secoes" in result.reason.lower()


# ---------------------------------------------------------------------------
# 6. tipos invalidos no retorno
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_output",
    [
        "texto solto",  # string, nao dict/objeto
        123,  # numero
        {"assunto_principal": 5, "necessidades": "x", "decisoes": "x", "pendencias": "x", "proximos_passos": "x"},  # tipo errado
        ["lista"],  # lista
        None,
    ],
)
def test_tipos_invalidos_no_retorno(monkeypatch, bad_output):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")

    def generator(prompt, transcription):
        return bad_output

    service = VisitaSummaryService(generator)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None
    assert result.used_fallback is True


# ---------------------------------------------------------------------------
# 7. excecao do gerador
# ---------------------------------------------------------------------------

def test_excecao_do_gerador(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")

    def boom(prompt, transcription):
        raise RuntimeError("provedor caiu")

    service = VisitaSummaryService(boom)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert result.summary is None
    assert "Falha no gerador" in result.reason
    # nao propaga
    assert isinstance(result, VisitaSummaryResult)


def test_sem_gerador_configurado(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(None)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is False
    assert "nao configurado" in result.reason.lower()


# ---------------------------------------------------------------------------
# 8. preservacao integral da transcricao original
# ---------------------------------------------------------------------------

def test_preservacao_integral_da_transcricao(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    original = "   Aplicar 12 kg em 5 ha no dia 12/05/2026   "
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate(original)
    assert result.original_transcription == original
    # fallback tambem preserva
    service_off = VisitaSummaryService(None, enabled=False)
    result_off = service_off.generate(original)
    assert result_off.original_transcription == original


# ---------------------------------------------------------------------------
# 9. preservacao de numeros
# ---------------------------------------------------------------------------

def test_preservacao_de_numeros(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Comprei 12 kg e 3 caixas de insumo"
    anchors = _extract_anchors(transcription)
    assert "12" in anchors
    assert "3" in anchors

    def generator(prompt, t):
        return {
            "assunto_principal": "Compra",
            "necessidades": "12 kg e 3 caixas",
            "decisoes": "ok",
            "pendencias": "sem",
            "proximos_passos": "depois",
        }

    service = VisitaSummaryService(generator)
    result = service.generate(transcription)
    assert result.ok is True


def test_remocao_de_numero_rejeitada(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Comprei 12 kg de insumo"

    def generator(prompt, t):
        return {
            "assunto_principal": "Compra",
            "necessidades": "kg de insumo",  # remove o 12
            "decisoes": "ok",
            "pendencias": "sem",
            "proximos_passos": "depois",
        }

    service = VisitaSummaryService(generator)
    result = service.generate(transcription)
    assert result.ok is False
    assert "ancora" in result.reason.lower()


# ---------------------------------------------------------------------------
# 10. preservacao de datas
# ---------------------------------------------------------------------------

def test_preservacao_de_datas(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Voltar no dia 12/05/2026 para revisar"
    assert _anchors_preserved(transcription, "Voltar no dia 12/05/2026 para revisar tudo")

    def generator(prompt, t):
        return {
            "assunto_principal": "Revisao",
            "necessidades": "nenhuma",
            "decisoes": "revisar em 12/05/2026",
            "pendencias": "sem",
            "proximos_passos": "voltar dia 12/05/2026",
        }

    service = VisitaSummaryService(generator)
    result = service.generate(transcription)
    assert result.ok is True


def test_alteracao_de_data_rejeitada(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Voltar no dia 12/05/2026"

    def generator(prompt, t):
        return {
            "assunto_principal": "Revisao",
            "necessidades": "nenhuma",
            "decisoes": "revisar em 13/05/2026",  # data alterada
            "pendencias": "sem",
            "proximos_passos": "voltar",
        }

    service = VisitaSummaryService(generator)
    result = service.generate(transcription)
    assert result.ok is False
    assert "ancora" in result.reason.lower()


# ---------------------------------------------------------------------------
# 11. preservacao de areas e medidas
# ---------------------------------------------------------------------------

def test_preservacao_de_areas_e_medidas(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Aplicar 5 ha e 2,5 l por talhao"

    def generator(prompt, t):
        return {
            "assunto_principal": "Aplicacao",
            "necessidades": "5 ha e 2,5 l",
            "decisoes": "fazer",
            "pendencias": "sem",
            "proximos_passos": "agendar",
        }

    service = VisitaSummaryService(generator)
    result = service.generate(transcription)
    assert result.ok is True


def test_remocao_de_area_rejeitada(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Aplicar em 5 ha de milho"

    def generator(prompt, t):
        return {
            "assunto_principal": "Aplicacao",
            "necessidades": "em ha de milho",  # remove o 5
            "decisoes": "fazer",
            "pendencias": "sem",
            "proximos_passos": "agendar",
        }

    service = VisitaSummaryService(generator)
    result = service.generate(transcription)
    assert result.ok is False
    assert "ancora" in result.reason.lower()


# ---------------------------------------------------------------------------
# 12. rejeicao quando ancora objetiva for alterada/removida
# ---------------------------------------------------------------------------

def test_alteracao_de_medida_rejeitada(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    transcription = "Dose de 10 kg por hectare"

    def generator(prompt, t):
        return {
            "assunto_principal": "Dose",
            "necessidades": "dose de 20 kg por hectare",  # altera 10 -> 20
            "decisoes": "ok",
            "pendencias": "sem",
            "proximos_passos": "depois",
        }

    service = VisitaSummaryService(generator)
    result = service.generate(transcription)
    assert result.ok is False


# ---------------------------------------------------------------------------
# 13. prompt contem todas as regras anti-invencao
# ---------------------------------------------------------------------------

def test_prompt_contem_regras_anti_invencao(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    prompt = service.build_summary_prompt("Aplicar 12 kg em 5 ha")
    assertions = [
        "somente a transcricao",
        "nao invente",
        "nao complete lacunas",
        "preserve",
        "fatos",
        "inferencias",
        "assunto principal",
        "necessidades",
        "decisoes",
        "pendencias",
        "proximos passos",
        "sem informacao",
        "instrucoes",
    ]
    lowered = prompt.lower()
    for token in assertions:
        assert token in lowered, f"regra ausente no prompt: {token}"


def test_prompt_inclui_transcricao_revisada(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    prompt = service.build_summary_prompt("Texto revisado da visita")
    assert "Texto revisado da visita" in prompt


# ---------------------------------------------------------------------------
# 14. resultado possui todas as secoes obrigatorias
# ---------------------------------------------------------------------------

def test_resultado_possui_todas_secoes(monkeypatch):
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate("Aplicar 12 kg em 5 ha no dia 12/05/2026")
    assert result.ok is True
    assert result.summary is not None
    for section in VisitaSummary.REQUIRED_SECTIONS:
        assert getattr(result.summary, section)


# ---------------------------------------------------------------------------
# 15. nenhum teste realiza chamada externa
# ---------------------------------------------------------------------------

def test_nenhum_acesso_externo(monkeypatch):
    # Garante que, mesmo com flag ligada, nao ha import de requests nem rede.
    import services.visita_summary_service as mod

    assert not hasattr(mod, "requests")
    monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
    service = VisitaSummaryService(_valid_dict_generator)
    result = service.generate("Aplicar 12 kg em 5 ha")
    assert result.ok is True


def test_flag_padrao_desligada_quando_sem_env(monkeypatch):
    monkeypatch.delenv("VISITA_SUMMARY_ENABLED", raising=False)
    service = VisitaSummaryService(_valid_dict_generator)
    assert service.is_enabled() is False
    result = service.generate("Aplicar 12 kg em 5 ha")
    assert result.ok is False
