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
    api_whatsapp.visita_edit_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
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

            reviewing = visitas.obter_visita(visita["id"])
            assert "Revisao da visita" in reply
            assert "Digite CONFIRMAR para finalizar a visita." in reply
            assert "Digite CANCELAR para sair sem finalizar." in reply
            assert reviewing["status"] == "aberta"
            assert reviewing["estado_fluxo"] == "revisao_visita"

            confirm_reply = api_whatsapp.handle_rdv_text_message(sender, "confirmar")
            closed = visitas.obter_visita(visita["id"])
            assert "Visita fechada com sucesso." in confirm_reply
            assert closed["status"] == "fechada"
            assert closed["fechado_em"]
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas


def test_visita_revisao_antes_de_concluir_relatorio():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)

            api_whatsapp.handle_rdv_text_message(sender, "visita")
            api_whatsapp.handle_rdv_text_message(sender, "Fazenda Imperial")
            api_whatsapp.handle_rdv_text_message(sender, "Alexander Duarte Paniago")
            api_whatsapp.handle_rdv_text_message(sender, "Paulo Silva")
            api_whatsapp.handle_rdv_text_message(sender, "2299 ha")
            api_whatsapp.handle_rdv_text_message(sender, "26/27")
            api_whatsapp.handle_rdv_text_message(
                sender,
                "Apresentacao de produtos ao cliente",
            )
            api_whatsapp.handle_rdv_text_message(sender, "obs Pedido de 300T")

            review_reply = api_whatsapp.handle_rdv_text_message(sender, "fechar visita")

            visit = visitas.obter_visita_aberta(sender)
            assert "Revisao da visita" in review_reply
            assert "1. Fazenda: Fazenda Imperial" in review_reply
            assert "Data da visita:" in review_reply
            assert "3. Tecnico: Danilo" in review_reply
            assert "2. Gerente: Paulo Silva" in review_reply
            assert "6. Descricao: Apresentacao de produtos ao cliente" in review_reply
            assert "7. Observacao: Pedido de 300T" in review_reply
            assert visit["status"] == "aberta"
            assert visit["estado_fluxo"] == "revisao_visita"

            completed_reply = api_whatsapp.handle_rdv_text_message(sender, "confirmar")
            closed = visitas.obter_visita(visit["id"])
            assert "Visita fechada com sucesso." in completed_reply
            assert closed["status"] == "fechada"
            assert closed["estado_fluxo"] == "fechada"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()


def test_visita_revisao_corrige_fazenda_e_volta_para_resumo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Antiga")
            visitas.atualizar_campo(visita["id"], "gerente", "Paulo Silva")
            visitas.atualizar_campo(visita["id"], "tipo_visita", "Visita tecnica")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            api_whatsapp.handle_rdv_text_message(sender, f"continuar visita {visita['id']}")
            api_whatsapp.handle_rdv_text_message(sender, "fechar visita")
            ask_farm = api_whatsapp.handle_rdv_text_message(sender, "1")
            assert ask_farm == "Informe o novo nome da fazenda."
            updated_review = api_whatsapp.handle_rdv_text_message(
                sender,
                "Fazenda Corrigida",
            )

            assert "Revisao da visita" in updated_review
            assert "1. Fazenda: Fazenda Corrigida" in updated_review
            reviewing = visitas.obter_visita_aberta(sender)
            assert reviewing["estado_fluxo"] == "revisao_visita"

            api_whatsapp.handle_rdv_text_message(sender, "ok")
            closed = visitas.obter_visita(visita["id"])
            assert closed["status"] == "fechada"
            assert closed["fazenda"] == "Fazenda Corrigida"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()


def test_visita_revisao_cancelar_nao_conclui_relatorio():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Cancelada")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            api_whatsapp.handle_rdv_text_message(sender, f"continuar visita {visita['id']}")
            api_whatsapp.handle_rdv_text_message(sender, "fechar visita")
            cancel_reply = api_whatsapp.handle_rdv_text_message(sender, "cancelar")

            saved = visitas.obter_visita(visita["id"])
            assert cancel_reply == "Revisao cancelada. A visita continua aberta."
            assert saved["status"] == "aberta"
            assert saved["estado_fluxo"] == "visita_aberta"
            assert not saved["fechado_em"]
            assert visitas.obter_visita_aberta(sender) is not None
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()


def test_visita_revisao_corrige_area():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            api_whatsapp.handle_rdv_text_message(sender, f"continuar visita {visita['id']}")
            api_whatsapp.handle_rdv_text_message(sender, "fechar visita")
            ask_area = api_whatsapp.handle_rdv_text_message(sender, "4")
            assert ask_area == "Informe a nova area. Exemplo: 2299 ha"
            updated_review = api_whatsapp.handle_rdv_text_message(sender, "150 ha")

            assert "4. Area: 150 ha" in updated_review
            api_whatsapp.handle_rdv_text_message(sender, "sim")
            closed = visitas.obter_visita(visita["id"])
            assert closed["status"] == "fechada"
            assert closed["area_hectares"] == 150
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()


