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


def test_menu_abre_com_menu():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)

            reply = api_whatsapp.handle_rdv_text_message(sender, "menu")

            assert "Olá! Sou o assistente da Ciclus Agro." in reply
            assert "1. RDV / Comprovantes" in reply
            assert "3. Visitas técnicas" in reply
            assert "* relatório visita" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_menu_principal_opcao_1_abre_submenu_rdv():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")

            reply = api_whatsapp.handle_rdv_text_message(sender, "1")

            assert "RDV / Comprovantes:" in reply
            assert "2. Resumo mensal" in reply
            assert "5. Planilha semanal" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_submenu_rdv_opcao_2_executa_resumo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")
            api_whatsapp.handle_rdv_text_message(sender, "1")

            reply = api_whatsapp.handle_rdv_text_message(sender, "2")

            assert "Resumo geral do mes" in reply
            assert "Lancamentos: 0" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_menu_principal_opcao_3_abre_submenu_visitas():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")

            reply = api_whatsapp.handle_rdv_text_message(sender, "3")

            assert "Visitas técnicas:" in reply
            assert "1. Iniciar visita" in reply
            assert "6. Relatório da visita" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_submenu_visitas_opcao_1_inicia_visita():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")
            api_whatsapp.handle_rdv_text_message(sender, "3")

            reply = api_whatsapp.handle_rdv_text_message(sender, "1")

            assert "Vamos iniciar uma visita técnica." in reply
            assert visitas.obter_visita_aberta(sender)["estado_fluxo"] == "aguardando_fazenda"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_submenu_visitas_opcao_6_envia_relatorio_da_visita():
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
            api_whatsapp.handle_rdv_text_message(sender, "menu")
            api_whatsapp.handle_rdv_text_message(sender, "3")

            reply = api_whatsapp.handle_rdv_text_message(sender, "6")

            assert reply is None
            assert sent[0][1] == f"relatorio_visita_{visita['id']}.pdf"
            assert sent[0][2] == "Segue o relatório da visita técnica da Ciclus Agro."
            assert sent[0][3] == "application/pdf"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender
        api_whatsapp.whatsapp_menu_states.clear()


def test_voltar_retorna_ao_menu_principal():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")
            api_whatsapp.handle_rdv_text_message(sender, "3")

            reply = api_whatsapp.handle_rdv_text_message(sender, "voltar")

            assert "Olá! Sou o assistente da Ciclus Agro." in reply
            assert "4. Relatórios" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_comando_direto_km_funciona_dentro_do_menu():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")

            reply = api_whatsapp.handle_rdv_text_message(sender, "km")

            assert reply == api_whatsapp.KM_HELP_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_comando_direto_visita_funciona_dentro_do_menu():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")

            reply = api_whatsapp.handle_rdv_text_message(sender, "visita")

            assert "Vamos iniciar uma visita técnica." in reply
            assert visitas.obter_visita_aberta(sender) is not None
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()


def test_opcao_invalida_no_menu():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _rdv, _visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "menu")

            reply = api_whatsapp.handle_rdv_text_message(sender, "banana")

            assert reply == api_whatsapp.MENU_INVALID_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.whatsapp_menu_states.clear()
