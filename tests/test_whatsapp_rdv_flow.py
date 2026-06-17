import tempfile
import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def test_explicit_km_flow_does_not_capture_regular_messages():
    original_service = api_whatsapp.rdv_service
    original_excel_sender = api_whatsapp._send_weekly_rdv_excel
    original_monthly_excel_sender = api_whatsapp._send_monthly_rdv_excel
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]

            assert api_whatsapp.handle_rdv_text_message(
                sender, "km"
            ) == api_whatsapp.KM_HELP_MESSAGE
            assert service.get_open_km_launch_by_phone(sender) is None

            loose_number = api_whatsapp.handle_rdv_text_message(sender, "1200")
            assert loose_number == api_whatsapp.MENU_NUMBER_MESSAGE
            assert service.list_launches() == []

            empty_summary = api_whatsapp.handle_rdv_text_message(sender, "resumo")
            assert "Lancamentos: 0" in empty_summary
            assert "Total: R$ 0,00" in empty_summary

            missing_start = api_whatsapp.handle_rdv_text_message(
                sender, "km inicio"
            )
            assert "Informe a quilometragem junto com o comando." in missing_start
            assert service.get_open_km_launch_by_phone(sender) is None

            started = api_whatsapp.handle_rdv_text_message(
                sender, "km início 120350"
            )
            assert "KM inicial: 120350" in started
            assert "Qual a cidade/local de origem?" in started
            trip = service.get_open_km_launch_by_phone(sender)
            assert trip["status_fluxo"] == "aguardando_km_origem"
            assert not trip["cidade_origem"]
            assert not trip["cidade_destino"]

            summary = api_whatsapp.handle_rdv_text_message(sender, "resumo")
            assert "Resumo geral do mes" in summary
            assert service.get_open_km_launch_by_phone(sender)["id"] == trip["id"]

            sent = []
            api_whatsapp._send_monthly_rdv_excel = lambda phone, month="": sent.append(
                (phone, month)
            )
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha") is None
            assert sent == [
                (
                    sender,
                    api_whatsapp.calculate_month_reference(api_whatsapp.date.today()),
                )
            ]
            assert service.get_open_km_launch_by_phone(sender)["id"] == trip["id"]

            duplicate = api_whatsapp.handle_rdv_text_message(
                sender, "iniciar km 120400"
            )
            assert "Ja existe uma viagem em andamento." in duplicate
            assert len(
                [
                    item
                    for item in service.list_launches()
                    if item["status_fluxo"] in {
                        "aguardando_km_origem",
                        "aguardando_km_destino",
                        "viagem_em_andamento",
                    }
                ]
            ) == 1

            premature_end = api_whatsapp.handle_rdv_text_message(
                sender, "km termino 120500"
            )
            assert "origem" in premature_end.lower()

            origin_reply = api_whatsapp.handle_rdv_text_message(sender, "Formosa")
            assert origin_reply == "\n".join(
                [
                    "Origem registrada: Formosa.",
                    "Qual a cidade/local de destino?",
                ]
            )
            trip = service.get_open_km_launch_by_phone(sender)
            assert trip["status_fluxo"] == "aguardando_km_destino"
            assert trip["cidade_origem"] == "Formosa"

            premature_end = api_whatsapp.handle_rdv_text_message(
                sender, "km termino 120500"
            )
            assert "destino" in premature_end.lower()

            destination_reply = api_whatsapp.handle_rdv_text_message(
                sender, "Fazenda Santa Rita"
            )
            assert destination_reply == "\n".join(
                [
                    "Destino registrado: Fazenda Santa Rita.",
                    "Quando terminar, envie:",
                    "km termino 120500",
                ]
            )
            trip = service.get_open_km_launch_by_phone(sender)
            assert trip["status_fluxo"] == "viagem_em_andamento"
            assert trip["cidade_destino"] == "Fazenda Santa Rita"

            missing_end = api_whatsapp.handle_rdv_text_message(
                sender, "km termino"
            )
            assert "Informe a quilometragem junto com o comando." in missing_end
            assert service.get_open_km_launch_by_phone(sender) is not None

            for value in ("120350", "120300"):
                rejected = api_whatsapp.handle_rdv_text_message(
                    sender, f"km fim {value}"
                )
                assert "deve ser maior" in rejected
                assert service.get_open_km_launch_by_phone(sender) is not None

            completed_reply = api_whatsapp.handle_rdv_text_message(
                sender, "km término 120500"
            )
            assert completed_reply == "\n".join(
                [
                    "Viagem finalizada com sucesso.",
                    "Origem: Formosa",
                    "Destino: Fazenda Santa Rita",
                    "KM inicial: 120350",
                    "KM final: 120500",
                    "KM rodado: 150 km",
                ]
            )
            completed = service.get_expense(trip["id"])
            assert completed["status_fluxo"] == "completo"
            assert completed["km_rodado"] == 150
            assert service.get_open_km_launch_by_phone(sender) is None
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp._send_weekly_rdv_excel = original_excel_sender
        api_whatsapp._send_monthly_rdv_excel = original_monthly_excel_sender