def test_visita_revisao_corrige_observacoes():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.adicionar_observacao(visita["id"], "Observacao antiga")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            api_whatsapp.handle_rdv_text_message(sender, f"continuar visita {visita['id']}")
            api_whatsapp.handle_rdv_text_message(sender, "fechar visita")
            ask_observation = api_whatsapp.handle_rdv_text_message(sender, "7")
            assert ask_observation == "Informe as novas observacoes da visita."
            updated_review = api_whatsapp.handle_rdv_text_message(
                sender,
                "Observacao corrigida",
            )

            assert "7. Observacao: Observacao corrigida" in updated_review
            api_whatsapp.handle_rdv_text_message(sender, "finalizar")
            closed = visitas.obter_visita(visita["id"])
            assert closed["status"] == "fechada"
            assert closed["observacoes"] == "Observacao corrigida"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()


def test_nova_visita_nao_usa_visita_aberta_antiga():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            antiga = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(antiga["id"], "fazenda", "FAZENDA NOVA FRONTEIRA")
            visitas.atualizar_campo(antiga["id"], "estado_fluxo", "visita_aberta")

            start = api_whatsapp.handle_rdv_text_message(sender, "nova visita")
            created = api_whatsapp.handle_rdv_text_message(sender, "Itapuã Prestes")
            reply = api_whatsapp.handle_visitas_media_message(
                sender,
                "image",
                "media-1",
                "foto-itapua.jpg",
                caption="Talhao novo",
            )

            data = visitas.listar_visitas_validas()
            nova = next(item for item in data["visitas"] if item["fazenda"] == "Itapuã Prestes")
            antiga_completa = visitas.obter_visita_completa(antiga["id"])
            nova_completa = visitas.obter_visita_completa(nova["id"])
            assert "Vamos iniciar uma nova visita técnica." in start
            assert "Visita criada para ITAPUÃ PRESTES." in created
            assert "Foto salva na visita Itapuã Prestes." in reply
            assert antiga_completa["midias"] == []
            assert len(nova_completa["midias"]) == 1
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_new_visit_states.clear()


def test_visita_com_aberta_existente_pede_escolha():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "FAZENDA NOVA FRONTEIRA")

            reply = api_whatsapp.handle_rdv_text_message(sender, "visita")

            assert "Você já possui uma visita aberta:" in reply
            assert f"continuar visita {visita['id']}" in reply
            assert "nova visita" in reply
            assert "fechar visita" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_new_visit_states.clear()


def test_continuar_visita_define_visita_ativa():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.atualizar_campo(visita["id"], "estado_fluxo", "visita_aberta")

            start = api_whatsapp.handle_rdv_text_message(sender, f"continuar visita {visita['id']}")
            reply = api_whatsapp.handle_visitas_media_message(
                sender,
                "image",
                "media-2",
                "foto-imperial.jpg",
            )

            saved = visitas.obter_visita_completa(visita["id"])
            assert "Você voltou para a visita" in start
            assert "Foto salva na visita Fazenda Imperial." in reply
            assert len(saved["midias"]) == 1
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()


def test_fechar_visita_limpa_estado_ativo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "nova visita")
            api_whatsapp.handle_rdv_text_message(sender, "Itapuã Prestes")
            visita_id = api_whatsapp.visita_active_states[sender]

            close_reply = api_whatsapp.handle_rdv_text_message(sender, "fechar visita")
            assert "Revisao da visita" in close_reply
            assert sender in api_whatsapp.visita_active_states

            confirm_reply = api_whatsapp.handle_rdv_text_message(sender, "confirmar")
            media_reply = api_whatsapp.handle_visitas_media_message(
                sender,
                "image",
                "media-3",
                "foto-fechada.jpg",
            )

            saved = visitas.obter_visita_completa(visita_id)
            assert "Visita fechada com sucesso." in confirm_reply
            assert sender not in api_whatsapp.visita_active_states
            assert media_reply == "Nenhuma visita em andamento encontrada."
            assert saved["midias"] == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_new_visit_states.clear()


def test_cancelar_visita_limpa_estado_ativo():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "nova visita")
            api_whatsapp.handle_rdv_text_message(sender, "Itapuã Prestes")
            visita_id = api_whatsapp.visita_active_states[sender]

            cancel_reply = api_whatsapp.handle_rdv_text_message(sender, "cancelar visita")
            media_reply = api_whatsapp.handle_visitas_media_message(
                sender,
                "image",
                "media-4",
                "foto-cancelada.jpg",
            )

            saved = visitas.obter_visita_completa(visita_id)
            assert cancel_reply == "Visita cancelada com sucesso."
            assert media_reply == "Nenhuma visita em andamento encontrada."
            assert saved["midias"] == []
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_new_visit_states.clear()


