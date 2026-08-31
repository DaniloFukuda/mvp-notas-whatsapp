import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.report_catalog import (
    REPORT_DEFINITIONS,
    parse_rdv_report_command,
    report_menu_sections,
)
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


def _install_services(temp_dir):
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.visita_edit_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    collaborator = rdv.get_collaborator_by_phone("5500000000001")
    return rdv, visitas, collaborator["telefone_whatsapp"]


def test_menu_abre_com_texto_explicativo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_main_menu_interactive
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            sent = []
            api_whatsapp.send_main_menu_interactive = lambda to: sent.append(to)

            reply = api_whatsapp.handle_rdv_text_message(sender, "menu")

            assert reply is None
            assert sent == [sender]
            return

            assert "Olá! Sou o assistente da Ciclus Agro." in reply
            assert "RDV / Comprovantes" in reply
            assert "KM / Viagens" in reply
            assert "Visitas técnicas" in reply
            assert "Relatórios" in reply
            assert "* visita — inicia uma visita técnica" in reply
            assert "* visitas — lista visitas/fazendas registradas" in reply
            assert "* ver visita 12 — mostra dados da visita" in reply
            assert "* editar visita 12 — corrige dados da visita" in reply
            assert "* fechar edição — encerra modo edição" in reply
            assert "* cancelar edição — sai do modo edição" in reply
            assert "* relatório visita 12 — gera PDF pelo ID da visita" in reply
            assert "* relatório fazenda Nome da Fazenda" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_main_menu_interactive = original_sender
        api_whatsapp.whatsapp_menu_states.clear()


def test_ajuda_retorna_mesmo_menu_explicativo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_main_menu_interactive
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            sent = []
            api_whatsapp.send_main_menu_interactive = lambda to: sent.append(to)

            menu = api_whatsapp.handle_rdv_text_message(sender, "menu")
            ajuda = api_whatsapp.handle_rdv_text_message(sender, "ajuda")

            assert menu is None
            assert ajuda is None
            assert sent == [sender, sender]
            return
            assert ajuda == menu
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_main_menu_interactive = original_sender
        api_whatsapp.whatsapp_menu_states.clear()


def test_relatorios_retorna_opcoes_explicativas():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_reports_menu_interactive
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            sent = []
            api_whatsapp.send_reports_menu_interactive = lambda to: sent.append(to)

            sem_acento = api_whatsapp.handle_rdv_text_message(sender, "relatorios")
            com_acento = api_whatsapp.handle_rdv_text_message(sender, "relatórios")

            assert sem_acento is None
            assert com_acento is None
            assert sent == [sender, sender]
            return

            assert sem_acento == com_acento
            assert "Relatórios disponíveis:" in sem_acento
            assert "* resumo — resumo mensal de despesas" in sem_acento
            assert "* planilha visitas — planilha com todas as visitas/fazendas registradas" in sem_acento
            assert "* ver visita 12 — mostra dados da visita" in sem_acento
            assert "* editar visita 12 — corrige dados da visita" in sem_acento
            assert "* relatório visita 12 — gera PDF pelo ID da visita" in sem_acento
            assert "* km inicio 120350" in sem_acento
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_reports_menu_interactive = original_sender
        api_whatsapp.whatsapp_menu_states.clear()


def test_fazendas_visitadas_executa_planilha_visitas():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            assert api_whatsapp.handle_rdv_text_message(sender, "planilha visitas") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "fazendas visitadas") is None

            assert len(sent) == 2
            assert sent[0][1] == api_whatsapp.VISITAS_EXCEL_FILENAME
            assert sent[1][1] == api_whatsapp.VISITAS_EXCEL_FILENAME
            assert sent[0][2] == sent[1][2] == api_whatsapp.VISITAS_EXCEL_CAPTION
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender
        api_whatsapp.whatsapp_menu_states.clear()