def test_loose_number_outside_manual_value_state_does_not_create_launch():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]

            reply = api_whatsapp.handle_rdv_text_message(sender, "1200")

            assert reply == api_whatsapp.MENU_NUMBER_MESSAGE
            assert service.list_launches() == []
            summary = api_whatsapp.handle_rdv_text_message(sender, "resumo")
            assert "Lancamentos: 0" in summary
            assert "Total: R$ 0,00" in summary
    finally:
        api_whatsapp.rdv_service = original_service


def test_rdv_summary_commands_support_month_week_and_previous_month():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            service.register_whatsapp_expense(
                colaborador_id=collaborator["id"],
                colaborador=collaborator["nome"],
                telefone_origem=sender,
                tipo_entrada="imagem",
                data_despesa="2026-06-14",
                data_detectada="2026-06-14",
                categoria="alimentacao",
                valor=80,
                caminho_arquivo="junho.jpg",
                status_fluxo="completo",
            )

            monthly = api_whatsapp.handle_rdv_text_message(sender, "resumo")
            specific_month = api_whatsapp.handle_rdv_text_message(
                sender, "resumo 2026-06"
            )
            weekly = api_whatsapp.handle_rdv_text_message(sender, "resumo 2026-W24")
            weekly_alias = api_whatsapp.handle_rdv_text_message(
                sender, "resumo semanal"
            )

            assert "Resumo geral do mes" in monthly
            assert "Resumo geral do mes 2026-06" in specific_month
            assert "Total: R$ 80,00" in specific_month
            assert "Resumo geral da semana 2026-W24" in weekly
            assert "Total: R$ 80,00" in weekly
            assert "Resumo geral da semana" in weekly_alias

            previous = api_whatsapp.handle_rdv_text_message(sender, "resumo anterior")
            assert "Resumo geral do mes" in previous
    finally:
        api_whatsapp.rdv_service = original_service


def test_rdv_excel_commands_support_month_week_and_specific_references():
    original_service = api_whatsapp.rdv_service
    original_weekly_excel_sender = api_whatsapp._send_weekly_rdv_excel
    original_monthly_excel_sender = api_whatsapp._send_monthly_rdv_excel
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            monthly = []
            weekly = []
            api_whatsapp._send_monthly_rdv_excel = (
                lambda phone, month="": monthly.append((phone, month))
            )
            api_whatsapp._send_weekly_rdv_excel = (
                lambda phone, week="": weekly.append((phone, week))
            )

            assert api_whatsapp.handle_rdv_text_message(sender, "planilha") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "excel mensal") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "relatorio 2026-06") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha semanal") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "excel 2026-W24") is None

            assert monthly[0] == (
                sender,
                api_whatsapp.calculate_month_reference(api_whatsapp.date.today()),
            )
            assert monthly[1] == (sender, "2026-06")
            assert monthly[2] == (sender, "2026-06")
            assert weekly[0] == (
                sender,
                api_whatsapp.calculate_week_reference(api_whatsapp.date.today()),
            )
            assert weekly[1] == (sender, "2026-W24")
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp._send_weekly_rdv_excel = original_weekly_excel_sender
        api_whatsapp._send_monthly_rdv_excel = original_monthly_excel_sender


