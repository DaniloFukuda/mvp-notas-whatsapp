import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def test_pdf_commands_route_to_monthly_and_weekly_reports():
    original_service = api_whatsapp.rdv_service
    original_monthly_pdf_sender = api_whatsapp._send_monthly_rdv_pdf
    original_weekly_pdf_sender = api_whatsapp._send_weekly_rdv_pdf
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            monthly = []
            weekly = []
            api_whatsapp._send_monthly_rdv_pdf = (
                lambda phone, month="": monthly.append((phone, month))
            )
            api_whatsapp._send_weekly_rdv_pdf = (
                lambda phone, week="": weekly.append((phone, week))
            )

            assert api_whatsapp.handle_rdv_text_message(sender, "pdf") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "relatorio pdf") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "pdf rdv") is None
            assert api_whatsapp.handle_rdv_text_message(sender, "pdf semanal") is None
            assert (
                api_whatsapp.handle_rdv_text_message(sender, "relatorio semanal pdf")
                is None
            )

            current_month = api_whatsapp.calculate_month_reference(api_whatsapp.date.today())
            current_week = api_whatsapp.calculate_week_reference(api_whatsapp.date.today())
            assert monthly == [
                (sender, current_month),
                (sender, current_month),
                (sender, current_month),
            ]
            assert weekly == [
                (sender, current_week),
                (sender, current_week),
            ]
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp._send_monthly_rdv_pdf = original_monthly_pdf_sender
        api_whatsapp._send_weekly_rdv_pdf = original_weekly_pdf_sender


def test_pdf_rdv_document_is_sent_with_pdf_mime_type():
    original_service = api_whatsapp.rdv_service
    original_sender = api_whatsapp.send_whatsapp_document
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
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, content, filename, caption, mime_type)
                )
            )

            assert api_whatsapp.handle_rdv_text_message(sender, "pdf") is None

            assert len(sent) == 1
            to, content, filename, caption, mime_type = sent[0]
            assert to == sender
            assert content.startswith(b"%PDF")
            assert filename == api_whatsapp.RDV_MONTHLY_PDF_FILENAME
            assert caption == api_whatsapp.RDV_MONTHLY_PDF_CAPTION
            assert mime_type == api_whatsapp.RDV_PDF_MIME_TYPE
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.send_whatsapp_document = original_sender


def test_pdf_semanal_document_is_sent_with_pdf_mime_type():
    original_service = api_whatsapp.rdv_service
    original_sender = api_whatsapp.send_whatsapp_document
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            sent = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent.append(
                    (to, content, filename, caption, mime_type)
                )
            )

            assert api_whatsapp.handle_rdv_text_message(sender, "pdf semanal") is None

            assert len(sent) == 1
            to, content, filename, caption, mime_type = sent[0]
            assert to == sender
            assert content.startswith(b"%PDF")
            assert filename == api_whatsapp.RDV_WEEKLY_PDF_FILENAME
            assert caption == api_whatsapp.RDV_WEEKLY_PDF_CAPTION
            assert mime_type == api_whatsapp.RDV_PDF_MIME_TYPE
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.send_whatsapp_document = original_sender
