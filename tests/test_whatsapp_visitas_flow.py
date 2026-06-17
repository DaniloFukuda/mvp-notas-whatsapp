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
    collaborator = rdv.get_collaborator_by_phone("5500000000001")
    return rdv, visitas, collaborator["telefone_whatsapp"]


def test_visita_iniciar_fluxo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)

            reply = api_whatsapp.handle_rdv_text_message(sender, "visita")

            assert "Vamos iniciar uma visita tecnica." in reply
            assert "Qual o nome da fazenda?" in reply
            assert visitas.obter_visita_aberta(sender)["estado_fluxo"] == "aguardando_fazenda"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_visita_preencher_campos():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)

            api_whatsapp.handle_rdv_text_message(sender, "visita")
            assert "proprietario" in api_whatsapp.handle_rdv_text_message(
                sender, "Fazenda Imperial"
            ).lower()
            api_whatsapp.handle_rdv_text_message(sender, "Alexander Duarte Paniago")
            api_whatsapp.handle_rdv_text_message(sender, "Paulo Silva")
            api_whatsapp.handle_rdv_text_message(sender, "2299 ha")
            api_whatsapp.handle_rdv_text_message(sender, "26/27")
            final = api_whatsapp.handle_rdv_text_message(
                sender, "Apresentacao de produtos ao cliente"
            )

            visita = visitas.obter_visita_aberta(sender)
            assert final.startswith("Visita aberta.")
            assert visita["estado_fluxo"] == "visita_aberta"
            assert visita["fazenda"] == "Fazenda Imperial"
            assert visita["proprietario"] == "Alexander Duarte Paniago"
            assert visita["gerente"] == "Paulo Silva"
            assert visita["area_hectares"] == 2299
            assert visita["safra"] == "26/27"
            assert visita["tipo_visita"] == "Apresentacao de produtos ao cliente"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_visita_comandos_diretos():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "visita")
            visita = visitas.obter_visita_aberta(sender)
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            api_whatsapp.handle_rdv_text_message(sender, "fazenda Fazenda Imperial")
            api_whatsapp.handle_rdv_text_message(sender, "gerente Paulo Silva")
            api_whatsapp.handle_rdv_text_message(sender, "hectares 2299")
            api_whatsapp.handle_rdv_text_message(sender, "obs Pedido de 300T")

            saved = visitas.obter_visita_aberta(sender)
            assert saved["fazenda"] == "Fazenda Imperial"
            assert saved["gerente"] == "Paulo Silva"
            assert saved["area_hectares"] == 2299
            assert "Pedido de 300T" in saved["observacoes"]
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_visita_salvar_localizacao():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender)
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            reply = api_whatsapp.handle_visitas_location_message(
                sender,
                {"latitude": -15.0019124, "longitude": -50.7714295},
            )

            saved = visitas.obter_visita_aberta(sender)
            assert "Localizacao salva." in reply
            assert "https://maps.google.com/?q=-15.0019124,-50.7714295" in reply
            assert saved["maps_url_principal"] == (
                "https://maps.google.com/?q=-15.0019124,-50.7714295"
            )
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_visita_fechar():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender)
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            reply = api_whatsapp.handle_rdv_text_message(sender, "fechar visita")

            closed = visitas.obter_visita(visita["id"])
            assert "Visita fechada com sucesso." in reply
            assert closed["status"] == "fechada"
            assert closed["fechado_em"]
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_rdv_nao_quebrou_comandos_principais():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_weekly = api_whatsapp._send_weekly_rdv_excel
    original_monthly = api_whatsapp._send_monthly_rdv_excel
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, _, sender = _install_services(temp_dir)
            monthly = []
            weekly = []
            api_whatsapp._send_monthly_rdv_excel = lambda phone, month="": monthly.append(
                (phone, month)
            )
            api_whatsapp._send_weekly_rdv_excel = lambda phone, week="": weekly.append(
                (phone, week)
            )

            assert "Resumo geral do mes" in api_whatsapp.handle_rdv_text_message(sender, "resumo")
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha") is None
            assert "Resumo geral da semana" in api_whatsapp.handle_rdv_text_message(
                sender, "resumo semanal"
            )
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha semanal") is None
            assert "Qual a cidade/local de origem?" in api_whatsapp.handle_rdv_text_message(
                sender, "km inicio 1000"
            )
            assert "Antes de finalizar" in api_whatsapp.handle_rdv_text_message(
                sender, "km termino 1200"
            )
            assert monthly
            assert weekly
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp._send_weekly_rdv_excel = original_weekly
        api_whatsapp._send_monthly_rdv_excel = original_monthly
