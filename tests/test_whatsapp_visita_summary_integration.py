"""Testes de integracao do resumo de IA no fluxo de audio de visita (modulo 3B).

Sem rede: o gerador LLM e injetado como fake que devolve
LlmTextGenerationResult. O fluxo de revisao de transcricao tambem e fakeado
para isolar a etapa de resumo. Valida-se que a transcricao revisada e salva
normalmente quando a flag esta off ou o resumo falha, e que, com a flag on, o
resumo e mostrado para confirmacao antes de salvar.
"""

import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService
from services.llm_text_generation_service import LlmTextGenerationResult
from services.visita_summary_service import VisitaSummaryService
from services.visita_summary_llm_adapter import VisitaSummaryLlmAdapter

SENDER = "5500000000001"


def _install_services(temp_dir):
    original = (api_whatsapp.rdv_service, api_whatsapp.visitas_service)
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_summary_confirmation_states.clear()
    sender = rdv.get_collaborator_by_phone(SENDER)["telefone_whatsapp"]
    return original, visitas, sender


def _fake_llm(summary_text):
    """Gerador fake que devolve um resumo estruturado valido."""
    def _gen(instructions, input_text, **kwargs):
        return LlmTextGenerationResult(True, "openai", "gpt-x", summary_text)
    return _gen


def _install_summary_service(summary_text=None):
    """Troca o servico de resumo do modulo por um com gerador fake.

    Se summary_text for None, o fake devolve resposta invalida (fallback).
    """
    if summary_text is None:
        def _bad(instructions, input_text, **kwargs):
            return LlmTextGenerationResult(False, "openai", "gpt-x", "", "fail", True)
        gen = _bad
    else:
        gen = _fake_llm(summary_text)
    api_whatsapp._visita_summary_service = VisitaSummaryService(
        VisitaSummaryLlmAdapter(gen)
    )


def _setup_visit(visitas, sender, state):
    visita = visitas.iniciar_visita(sender)
    visitas.atualizar_campo(visita["id"], "estado_fluxo", state)
    return visita


def _run_audio(monkeypatch, tmp_path, sender, reviewed_text, state):
    downloaded = tmp_path / "visita.ogg"
    downloaded.write_bytes(b"audio")
    monkeypatch.setenv("WHISPER_ENABLED", "true")
    monkeypatch.setattr(
        api_whatsapp, "download_media", lambda media_id, destination: downloaded
    )
    monkeypatch.setattr(
        api_whatsapp, "_transcribe_audio_file", lambda path: reviewed_text
    )
    monkeypatch.setattr(
        api_whatsapp,
        "_review_audio_transcription_for_sender",
        lambda phone, raw: __import__(
            "services.audio_transcription_review_service", fromlist=["ReviewedTranscription"]
        ).ReviewedTranscription(raw, raw, False, []),
    )
    return api_whatsapp.handle_whatsapp_audio_message(sender, "media-visita", "audio/ogg")


# ---------------------------------------------------------------------------
# 1. flag desligada -> salva transcricao revisada normalmente
# ---------------------------------------------------------------------------

def test_flag_desligada_salva_transcricao_revisada(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        _install_summary_service("assunto_principal: x\nnecessidades: y\n"
                                 "decisoes: z\npendencias: w\nproximos_passos: k")
        visita = _setup_visit(visitas, sender, "aguardando_observacoes_gerais")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "false")
        reviewed = "Aplicar 12 kg em 5 ha no dia 12/05/2026"
        reply = _run_audio(monkeypatch, tmp_path, sender, reviewed,
                           "aguardando_observacoes_gerais")
        saved = visitas.obter_visita_aberta(sender)
        assert reviewed in (saved["observacoes_gerais"] or "")
        # Nenhum estado de confirmacao de resumo foi criado.
        assert sender not in api_whatsapp.visita_summary_confirmation_states
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original


# ---------------------------------------------------------------------------
# 2. flag ligada + resumo valido -> mostra previsualizacao e NAO salva
# ---------------------------------------------------------------------------

