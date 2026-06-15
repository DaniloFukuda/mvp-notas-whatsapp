import tempfile
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def test_explicit_km_flow_does_not_capture_regular_messages():
    original_service = api_whatsapp.rdv_service
    original_excel_sender = api_whatsapp._send_weekly_rdv_excel
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

            missing_start = api_whatsapp.handle_rdv_text_message(
                sender, "km inicio"
            )
            assert "Informe a quilometragem junto com o comando." in missing_start
            assert service.get_open_km_launch_by_phone(sender) is None

            started = api_whatsapp.handle_rdv_text_message(
                sender, "km início 120350"
            )
            assert "Viagem iniciada com sucesso." in started
            assert "KM inicial: 120350" in started
            trip = service.get_open_km_launch_by_phone(sender)
            assert trip["status_fluxo"] == "viagem_em_andamento"
            assert not trip["cidade_origem"]
            assert not trip["cidade_destino"]

            regular = api_whatsapp.handle_rdv_text_message(sender, "ola")
            assert "Ciclus Agro - RDV por WhatsApp" in regular
            assert "quilometragem" not in regular.lower()
            assert service.get_open_km_launch_by_phone(sender)["id"] == trip["id"]

            summary = api_whatsapp.handle_rdv_text_message(sender, "resumo")
            assert "Resumo geral da semana" in summary
            assert service.get_open_km_launch_by_phone(sender)["id"] == trip["id"]

            sent = []
            api_whatsapp._send_weekly_rdv_excel = lambda phone: sent.append(phone)
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha") is None
            assert sent == [sender]
            assert service.get_open_km_launch_by_phone(sender)["id"] == trip["id"]

            duplicate = api_whatsapp.handle_rdv_text_message(
                sender, "iniciar km 120400"
            )
            assert "Ja existe uma viagem em andamento." in duplicate
            assert len(
                [
                    item
                    for item in service.list_launches()
                    if item["status_fluxo"] == "viagem_em_andamento"
                ]
            ) == 1

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
