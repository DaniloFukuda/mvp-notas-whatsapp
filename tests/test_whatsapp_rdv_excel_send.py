import tempfile
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def test_planilha_remains_global_command_during_open_trip():
    original_service = api_whatsapp.rdv_service
    original_excel_sender = api_whatsapp._send_weekly_rdv_excel
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            api_whatsapp.handle_rdv_text_message(sender, "km inicio 1000")

            sent = []
            api_whatsapp._send_weekly_rdv_excel = lambda phone: sent.append(phone)
            assert api_whatsapp.handle_rdv_text_message(sender, "planilha") is None
            assert sent == [sender]
            assert service.get_open_km_launch_by_phone(sender) is not None
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp._send_weekly_rdv_excel = original_excel_sender
