import tempfile
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def test_cancel_open_trip_and_report_when_none_exists():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]

            api_whatsapp.handle_rdv_text_message(sender, "km inicio 1000")
            assert api_whatsapp.handle_rdv_text_message(
                sender, "cancelar km"
            ) == "Viagem cancelada com sucesso."
            assert service.get_open_km_launch_by_phone(sender) is None
            assert "Nenhuma viagem em andamento" in (
                api_whatsapp.handle_rdv_text_message(sender, "cancelar km")
            )
    finally:
        api_whatsapp.rdv_service = original_service


def test_legacy_km_state_is_cancelled_on_next_message():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            legacy = service.register_whatsapp_expense(
                colaborador_id=collaborator["id"],
                telefone_origem=sender,
                tipo_entrada="texto",
                categoria="outro",
                status_fluxo="aguardando_km_fim",
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "km")
            assert reply == api_whatsapp.KM_HELP_MESSAGE
            assert service.get_expense(legacy["id"])["status_fluxo"] == "cancelado"
    finally:
        api_whatsapp.rdv_service = original_service
