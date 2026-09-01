import tempfile
from pathlib import Path

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


SENDER = "5500000000001"
OTHER = "5500000000002"


def _install(temp_dir: str):
    api_whatsapp.rdv_service = RDVService(Path(temp_dir) / "rdv.db")
    api_whatsapp.visitas_service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.visita_edit_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    return api_whatsapp.visitas_service


def _visit(visitas, phone: str, farm: str, status: str = "fechada"):
    visita = visitas.iniciar_visita(phone, tecnico_nome="Técnico", fazenda=farm)
    visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")
    if status == "fechada":
        visitas.fechar_visita(visita["id"])
    elif status == "cancelada":
        visitas.cancelar_visita(visita["id"])
    return visitas.obter_visita_por_id(visita["id"])


def test_menu_publico_expoe_quatro_opcoes_sem_legados(monkeypatch):
    captured = []
    monkeypatch.setattr(api_whatsapp, "_is_assistente_inteligente_enabled", lambda: True)
    monkeypatch.setattr(
        api_whatsapp,
        "send_whatsapp_list_message",
        lambda **kwargs: captured.append(kwargs),
    )

    api_whatsapp.send_main_menu_interactive(SENDER)

    rows = captured[0]["sections"][0]["rows"]
    ids = [row["id"] for row in rows]
    assert ids == [
        "menu_visit_start",
        "menu_audio_transcription",
        "menu_assistente_inteligente",
        "menu_reports",
    ]
    menu_text = " ".join(row["title"] for row in rows).lower()
    assert "rdv" not in menu_text
    assert "km" not in menu_text
    assert "resumo" not in menu_text
    assert "planilha" not in menu_text


def test_historico_lista_so_fechadas_do_usuario_e_limita_dez(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas = _install(temp_dir)
        for index in range(12):
            _visit(visitas, SENDER, f"Fazenda {index}")
        aberta = _visit(visitas, SENDER, "Fazenda aberta", status="aberta")
        cancelada = _visit(visitas, SENDER, "Fazenda cancelada", status="cancelada")
        alheia = _visit(visitas, OTHER, "Fazenda alheia")
        captured = []
        monkeypatch.setattr(
            api_whatsapp,
            "send_whatsapp_list_message",
            lambda **kwargs: captured.append(kwargs),
        )

        api_whatsapp.send_reports_menu_interactive(SENDER)

        rows = captured[0]["sections"][0]["rows"]
        ids = [row["id"] for row in rows]
        assert len(rows) == 10
        assert f"visita_relatorio_{aberta['id']}" not in ids
        assert f"visita_relatorio_{cancelada['id']}" not in ids
        assert f"visita_relatorio_{alheia['id']}" not in ids
        assert all("Finalizada" in row["description"] for row in rows)


def test_historico_vazio_usa_mensagem_amigavel(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        _install(temp_dir)
        sent = []
        monkeypatch.setattr(api_whatsapp, "send_whatsapp_text", lambda to, text: sent.append((to, text)))

        api_whatsapp.send_reports_menu_interactive(SENDER)

        assert sent == [(SENDER, "Você ainda não possui relatórios de visitas finalizadas.")]


def test_selecao_interativa_abre_pdf_final_autorizado(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas = _install(temp_dir)
        visita = _visit(visitas, SENDER, "Fazenda autorizada")
        sent = []
        monkeypatch.setattr(
            api_whatsapp,
            "send_whatsapp_document",
            lambda to, content, filename, caption, mime_type: sent.append((to, filename, content)),
        )
        command = api_whatsapp._interactive_visit_command(
            f"visita_relatorio_{visita['id']}"
        )

        reply = api_whatsapp.handle_rdv_text_message(SENDER, command)

        assert reply is None
        assert sent[0][0] == SENDER
        assert sent[0][1] == f"relatorio_visita_{visita['id']}.pdf"
        assert sent[0][2].startswith(b"%PDF")


def test_pdf_de_outro_usuario_nao_e_exposto(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas = _install(temp_dir)
        visita = _visit(visitas, SENDER, "Fazenda privada")
        sent = []
        monkeypatch.setattr(api_whatsapp, "send_whatsapp_document", lambda *args, **kwargs: sent.append(args))

        reply = api_whatsapp.handle_rdv_text_message(
            OTHER, f"relatorio visita {visita['id']}"
        )

        assert "Não encontrei" in reply
        assert sent == []


def test_relatorio_indisponivel_usa_fallback_controlado(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas = _install(temp_dir)
        visita = _visit(visitas, SENDER, "Fazenda PDF")
        monkeypatch.setattr(
            api_whatsapp,
            "build_visita_pdf",
            lambda data: (_ for _ in ()).throw(RuntimeError("arquivo indisponível")),
        )

        reply = api_whatsapp.handle_rdv_text_message(
            SENDER, f"relatorio visita {visita['id']}"
        )

        assert "Não consegui enviar o relatório" in reply
        assert "arquivo indisponível" not in reply


def test_visita_ativa_bloqueia_relatorios_e_nova_visita_com_aviso():
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas = _install(temp_dir)
        visita = _visit(visitas, SENDER, "Fazenda atual", status="aberta")

        reports = api_whatsapp.handle_rdv_text_message(SENDER, "relatorios")
        new_visit = api_whatsapp.handle_rdv_text_message(SENDER, "nova visita")

        assert "visita em andamento" in reports.lower()
        assert "Visita em andamento" in reports
        assert "Já existe uma visita em andamento" in new_visit
        assert f"Visita #{visita['id']}" in new_visit
        assert visitas.obter_visita_aberta(SENDER)["id"] == visita["id"]


def test_orientacao_de_midias_menciona_fotos_videos_e_legenda():
    message = api_whatsapp.VISITA_OBSERVACOES_FINALIZADAS_MESSAGE
    assert "fotos e vídeos" in message
    assert "Cada arquivo pode receber uma legenda" in message
    assert "Agora você pode enviar fotos da visita" not in message