def test_fluxo_edicao_nao_interfere_com_visita_ativa():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            api_whatsapp.handle_rdv_text_message(sender, "nova visita")
            api_whatsapp.handle_rdv_text_message(sender, "Itapuã Prestes")
            visita_id = api_whatsapp.visita_active_states[sender]
            visitas.atualizar_campo(visita_id, "gerente", "Marcos")

            api_whatsapp.handle_rdv_text_message(sender, f"editar visita {visita_id}")
            reply = api_whatsapp.handle_rdv_text_message(sender, "gerente = X")

            saved = visitas.obter_visita_completa(visita_id)
            assert "Campo atualizado:" in reply
            assert saved["gerente"] == "X"
            assert saved["dados_coletados"] == []
            assert saved["observacoes"] in (None, "")
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()
        api_whatsapp.visita_active_states.clear()


def test_ver_visita_por_id():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Marcelo Fukuda")
            visitas.atualizar_campo(visita["id"], "fazenda", "FAZENDA NOVA FRONTEIRA")
            visitas.atualizar_campo(visita["id"], "gerente", "Marcos")
            visitas.atualizar_campo(visita["id"], "data_visita", "2026-06-17")

            reply = api_whatsapp.handle_rdv_text_message(sender, f"ver visita {visita['id']}")

            assert f"Visita #{visita['id']} - FAZENDA NOVA FRONTEIRA" in reply
            assert "Status: aberta" in reply
            assert "Técnico: Marcelo Fukuda" in reply
            assert "Data: 17/06/2026" in reply
            assert "Gerente/responsável: Marcos" in reply
            assert f"editar visita {visita['id']}" in reply
            assert f"relatório visita {visita['id']}" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()


def test_editar_visita_campo_gerente():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            visitas.atualizar_campo(visita["id"], "gerente", "Marcos")

            start = api_whatsapp.handle_rdv_text_message(sender, f"editar visita {visita['id']}")
            reply = api_whatsapp.handle_rdv_text_message(sender, "gerente = Marcos Silva")

            saved = visitas.obter_visita(visita["id"])
            assert f"Você está editando a visita #{visita['id']}" in start
            assert saved["gerente"] == "Marcos Silva"
            assert "Campo atualizado:" in reply
            assert "Gerente/responsável" in reply
            assert "Antes: Marcos" in reply
            assert "Depois: Marcos Silva" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()


def test_editar_visita_observacoes_reflete_no_pdf():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "fazenda", "Fazenda Imperial")
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, filename, caption, mime_type, content)
                )
            )

            api_whatsapp.handle_rdv_text_message(sender, f"editar visita {visita['id']}")
            api_whatsapp.handle_rdv_text_message(
                sender,
                "observações = Cliente solicitou orçamento.",
            )
            reply = api_whatsapp.handle_rdv_text_message(sender, f"relatorio visita {visita['id']}")

            saved = visitas.obter_visita_completa(visita["id"])
            assert reply is None
            assert saved["observacoes"] == "Cliente solicitou orçamento."
            assert sent[0][4].startswith(b"%PDF")
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_document = original_sender
        api_whatsapp.visita_edit_states.clear()


def test_editar_visita_cancelada_bloqueia():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.cancelar_visita(visita["id"])

            reply = api_whatsapp.handle_rdv_text_message(sender, f"editar visita {visita['id']}")

            assert "cancelada" in reply
            assert "não pode ser editada" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()


def test_editar_visita_campo_invalido():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")

            api_whatsapp.handle_rdv_text_message(sender, f"editar visita {visita['id']}")
            reply = api_whatsapp.handle_rdv_text_message(sender, "campo_invalido = x")

            assert "Não reconheci esse campo." in reply
            assert "Campos aceitos" in reply
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()


def test_fechar_edicao():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "gerente", "Marcos")
            visitas.fechar_visita(visita["id"])

            api_whatsapp.handle_rdv_text_message(sender, f"editar visita {visita['id']}")
            close_reply = api_whatsapp.handle_rdv_text_message(sender, "fechar edição")
            next_reply = api_whatsapp.handle_rdv_text_message(sender, "gerente = Marcos Silva")

            saved = visitas.obter_visita(visita["id"])
            assert "Edição finalizada." in close_reply
            assert saved["gerente"] == "Marcos"
            assert next_reply == api_whatsapp.RDV_MENU
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()


def test_cancelar_edicao():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, visitas, sender = _install_services(temp_dir)
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")

            api_whatsapp.handle_rdv_text_message(sender, f"editar visita {visita['id']}")
            reply = api_whatsapp.handle_rdv_text_message(sender, "cancelar edição")

            assert "Edição encerrada." in reply
            assert api_whatsapp.visita_edit_states == {}
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()


def test_edicao_de_outro_telefone_permitida():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services(temp_dir)
            other = rdv.get_collaborator_by_phone("5500000000002")["telefone_whatsapp"]
            visita = visitas.iniciar_visita(sender, tecnico_nome="Danilo")
            visitas.atualizar_campo(visita["id"], "gerente", "Marcos")

            start = api_whatsapp.handle_rdv_text_message(other, f"editar visita {visita['id']}")
            reply = api_whatsapp.handle_rdv_text_message(other, "gerente = Marcos Silva")

            assert "Você está editando" in start
            assert "Depois: Marcos Silva" in reply
            assert visitas.obter_visita(visita["id"])["gerente"] == "Marcos Silva"
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.visita_edit_states.clear()


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
