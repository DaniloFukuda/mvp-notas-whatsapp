import sys
import tempfile
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook


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

            assert "Vamos iniciar uma visita técnica." in reply
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
            assert "proprietário" in api_whatsapp.handle_rdv_text_message(
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
            assert "📍 Localização salva." in reply
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
            assert "Área: - ha" in reply
            assert "Localizações: 0" in reply
            assert "Comandos disponíveis:" in reply
            assert "relatório visita" in reply
            assert "localização visita" in reply
            assert closed["status"] == "fechada"
            assert closed["fechado_em"]
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_relatorio_visita_envia_pdf():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.atualizar_campo(visita["id"], "gerente", "Paulo Silva")
            visitas.adicionar_observacao(visita["id"], "Pedido de 300T")
            sent = []

            def fake_send(to, content, filename, caption, mime_type):
                sent.append(
                    {
                        "to": to,
                        "content": content,
                        "filename": filename,
                        "caption": caption,
                        "mime_type": mime_type,
                    }
                )

            api_whatsapp.send_whatsapp_document = fake_send

            reply = api_whatsapp.handle_rdv_text_message(sender, "relatorio visita")

            assert reply is None
            assert len(sent) == 1
            assert sent[0]["to"] == sender
            assert sent[0]["content"].startswith(b"%PDF")
            assert sent[0]["filename"] == f"relatorio_visita_{visita['id']}.pdf"
            assert sent[0]["caption"] == (
                "Segue o relatório da visita técnica da Ciclus Agro."
            )
            assert sent[0]["mime_type"] == "application/pdf"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_relatorio_visita_sem_visita():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, _, sender = _install_services(temp_dir)

            reply = api_whatsapp.handle_rdv_text_message(sender, "relatorio visita")

            assert reply == api_whatsapp.NO_VALID_VISITA_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_relatorio_visita_por_id_de_outro_telefone():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services(temp_dir)
            other = rdv.get_collaborator_by_phone("5500000000002")["telefone_whatsapp"]
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(
                other,
                f"relatorio visita {visita['id']}",
            )

            assert reply is None
            assert len(sent) == 1
            assert sent[0][0] == other
            assert sent[0][1] == f"relatorio_visita_{visita['id']}.pdf"
            assert sent[0][4].startswith(b"%PDF")
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_relatorio_visita_sem_id_com_multiplas_visitas_lista_opcoes():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services(temp_dir)
            other = rdv.get_collaborator_by_phone("5500000000002")["telefone_whatsapp"]
            primeira = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(primeira["id"], "fazenda", "Fazenda Imperial")
            segunda = visitas.iniciar_visita(other, tecnico_nome="Marcelo")
            visitas.atualizar_campo(segunda["id"], "fazenda", "Fazenda Boi Dourado 3J")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "relatorio visita")

            assert "Escolha uma pelo ID" in reply
            assert f"#{primeira['id']} - Fazenda Imperial" in reply
            assert f"#{segunda['id']} - Fazenda Boi Dourado 3J" in reply
            assert sent == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_relatorio_fazenda_um_resultado():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita("5500000000002", tecnico_nome="Marcelo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(
                sender,
                "relatorio fazenda Fazenda Imperial",
            )

            assert reply is None
            assert len(sent) == 1
            assert sent[0][1] == f"relatorio_visita_{visita['id']}.pdf"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_relatorio_fazenda_multiplos_resultados():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services(temp_dir)
            other = rdv.get_collaborator_by_phone("5500000000002")["telefone_whatsapp"]
            primeira = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(primeira["id"], "fazenda", "Fazenda Imperial")
            segunda = visitas.iniciar_visita(other, tecnico_nome="Marcelo")
            visitas.atualizar_campo(segunda["id"], "fazenda", "Fazenda Imperial Norte")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(
                sender,
                "relatorio fazenda Fazenda Imperial",
            )

            assert "Encontrei mais de uma visita" in reply
            assert f"#{primeira['id']} - Fazenda Imperial" in reply
            assert f"#{segunda['id']} - Fazenda Imperial Norte" in reply
            assert sent == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_relatorio_visita_nao_gera_pdf_de_cancelada():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Cancelada")
            visitas.cancelar_visita(visita["id"])
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "relatório visita")

            assert reply == api_whatsapp.NO_VALID_VISITA_MESSAGE
            assert sent == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_relatorio_visita_id_cancelado_bloqueia():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Cancelada")
            visitas.cancelar_visita(visita["id"])
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(
                sender,
                f"relatório visita {visita['id']}",
            )

            assert reply == api_whatsapp.CANCELED_VISITA_REPORT_MESSAGE
            assert sent == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_fazendas_visitadas_exclui_canceladas():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            cancelada = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(cancelada["id"], "data_visita", "2026-06-17")
            visitas.atualizar_campo(cancelada["id"], "fazenda", "Fazenda Cancelada")
            visitas.cancelar_visita(cancelada["id"])
            fechada = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(fechada["id"], "data_visita", "2026-06-17")
            visitas.atualizar_campo(fechada["id"], "fazenda", "Fazenda Valida")
            visitas.fechar_visita(fechada["id"])
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "fazendas visitadas")

            assert reply is None
            workbook = load_workbook(BytesIO(sent[0][4]))
            visitas_sheet = workbook["Visitas"]
            fazendas = [
                row[0]
                for row in visitas_sheet.iter_rows(
                    min_row=2,
                    min_col=5,
                    max_col=5,
                    values_only=True,
                )
            ]
            assert "Fazenda Valida" in fazendas
            assert "Fazenda Cancelada" not in fazendas
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_planilha_visitas_global():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            primeira = visitas.iniciar_visita("5500000000001", tecnico_nome="Danilo")
            visitas.atualizar_campo(primeira["id"], "data_visita", "2026-05-10")
            visitas.atualizar_campo(primeira["id"], "fazenda", "Fazenda Imperial")
            segunda = visitas.iniciar_visita("5500000000002", tecnico_nome="Marcelo")
            visitas.atualizar_campo(segunda["id"], "data_visita", "2026-06-17")
            visitas.atualizar_campo(segunda["id"], "fazenda", "Fazenda Boi Dourado 3J")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "planilha visitas")

            assert reply is None
            workbook = load_workbook(BytesIO(sent[0][4]))
            sheet = workbook["Visitas"]
            fazendas = [
                row[0]
                for row in sheet.iter_rows(
                    min_row=2,
                    min_col=5,
                    max_col=5,
                    values_only=True,
                )
            ]
            assert "Fazenda Imperial" in fazendas
            assert "Fazenda Boi Dourado 3J" in fazendas
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_fazendas_visitadas_global():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            primeira = visitas.iniciar_visita("5500000000001", tecnico_nome="Danilo")
            visitas.atualizar_campo(primeira["id"], "data_visita", "2026-05-10")
            visitas.atualizar_campo(primeira["id"], "fazenda", "Fazenda Imperial")
            segunda = visitas.iniciar_visita("5500000000002", tecnico_nome="Marcelo")
            visitas.atualizar_campo(segunda["id"], "data_visita", "2026-06-17")
            visitas.atualizar_campo(segunda["id"], "fazenda", "Fazenda Boi Dourado 3J")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "fazendas visitadas")

            assert reply is None
            workbook = load_workbook(BytesIO(sent[0][4]))
            sheet = workbook["Visitas"]
            fazendas = [
                row[0]
                for row in sheet.iter_rows(
                    min_row=2,
                    min_col=5,
                    max_col=5,
                    values_only=True,
                )
            ]
            assert "Fazenda Imperial" in fazendas
            assert "Fazenda Boi Dourado 3J" in fazendas
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_localizacao_visita_por_id():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, _sender = _install_services(temp_dir)
            other = rdv.get_collaborator_by_phone("5500000000002")["telefone_whatsapp"]
            visita = visitas.iniciar_visita("5500000000001", tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.adicionar_localizacao(visita["id"], -15.0019124, -50.7714295)

            reply = api_whatsapp.handle_rdv_text_message(
                other,
                f"localizacao visita {visita['id']}",
            )

            assert "Fazenda Imperial" in reply
            assert "https://maps.google.com/?q=-15.0019124,-50.7714295" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_visita_status_continua_por_telefone():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services(temp_dir)
            other = rdv.get_collaborator_by_phone("5500000000002")["telefone_whatsapp"]
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            reply = api_whatsapp.handle_rdv_text_message(other, "visita status")

            assert reply == api_whatsapp.NO_OPEN_VISITA_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_canceladas_nao_aparecem():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            cancelada = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(cancelada["id"], "fazenda", "Fazenda Cancelada")
            visitas.cancelar_visita(cancelada["id"])
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            list_reply = api_whatsapp.handle_rdv_text_message(sender, "visitas")
            planilha_reply = api_whatsapp.handle_rdv_text_message(sender, "planilha visitas")
            relatorio_reply = api_whatsapp.handle_rdv_text_message(sender, "relatorio visita")
            fazenda_reply = api_whatsapp.handle_rdv_text_message(
                sender,
                "relatorio fazenda Fazenda Cancelada",
            )

            assert list_reply == api_whatsapp.NO_VALID_VISITA_MESSAGE
            assert planilha_reply is None
            assert relatorio_reply == api_whatsapp.NO_VALID_VISITA_MESSAGE
            assert "Não encontrei visita técnica válida" in fazenda_reply
            workbook = load_workbook(BytesIO(sent[0][4]))
            assert workbook["Visitas"].max_row == 1
            assert len(sent) == 1
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


def test_localizacao_visita_ignora_cancelada():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")
            visitas.adicionar_localizacao(visita["id"], -15.0019124, -50.7714295)
            visitas.cancelar_visita(visita["id"])

            reply = api_whatsapp.handle_rdv_text_message(sender, "localização visita")

            assert reply == api_whatsapp.NO_VALID_VISITA_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_visita_status_apos_cancelar():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, _visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "visita")
            cancel_reply = api_whatsapp.handle_rdv_text_message(sender, "cancelar visita")

            status_reply = api_whatsapp.handle_rdv_text_message(sender, "visita status")

            assert cancel_reply == "Visita cancelada com sucesso."
            assert status_reply == api_whatsapp.NO_OPEN_VISITA_MESSAGE
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_comandos_visita_aceitam_acentos_e_sem_acentos():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")
            visitas.adicionar_localizacao(visita["id"], -15.0019124, -50.7714295)
            sent = []

            def fake_send(to, content, filename, caption, mime_type):
                sent.append((to, filename, caption, mime_type, content))

            api_whatsapp.send_whatsapp_document = fake_send

            assert api_whatsapp.handle_rdv_text_message(
                sender, "localizacao visita"
            ).startswith("Fazenda Imperial")
            assert api_whatsapp.handle_rdv_text_message(
                sender, "localização visita"
            ).startswith("Fazenda Imperial")
            assert api_whatsapp.handle_rdv_text_message(sender, "relatorio visita") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "relatório visita") is None
            assert len(sent) == 2
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender


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
            assert "Viagem cancelada com sucesso." in api_whatsapp.handle_rdv_text_message(
                sender, "km cancelar"
            )
            assert monthly
            assert weekly
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp._send_weekly_rdv_excel = original_weekly
        api_whatsapp._send_monthly_rdv_excel = original_monthly