def test_flag_ligada_mostra_resumo_e_pausa_salvamento(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        summary = ("assunto_principal: Aplicacao\nnecessidades: 12 kg em 5 ha\n"
                   "decisoes: dia 12/05/2026\npendencias: nenhuma\nproximos_passos: retornar")
        _install_summary_service(summary)
        _setup_visit(visitas, sender, "aguardando_observacoes_gerais")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
        reviewed = "Aplicar 12 kg em 5 ha no dia 12/05/2026"
        reply = _run_audio(monkeypatch, tmp_path, sender, reviewed,
                           "aguardando_observacoes_gerais")
        # Previa exibida.
        assert "Resumo sugerido" in reply
        assert "Assunto principal: Aplicacao" in reply
        # Nao salvou ainda.
        saved = visitas.obter_visita_aberta(sender)
        assert not (saved["observacoes_gerais"] or "").strip()
        # Estado de confirmacao criado.
        assert sender in api_whatsapp.visita_summary_confirmation_states
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original


# ---------------------------------------------------------------------------
# 3. escolhas do usuario
# ---------------------------------------------------------------------------

def test_escolha_usar_resumo_salva_resumo(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        summary = ("assunto_principal: Aplicacao\nnecessidades: 12 kg em 5 ha\n"
                   "decisoes: dia 12/05/2026\npendencias: nenhuma\nproximos_passos: retornar")
        _install_summary_service(summary)
        _setup_visit(visitas, sender, "aguardando_observacoes_gerais")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
        reviewed = "Aplicar 12 kg em 5 ha no dia 12/05/2026"
        _run_audio(monkeypatch, tmp_path, sender, reviewed,
                   "aguardando_observacoes_gerais")
        # Usuario escolhe "1 - usar resumo".
        reply = api_whatsapp.handle_rdv_text_message(sender, "1")
        saved = visitas.obter_visita_aberta(sender)
        assert "Aplicacao" in (saved["observacoes_gerais"] or "")
        assert "12 kg em 5 ha" in (saved["observacoes_gerais"] or "")
        assert sender not in api_whatsapp.visita_summary_confirmation_states
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original


def test_escolha_usar_transcricao_salva_revisada(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        summary = ("assunto_principal: Aplicacao\nnecessidades: 12 kg em 5 ha\n"
                   "decisoes: dia 12/05/2026\npendencias: nenhuma\nproximos_passos: retornar")
        _install_summary_service(summary)
        _setup_visit(visitas, sender, "aguardando_observacoes_gerais")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
        reviewed = "Aplicar 12 kg em 5 ha no dia 12/05/2026"
        _run_audio(monkeypatch, tmp_path, sender, reviewed,
                   "aguardando_observacoes_gerais")
        reply = api_whatsapp.handle_rdv_text_message(sender, "2")
        saved = visitas.obter_visita_aberta(sender)
        assert reviewed in (saved["observacoes_gerais"] or "")
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original


def test_escolha_reenviar_limpa_estado(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        summary = ("assunto_principal: Aplicacao\nnecessidades: 12 kg em 5 ha\n"
                   "decisoes: dia 12/05/2026\npendencias: nenhuma\nproximos_passos: retornar")
        _install_summary_service(summary)
        _setup_visit(visitas, sender, "aguardando_observacoes_gerais")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
        reviewed = "Aplicar 12 kg em 5 ha no dia 12/05/2026"
        _run_audio(monkeypatch, tmp_path, sender, reviewed,
                   "aguardando_observacoes_gerais")
        reply = api_whatsapp.handle_rdv_text_message(sender, "3")
        assert sender not in api_whatsapp.visita_summary_confirmation_states
        assert "reenviar" in reply.lower() or "digitar" in reply.lower()
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original


# ---------------------------------------------------------------------------
# 4. falha do resumo -> fallback salva transcricao revisada
# ---------------------------------------------------------------------------

def test_falha_resumo_fallback_salva_revisada(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        _install_summary_service(None)  # gerador fake invalido
        _setup_visit(visitas, sender, "aguardando_observacoes_gerais")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
        reviewed = "Aplicar 12 kg em 5 ha no dia 12/05/2026"
        reply = _run_audio(monkeypatch, tmp_path, sender, reviewed,
                           "aguardando_observacoes_gerais")
        saved = visitas.obter_visita_aberta(sender)
        assert reviewed in (saved["observacoes_gerais"] or "")
        assert sender not in api_whatsapp.visita_summary_confirmation_states
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original


# ---------------------------------------------------------------------------
# 5. nao afeta RDV nem transcricao avulsa
# ---------------------------------------------------------------------------

def test_resumo_nao_afeta_transcricao_avulsa(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        _install_summary_service("assunto_principal: x\nnecessidades: y\n"
                                 "decisoes: z\npendencias: w\nproximos_passos: k")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
        downloaded = tmp_path / "standalone.ogg"
        downloaded.write_bytes(b"audio")
        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )
        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_file", lambda path: "usar o cadax"
        )
        api_whatsapp.whatsapp_menu_states[
            sender
        ] = api_whatsapp.STANDALONE_TRANSCRIPTION_STATE
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-standalone", "audio/ogg"
        )
        # Fluxo avulso intacto; nenhum estado de resumo de visita.
        assert "Transcrição revisada" in reply
        assert sender not in api_whatsapp.visita_summary_confirmation_states
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original


def test_resumo_nao_afeta_comentario_rdv(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        original, visitas, sender = _install_services(temp_dir)
        _install_summary_service("assunto_principal: x\nnecessidades: y\n"
                                 "decisoes: z\npendencias: w\nproximos_passos: k")
        monkeypatch.setenv("VISITA_SUMMARY_ENABLED", "true")
        # Estado de comentario RDV ativo (sem visita aberta no estado de audio).
        api_whatsapp._start_rdv_comment_state(sender, 1)
        downloaded = tmp_path / "rdv.ogg"
        downloaded.write_bytes(b"audio")
        monkeypatch.setattr(
            api_whatsapp, "download_media", lambda media_id, destination: downloaded
        )
        monkeypatch.setattr(
            api_whatsapp, "_transcribe_audio_file", lambda path: "comentario de despesa"
        )
        monkeypatch.setattr(
            api_whatsapp,
            "_review_transcription_in_revisada_mode",
            lambda raw, **kw: __import__(
                "services.audio_transcription_review_service",
                fromlist=["ReviewedTranscription"],
            ).ReviewedTranscription(raw, raw, False, []),
        )
        reply = api_whatsapp.handle_whatsapp_audio_message(
            sender, "media-rdv", "audio/ogg"
        )
        assert sender not in api_whatsapp.visita_summary_confirmation_states
        api_whatsapp.rdv_comment_states.clear()
        api_whatsapp.rdv_service, api_whatsapp.visitas_service = original
