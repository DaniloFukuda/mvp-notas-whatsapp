import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


def _install_services(temp_dir):
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    api_whatsapp.whatsapp_menu_states.clear()
    collaborator = rdv.get_collaborator_by_phone("5500000000001")
    return rdv, visitas, collaborator["telefone_whatsapp"]


def test_menu_abre_com_texto_explicativo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)

            reply = api_whatsapp.handle_rdv_text_message(sender, "menu")

            assert "Olá! Sou o assistente da Ciclus Agro." in reply
            assert "RDV / Comprovantes" in reply
            assert "KM / Viagens" in reply
            assert "Visitas técnicas" in reply
            assert "Relatórios" in reply
            assert "* visita — inicia uma visita técnica" in reply
            assert "* visitas — lista visitas/fazendas registradas" in reply
            assert "* relatório visita 12 — gera PDF pelo ID da visita" in reply
            assert "* relatório fazenda Nome da Fazenda" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_ajuda_retorna_mesmo_menu_explicativo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)

            menu = api_whatsapp.handle_rdv_text_message(sender, "menu")
            ajuda = api_whatsapp.handle_rdv_text_message(sender, "ajuda")

            assert ajuda == menu
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_relatorios_retorna_opcoes_explicativas():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)

            sem_acento = api_whatsapp.handle_rdv_text_message(sender, "relatorios")
            com_acento = api_whatsapp.handle_rdv_text_message(sender, "relatórios")

            assert sem_acento == com_acento
            assert "Relatórios disponíveis:" in sem_acento
            assert "* resumo — resumo mensal de despesas" in sem_acento
            assert "* planilha visitas — planilha com todas as visitas/fazendas registradas" in sem_acento
            assert "* relatório visita 12 — gera PDF pelo ID da visita" in sem_acento
            assert "* km inicio 120350" in sem_acento
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
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

            assert "Confira os dados do lancamento RDV:" in reply
            reviewing = rdv.get_expense(pending["id"])
            assert reviewing["status_fluxo"] == "revisao"
            assert reviewing["categoria"] == "combustivel"

            completed_reply = api_whatsapp.handle_rdv_text_message(sender, "1")
            assert "RDV registrado com sucesso." in completed_reply
            assert rdv.get_expense(pending["id"])["status_fluxo"] == "completo"
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
            assert api_whatsapp.handle_rdv_text_message(sender, "relatorio visita") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "relatório visita") is None
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