def test_numero_solto_fora_de_fluxo_orienta_menu():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)

            reply = api_whatsapp.handle_rdv_text_message(sender, "1")

            assert reply == api_whatsapp.MENU_NUMBER_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_numero_solto_durante_visita_aberta_orienta_visita():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            reply = api_whatsapp.handle_rdv_text_message(sender, "2")

            assert reply == api_whatsapp.VISITA_NUMBER_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_numero_no_fluxo_rdv_categoria_continua_funcionando():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, _visitas, sender = _install_services(temp_dir)
            collaborator = rdv.get_collaborator_by_phone(sender)
            pending = rdv.register_whatsapp_expense(
                colaborador_id=collaborator["id"],
                colaborador=collaborator["nome"],
                telefone_origem=sender,
                tipo_entrada="imagem",
                valor=120,
                data_despesa="2026-06-11",
                data_detectada="2026-06-11",
                status_fluxo="aguardando_categoria",
                caminho_arquivo="comprovante.jpg",
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "1")

            assert "RDV registrado com sucesso." in reply
            assert rdv.get_expense(pending["id"])["categoria"] == "combustivel"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_cancelar_visita_cancela_visita_aberta():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            reply = api_whatsapp.handle_rdv_text_message(sender, "cancelar visita")

            assert reply == "Visita cancelada com sucesso."
            assert visitas.obter_visita_aberta(sender) is None
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_comandos_diretos_continuam_funcionando():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_weekly = api_whatsapp._send_weekly_rdv_excel
    original_monthly = api_whatsapp._send_monthly_rdv_excel
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, visitas, sender = _install_services(temp_dir)
            monthly = []
            weekly = []
            documents = []
            api_whatsapp._send_monthly_rdv_excel = lambda phone, month="": monthly.append((phone, month))
            api_whatsapp._send_weekly_rdv_excel = lambda phone, week="": weekly.append((phone, week))
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: documents.append(
                    (to, filename, caption, mime_type, content)
                )
            )
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            assert "Resumo geral do mes" in api_whatsapp.handle_rdv_text_message(sender, "resumo")
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha visitas") is None
            assert api_whatsapp.handle_rdv_text_message(
                sender,
                f"relatorio visita {visita['id']}",
            ) is None
            assert api_whatsapp.handle_rdv_text_message(
                sender,
                f"relatório visita {visita['id']}",
            ) is None
            assert "KM inicial: 120350" in api_whatsapp.handle_rdv_text_message(sender, "km inicio 120350")
            assert "Vamos iniciar uma visita técnica." in api_whatsapp.handle_rdv_text_message("5500000000002", "visita")

            assert monthly
            assert any(item[1] == api_whatsapp.VISITAS_EXCEL_FILENAME for item in documents)
            assert any(item[1] == f"relatorio_visita_{visita['id']}.pdf" for item in documents)
            assert weekly == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp._send_weekly_rdv_excel = original_weekly
        api_whatsapp._send_monthly_rdv_excel = original_monthly
        api_whatsapp.send_whatsapp_document = original_sender
        api_whatsapp.whatsapp_menu_states.clear()


def test_payload_menu_principal_interativo(monkeypatch):
    monkeypatch.setenv("ASSISTENTE_INTELIGENTE_ENABLED", "false")
    sent = []
    original_sender = api_whatsapp.send_whatsapp_list_message
    try:
        api_whatsapp.send_whatsapp_list_message = lambda **kwargs: sent.append(kwargs)

        api_whatsapp.send_main_menu_interactive("5500000000001")

        kwargs = sent[0]
    finally:
        api_whatsapp.send_whatsapp_list_message = original_sender

    payload = api_whatsapp._build_whatsapp_list_payload(
        to=kwargs["to"],
        header=kwargs["header"],
        body=kwargs["body"],
        button_text=kwargs["button_text"],
        sections=kwargs["sections"],
    )

    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "5500000000001"
    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["header"]["text"] == "🌱 Ciclus Agro"
    assert payload["interactive"]["body"]["text"] == "Escolha uma opção para continuar:"
    assert payload["interactive"]["action"]["button"] == "Abrir menu"
    rows = payload["interactive"]["action"]["sections"][0]["rows"]
    assert rows == [
        {
            "id": "menu_visit_start",
            "title": "🌱 Nova visita técnica",
            "description": "Registrar fazenda visitada",
        },
        {
            "id": "menu_audio_transcription",
            "title": "🎙️ Transcrever áudio",
            "description": "Receber a transcrição em texto",
        },
    ]


def test_menu_publico_nao_envia_instrucoes_legadas(monkeypatch):
    sent = []
    monkeypatch.setattr(
        api_whatsapp,
        "send_whatsapp_list_message",
        lambda **kwargs: sent.append(kwargs),
    )

    api_whatsapp.send_main_menu_interactive("5500000000001")

    menu = sent[0]
    visible = " ".join(
        [menu["header"], menu["body"], menu["fallback_text"]]
        + [
            " ".join(str(value) for value in row.values())
            for section in menu["sections"]
            for row in section["rows"]
        ]
    ).lower()
    assert "ciclus agro - rdv por whatsapp" not in visible
    assert "digite km" not in visible
    assert "digite resumo" not in visible
    assert "digite planilha" not in visible
    assert "comprovante" not in visible