def test_manual_value_state_still_accepts_number():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            pending = service.register_whatsapp_expense(
                colaborador_id=collaborator["id"],
                colaborador=collaborator["nome"],
                telefone_origem=sender,
                tipo_entrada="imagem",
                categoria="outro",
                status_fluxo="aguardando_valor",
                caminho_arquivo="comprovante.jpg",
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "1200")

            assert "Valor registrado manualmente: R$ 1.200,00." in reply
            assert "data do comprovante" in reply
            saved = service.get_expense(pending["id"])
            assert saved["valor"] == 1200
            assert saved["origem_valor"] == "manual"
            assert saved["status_fluxo"] == "aguardando_data_comprovante"
    finally:
        api_whatsapp.rdv_service = original_service


def test_received_receipt_with_value_without_date_asks_for_receipt_date():
    reply = api_whatsapp._rdv_received_message(
        {
            "status_fluxo": "aguardando_data_comprovante",
            "valor": 80,
        }
    )

    assert reply == (
        "Detectei o valor R$ 80,00, mas nao consegui identificar a data do "
        "comprovante. Informe a data do comprovante no formato 11/06/2026."
    )


def test_manual_value_then_manual_date_and_category_completes_rdv():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            pending = service.register_whatsapp_expense(
                colaborador_id=collaborator["id"],
                colaborador=collaborator["nome"],
                telefone_origem=sender,
                tipo_entrada="imagem",
                categoria="outro",
                status_fluxo="aguardando_valor",
                caminho_arquivo="comprovante.jpg",
            )

            value_reply = api_whatsapp.handle_rdv_text_message(sender, "64,00")
            assert "data do comprovante" in value_reply

            future_date = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
            invalid_date = api_whatsapp.handle_rdv_text_message(sender, future_date)
            assert invalid_date == (
                "Data invalida. Informe a data do comprovante no formato 11/06/2026."
            )

            date_reply = api_whatsapp.handle_rdv_text_message(sender, "11-06-2026")
            assert "Data registrada: 11/06/2026. Qual a categoria?" in date_reply

            completed_reply = api_whatsapp.handle_rdv_text_message(sender, "1")
            assert "RDV registrado com sucesso." in completed_reply
            assert "Data do comprovante: 11/06/2026." in completed_reply
            assert "Enviado no WhatsApp:" in completed_reply
            assert "Mes: 2026-06." in completed_reply
            assert "Semana: 2026-W24." in completed_reply
            completed = service.get_expense(pending["id"])
            assert completed["status_fluxo"] == "completo"
            assert completed["categoria"] == "combustivel"
            assert completed["data_despesa"] == "2026-06-11"
            assert completed["data_detectada"] == "2026-06-11"
    finally:
        api_whatsapp.rdv_service = original_service


def test_supported_command_aliases():
    assert api_whatsapp._parse_km_command("inicio km 120350") == (
        "start",
        "120350",
    )
    assert api_whatsapp._parse_km_command("iniciar km 120350") == (
        "start",
        "120350",
    )
    assert api_whatsapp._parse_km_command("fim km 120500") == ("end", "120500")
    assert api_whatsapp._parse_km_command("finalizar km 120500") == (
        "end",
        "120500",
    )
    assert api_whatsapp._parse_km_command("km final 120500") == ("end", "120500")