def test_fallback_textual_desconhecido_retorna_menu_publico():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    with tempfile.TemporaryDirectory() as temp_dir:
        _, _, sender = _install_services(temp_dir)
        try:
            reply = api_whatsapp.handle_rdv_text_message(
                sender, "comando inexistente"
            )
            assert reply == api_whatsapp.MAIN_MENU_MESSAGE
            assert "Ciclus Agro - RDV por WhatsApp" not in reply
        finally:
            api_whatsapp.rdv_service = original_rdv
            api_whatsapp.visitas_service = original_visitas


def test_payload_menu_relatorios_interativo():
    sent = []
    original_sender = api_whatsapp.send_whatsapp_list_message
    try:
        api_whatsapp.send_whatsapp_list_message = lambda **kwargs: sent.append(kwargs)

        api_whatsapp.send_reports_menu_interactive("5500000000001")

        assert sent[0]["to"] == "5500000000001"
        assert sent[0]["header"] == "Relatorios"
        assert [section["title"] for section in sent[0]["sections"]] == [
            "Visitas técnicas",
        ]
        assert [row["title"] for row in sent[0]["sections"][0]["rows"]] == [
            "Listar visitas",
            "Planilha visitas",
            "PDF visita",
        ]
        assert all(
            row["title"] not in {"Resumo semanal", "Planilha semanal", "PDF semanal"}
            for section in sent[0]["sections"]
            for row in section["rows"]
        )
        rows = [
            row
            for section in sent[0]["sections"]
            for row in section["rows"]
        ]
        assert {row["id"] for row in rows} == {
            "menu_visit_list",
            "menu_visit_excel",
            "menu_visit_pdf",
        }
        assert {
            (row["title"], row["description"])
            for row in rows
        } >= {
            ("PDF visita", "Gerar PDF individual de uma visita"),
        }
    finally:
        api_whatsapp.send_whatsapp_list_message = original_sender


def test_menu_relatorios_e_ids_interativos_usam_catalogo_unico():
    report_commands = {
        report.report_id: report.aliases[0]
        for report in REPORT_DEFINITIONS
        if report.aliases and report.show_in_menu
    }
    menu_rows = [
        row
        for section in report_menu_sections()
        for row in section["rows"]
    ]

    assert {row["id"] for row in menu_rows} == set(report_commands)
    for report_id, command in report_commands.items():
        assert api_whatsapp.INTERACTIVE_COMMAND_IDS[report_id] == command


def test_aliases_de_relatorios_usam_catalogo_unico():
    for report in REPORT_DEFINITIONS:
        if report.period == "visitas":
            continue
        for alias in report.aliases:
            request = parse_rdv_report_command(alias, today=api_whatsapp.date(2026, 6, 24))
            assert request is not None
            assert request["id"] == report.report_id

    assert all(
        api_whatsapp._is_listar_visitas_command(alias)
        for report in REPORT_DEFINITIONS
        if report.handler == "visit_list"
        for alias in report.aliases
    )
    assert all(
        api_whatsapp._is_planilha_visitas_command(alias)
        for report in REPORT_DEFINITIONS
        if report.report_id == "menu_visit_excel"
        for alias in report.aliases
    )


def test_payload_botoes_confirmacao():
    payload = api_whatsapp._build_whatsapp_button_payload(
        to="5500000000001",
        body="Confirma a acao?",
        buttons=[
            {"id": "confirm_clear_km", "title": "Limpar KM"},
            {"id": "cancel_action", "title": "Cancelar"},
        ],
    )

    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "button"
    buttons = payload["interactive"]["action"]["buttons"]
    assert buttons[0]["type"] == "reply"
    assert buttons[0]["reply"] == {"id": "confirm_clear_km", "title": "Limpar KM"}
    assert buttons[1]["reply"] == {"id": "cancel_action", "title": "Cancelar"}


def test_leitura_de_interactive_button_reply():
    message = {
        "type": "interactive",
        "interactive": {
            "button_reply": {
                "id": "menu_rdv_summary",
                "title": "Resumo RDV",
            }
        },
    }

    assert api_whatsapp._extract_text(message) == "resumo"


def test_leitura_de_interactive_list_reply():
    message = {
        "type": "interactive",
        "interactive": {
            "list_reply": {
                "id": "menu_weekly_excel",
                "title": "Planilha semanal",
            }
        },
    }

    assert api_whatsapp._extract_text(message) == "planilha semanal"


def test_extrai_id_de_interactive_list_reply():
    message = {
        "type": "interactive",
        "interactive": {
            "list_reply": {
                "id": "menu_km",
                "title": "Registrar KM",
            }
        },
    }

    assert api_whatsapp._extract_interactive_reply_id(message) == "menu_km"


def test_mapeamento_menu_km_para_comando_km():
    message = {
        "type": "interactive",
        "interactive": {
            "list_reply": {
                "id": "menu_km",
                "title": "Registrar KM",
            }
        },
    }

    assert api_whatsapp._extract_text(message) == "km"


def test_lista_interativa_faz_fallback_textual_quando_meta_recusa():
    sent_texts = []
    original_post = api_whatsapp._post_whatsapp_message_payload
    original_text = api_whatsapp.send_whatsapp_text
    try:
        error = api_whatsapp.WhatsAppSendError(
            category="INVALID_PAYLOAD",
            fallback_allowed=True,
            message_kind="interactive.list",
        )
        api_whatsapp._post_whatsapp_message_payload = (
            lambda payload, recipient, message_type: (_ for _ in ()).throw(
                error
            )
        )
        api_whatsapp.send_whatsapp_text = (
            lambda to, message: sent_texts.append((to, message))
        )

        api_whatsapp.send_whatsapp_list_message(
            to="5500000000001",
            header="Header",
            body="Body",
            button_text="Abrir",
            sections=[{"title": "S", "rows": [{"id": "menu_km", "title": "KM"}]}],
            fallback_text="menu textual antigo",
        )

        assert sent_texts == [("5500000000001", "menu textual antigo")]
    finally:
        api_whatsapp._post_whatsapp_message_payload = original_post
        api_whatsapp.send_whatsapp_text = original_text


def test_ids_interativos_mapeiam_para_comandos_antigos():
    expected = {
        "menu_rdv_receipt": "rdv",
        "menu_rdv_summary": "resumo",
        "menu_rdv_excel": "planilha",
        "menu_rdv_pdf": "pdf",
        "menu_weekly_summary": "resumo semanal",
        "menu_weekly_excel": "planilha semanal",
        "menu_weekly_pdf": "pdf semanal",
        "menu_km": "km",
        "menu_visit_start": "visita",
        "menu_visit_list": "visitas",
        "menu_visit_excel": "planilha visitas",
        "menu_visit_pdf": "pdf visita",
        "menu_reports": "relatorios",
        "menu_help": "menu",
    }

    for reply_id, command in expected.items():
        assert api_whatsapp.INTERACTIVE_COMMAND_IDS[reply_id] == command


def test_interactive_list_reply_executa_comando_antigo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_send_text = api_whatsapp.send_whatsapp_text
    original_send_menu = api_whatsapp.send_main_menu_interactive
    original_message_check = api_whatsapp._was_whatsapp_message_processed
    original_image_check = api_whatsapp._was_whatsapp_image_processed_for_sender
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            sent = []
            api_whatsapp.send_main_menu_interactive = lambda to: sent.append(to)
            sent_texts = []
            api_whatsapp.send_whatsapp_text = lambda to, message: sent_texts.append((to, message))
            api_whatsapp._was_whatsapp_message_processed = lambda message_id: False
            api_whatsapp._was_whatsapp_image_processed_for_sender = lambda sha, phone: False

            api_whatsapp._handle_whatsapp_message(
                {
                    "from": sender,
                    "id": "wamid.interactive.menu",
                    "type": "interactive",
                    "interactive": {
                        "list_reply": {
                            "id": "menu_help",
                            "title": "Menu em texto",
                        }
                    },
                }
            )

            assert sent == [sender]
            assert sent_texts == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_text = original_send_text
        api_whatsapp.send_main_menu_interactive = original_send_menu
        api_whatsapp._was_whatsapp_message_processed = original_message_check
        api_whatsapp._was_whatsapp_image_processed_for_sender = original_image_check
        api_whatsapp.whatsapp_menu_states.clear()
