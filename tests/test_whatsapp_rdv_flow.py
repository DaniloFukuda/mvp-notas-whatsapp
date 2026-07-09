import tempfile
import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_receipt_analysis_service import RDVReceiptAnalysisResult
from services.rdv_service import RDVService


def test_voltar_abre_menu_principal_quando_estado_do_transcritor_foi_perdido(
    monkeypatch,
):
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            menus_enviados = []
            monkeypatch.setattr(
                api_whatsapp,
                "send_main_menu_interactive",
                lambda phone: menus_enviados.append(phone),
            )

            for option in ("1", "2"):
                api_whatsapp.handle_rdv_text_message(sender, "transcrever áudio")
                api_whatsapp.handle_rdv_text_message(sender, option)
                api_whatsapp.whatsapp_menu_states.pop(sender, None)
                api_whatsapp.standalone_transcription_modes.pop(sender, None)

                reply = api_whatsapp.handle_rdv_text_message(sender, "voltar")

                assert reply is None
                assert sender not in api_whatsapp.whatsapp_menu_states
                assert sender not in api_whatsapp.standalone_transcription_modes

            assert menus_enviados == [sender, sender]
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.standalone_transcription_modes.clear()


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
            ) == api_whatsapp.KM_MENU_MESSAGE
            assert service.get_open_km_launch_by_phone(sender) is None

            loose_number = api_whatsapp.handle_rdv_text_message(sender, "1200")
            assert loose_number == api_whatsapp.KM_MENU_MESSAGE
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
        api_whatsapp.whatsapp_menu_states.clear()


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
            assert monthly[1] == (
                sender,
                api_whatsapp.calculate_month_reference(api_whatsapp.date.today()),
            )
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


def test_invalid_image_receipt_replies_error_and_keeps_waiting_state():
    original_service = api_whatsapp.rdv_service
    original_download = api_whatsapp.download_media
    original_sender = api_whatsapp.send_whatsapp_text
    original_analyzer = api_whatsapp.rdv_receipt_analysis_service
    original_message_check = api_whatsapp._was_whatsapp_message_processed
    original_image_check = api_whatsapp._was_whatsapp_image_processed_for_sender
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            sent_messages = []
            downloaded = Path(temp_dir) / "post-futebol.jpg"
            downloaded.write_bytes(b"not a receipt")

            api_whatsapp.download_media = lambda media_id, destino: downloaded
            api_whatsapp.send_whatsapp_text = lambda phone, text: sent_messages.append(
                (phone, text)
            )
            api_whatsapp.rdv_receipt_analysis_service = _InvalidReceiptAnalyzer()
            api_whatsapp._was_whatsapp_message_processed = lambda message_id: False
            api_whatsapp._was_whatsapp_image_processed_for_sender = (
                lambda image_sha256, phone: False
            )

            menu_reply = api_whatsapp.handle_rdv_text_message(sender, "rdv")
            assert "Envie uma foto ou documento do comprovante" in menu_reply
            assert (
                api_whatsapp.whatsapp_menu_states[sender]
                == api_whatsapp.RDV_WAITING_RECEIPT_STATE
            )

            api_whatsapp._handle_whatsapp_message(
                {
                    "from": sender,
                    "id": "wamid.invalid.image",
                    "type": "image",
                    "timestamp": "1780000000",
                    "image": {
                        "id": "media-invalid-image",
                        "sha256": "invalid-image-sha",
                        "mime_type": "image/jpeg",
                    },
                }
            )

            assert sent_messages == [
                (sender, api_whatsapp.INVALID_RDV_RECEIPT_MESSAGE)
            ]
            assert service.list_launches() == []
            assert (
                api_whatsapp.whatsapp_menu_states[sender]
                == api_whatsapp.RDV_WAITING_RECEIPT_STATE
            )
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.download_media = original_download
        api_whatsapp.send_whatsapp_text = original_sender
        api_whatsapp.rdv_receipt_analysis_service = original_analyzer
        api_whatsapp._was_whatsapp_message_processed = original_message_check
        api_whatsapp._was_whatsapp_image_processed_for_sender = original_image_check
        api_whatsapp.whatsapp_menu_states.clear()


def test_invalid_document_receipt_does_not_create_launch():
    original_service = api_whatsapp.rdv_service
    original_download = api_whatsapp.download_media
    original_sender = api_whatsapp.send_whatsapp_text
    original_analyzer = api_whatsapp.rdv_receipt_analysis_service
    original_message_check = api_whatsapp._was_whatsapp_message_processed
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            sent_messages = []
            downloaded = Path(temp_dir) / "arquivo-aleatorio.pdf"
            downloaded.write_bytes(b"%PDF-1.4")

            api_whatsapp.download_media = lambda media_id, destino: downloaded
            api_whatsapp.send_whatsapp_text = lambda phone, text: sent_messages.append(
                (phone, text)
            )
            api_whatsapp.rdv_receipt_analysis_service = _InvalidReceiptAnalyzer()
            api_whatsapp._was_whatsapp_message_processed = lambda message_id: False

            api_whatsapp._handle_whatsapp_message(
                {
                    "from": sender,
                    "id": "wamid.invalid.document",
                    "type": "document",
                    "timestamp": "1780000000",
                    "document": {
                        "id": "media-invalid-document",
                        "mime_type": "application/pdf",
                    },
                }
            )

            assert sent_messages[-1] == (
                sender,
                api_whatsapp.INVALID_RDV_RECEIPT_MESSAGE,
            )
            assert service.list_launches() == []
            assert (
                api_whatsapp.whatsapp_menu_states[sender]
                == api_whatsapp.RDV_WAITING_RECEIPT_STATE
            )
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.download_media = original_download
        api_whatsapp.send_whatsapp_text = original_sender
        api_whatsapp.rdv_receipt_analysis_service = original_analyzer
        api_whatsapp._was_whatsapp_message_processed = original_message_check
        api_whatsapp.whatsapp_menu_states.clear()


def test_valid_receipt_after_invalid_file_enters_review_before_saving():
    original_service = api_whatsapp.rdv_service
    original_download = api_whatsapp.download_media
    original_sender = api_whatsapp.send_whatsapp_text
    original_review_menu = api_whatsapp.send_rdv_review_menu_interactive
    original_analyzer = api_whatsapp.rdv_receipt_analysis_service
    original_message_check = api_whatsapp._was_whatsapp_message_processed
    original_image_check = api_whatsapp._was_whatsapp_image_processed_for_sender
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            sent_messages = []
            downloaded = Path(temp_dir) / "comprovante.jpg"
            downloaded.write_bytes(b"receipt")

            api_whatsapp.download_media = lambda media_id, destino: downloaded
            api_whatsapp.send_whatsapp_text = lambda phone, text: sent_messages.append(
                (phone, text)
            )
            api_whatsapp.send_rdv_review_menu_interactive = (
                lambda phone, pending: sent_messages.append(
                    (phone, api_whatsapp._rdv_review_fallback_message(pending))
                )
            )
            api_whatsapp.rdv_receipt_analysis_service = _ValidReceiptAnalyzer()
            api_whatsapp._was_whatsapp_message_processed = lambda message_id: False
            api_whatsapp._was_whatsapp_image_processed_for_sender = (
                lambda image_sha256, phone: False
            )
            api_whatsapp.whatsapp_menu_states[sender] = (
                api_whatsapp.RDV_WAITING_RECEIPT_STATE
            )

            api_whatsapp._handle_whatsapp_message(
                {
                    "from": sender,
                    "id": "wamid.valid.after.invalid",
                    "type": "image",
                    "timestamp": "1780000000",
                    "image": {
                        "id": "media-valid-image",
                        "sha256": "valid-image-sha",
                        "mime_type": "image/jpeg",
                    },
                }
            )

            launches = service.list_launches()
            assert launches == []
            assert (
                api_whatsapp.whatsapp_menu_states[sender]
                == api_whatsapp.RDV_REVIEW_CONFIRM_STATE
            )
            assert api_whatsapp.rdv_receipt_review_states[sender]["valor"] == 80
            assert "Revise o RDV antes de salvar" in sent_messages[-1][1]
            assert "Fonte da leitura: OCR" in sent_messages[-1][1]

            reply = api_whatsapp.handle_rdv_text_message(sender, "1")

            launches = service.list_launches()
            assert len(launches) == 1
            assert launches[0]["status_fluxo"] == "completo"
            assert launches[0]["valor"] == 80
            assert "RDV registrado com sucesso." in reply
            assert sender not in api_whatsapp.whatsapp_menu_states
            assert sender not in api_whatsapp.rdv_receipt_review_states
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.download_media = original_download
        api_whatsapp.send_whatsapp_text = original_sender
        api_whatsapp.rdv_receipt_analysis_service = original_analyzer
        api_whatsapp._was_whatsapp_message_processed = original_message_check
        api_whatsapp._was_whatsapp_image_processed_for_sender = original_image_check
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.rdv_receipt_review_states.clear()


def test_receipt_review_edits_fields_before_confirming():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            api_whatsapp._start_rdv_receipt_review(
                sender_phone=sender,
                caminho_arquivo="comprovante.jpg",
                whatsapp_message_id="wamid.review.edit",
                message_type="image",
                received_at="06/07/2026 10:00",
                analysis=_ValidReceiptAnalyzer().analyze_file("x").to_dict(),
            )

            assert "Informe o valor correto" in api_whatsapp.handle_rdv_text_message(
                sender, "2"
            )
            assert "Valor: R$ 150,00" in api_whatsapp.handle_rdv_text_message(
                sender, "150,00"
            )
            assert "Informe a data correta" in api_whatsapp.handle_rdv_text_message(
                sender, "3"
            )
            assert "Data: 06/07/2026" in api_whatsapp.handle_rdv_text_message(
                sender, "06/07/2026"
            )
            assert "Escolha a categoria correta" in api_whatsapp.handle_rdv_text_message(
                sender, "4"
            )
            assert "Categoria: Combustivel" in api_whatsapp.handle_rdv_text_message(
                sender, "1"
            )
            assert "Digite o comentario correto" in api_whatsapp.handle_rdv_text_message(
                sender, "5"
            )
            assert "abastecimento viagem fazenda" in api_whatsapp.handle_rdv_text_message(
                sender, "abastecimento viagem fazenda"
            )

            final = api_whatsapp.handle_rdv_text_message(sender, "1")

            expense = service.list_launches()[0]
            assert "RDV registrado com sucesso." in final
            assert expense["valor"] == 150
            assert expense["data_despesa"] == "2026-07-06"
            assert expense["categoria"] == "combustivel"
            assert expense["observacao"] == "abastecimento viagem fazenda"
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.rdv_receipt_review_states.clear()


def test_receipt_review_cancel_does_not_create_launch():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            api_whatsapp._start_rdv_receipt_review(
                sender_phone=sender,
                caminho_arquivo="comprovante.jpg",
                whatsapp_message_id="wamid.review.cancel",
                message_type="image",
                received_at="06/07/2026 10:00",
                analysis=_ValidReceiptAnalyzer().analyze_file("x").to_dict(),
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "6")

            assert reply == api_whatsapp.RDV_RECEIPT_CANCEL_MESSAGE
            assert service.list_launches() == []
            assert sender not in api_whatsapp.rdv_receipt_review_states
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.rdv_receipt_review_states.clear()


def test_receipt_review_interactive_list_reply_maps_to_confirm():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            api_whatsapp._start_rdv_receipt_review(
                sender_phone=sender,
                caminho_arquivo="comprovante.jpg",
                whatsapp_message_id="wamid.review.interactive",
                message_type="image",
                received_at="06/07/2026 10:00",
                analysis=_ValidReceiptAnalyzer().analyze_file("x").to_dict(),
            )
            text = api_whatsapp._extract_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "list_reply": {
                            "id": "rdv_review_confirm",
                            "title": "Confirmar e salvar",
                        }
                    },
                }
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, text)

            assert text == "1"
            assert "RDV registrado com sucesso." in reply
            assert len(service.list_launches()) == 1
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.whatsapp_menu_states.clear()
        api_whatsapp.rdv_receipt_review_states.clear()


def test_receipt_review_source_labels_qr_and_ocr():
    qr = RDVReceiptAnalysisResult(
        valor_detectado=150,
        data_detectada="2026-07-06",
        origem_valor="qr_code",
        reasons=["qr_code_detectado", "valor_encontrado_qr_code"],
    ).to_dict()
    ocr = _ValidReceiptAnalyzer().analyze_file("x").to_dict()

    assert api_whatsapp._analysis_source_label(qr) == "QR Code"
    assert api_whatsapp._analysis_source_label(ocr) == "OCR"


def test_cancelar_clears_waiting_receipt_state():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]

            api_whatsapp.handle_rdv_text_message(sender, "rdv")
            reply = api_whatsapp.handle_rdv_text_message(sender, "cancelar")

            assert reply == api_whatsapp.RDV_RECEIPT_CANCEL_MESSAGE
            assert sender not in api_whatsapp.whatsapp_menu_states
            assert service.list_launches() == []
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.whatsapp_menu_states.clear()


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
    assert api_whatsapp._parse_km_command("registrar km") == ("menu", "")
    assert api_whatsapp._parse_km_command("iniciar viagem") == ("start_prompt", "")
    assert api_whatsapp._parse_km_command("finalizar viagem") == ("end_prompt", "")
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


def test_km_menu_flow_has_priority_over_rdv_receipt_state():
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            api_whatsapp.rdv_service = service
            api_whatsapp.whatsapp_menu_states.clear()
            collaborator = service.get_collaborator_by_phone("5500000000001")
            sender = collaborator["telefone_whatsapp"]
            service.register_whatsapp_expense(
                colaborador_id=collaborator["id"],
                colaborador=collaborator["nome"],
                telefone_origem=sender,
                tipo_entrada="imagem",
                categoria="outro",
                status_fluxo="aguardando_data_comprovante",
                caminho_arquivo="comprovante.jpg",
            )

            reply = api_whatsapp.handle_rdv_text_message(sender, "registrar km")
            assert reply == api_whatsapp.KM_MENU_MESSAGE

            start_reply = api_whatsapp.handle_rdv_text_message(sender, "1")
            assert "KM inicial" in start_reply
            assert "comprovante" not in start_reply.lower()

            km_reply = api_whatsapp.handle_rdv_text_message(sender, "36988")
            assert "Qual a cidade/local de origem?" in km_reply
            assert "comprovante" not in km_reply.lower()

            origin_reply = api_whatsapp.handle_rdv_text_message(sender, "Mozarlandia GO")
            assert "Qual a cidade/local de destino?" in origin_reply
            assert "comprovante" not in origin_reply.lower()

            destination_reply = api_whatsapp.handle_rdv_text_message(sender, "Fazenda Modelo")
            assert "km termino 120500" in destination_reply
            assert "data do comprovante" not in destination_reply.lower()
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.whatsapp_menu_states.clear()


def test_open_km_state_has_priority_over_pending_receipt_date():
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
                categoria="outro",
                status_fluxo="aguardando_data_comprovante",
                caminho_arquivo="comprovante.jpg",
            )

            started = api_whatsapp.handle_rdv_text_message(sender, "km inicio 36988")
            assert "Qual a cidade/local de origem?" in started

            origin_reply = api_whatsapp.handle_rdv_text_message(sender, "Mozarlandia GO")
            date_like_reply = api_whatsapp.handle_rdv_text_message(sender, "19/06/2026")

            assert "comprovante" not in origin_reply.lower()
            assert "data do comprovante" not in date_like_reply.lower()
            assert "Destino registrado" in date_like_reply
    finally:
        api_whatsapp.rdv_service = original_service


class _InvalidReceiptAnalyzer:
    def analyze_file(self, file_path: str) -> RDVReceiptAnalysisResult:
        return RDVReceiptAnalysisResult(reasons=["texto_ocr_nao_detectado"])


class _ValidReceiptAnalyzer:
    def analyze_file(self, file_path: str) -> RDVReceiptAnalysisResult:
        return RDVReceiptAnalysisResult(
            valor_detectado=80,
            data_detectada="2026-06-14",
            fornecedor_detectado="Mercado Pago",
            origem_valor="ocr",
            confidence=0.85,
            reasons=[
                "valor_encontrado_ocr",
                "data_encontrada",
                "fornecedor_encontrado",
                "marcador_comprovante_encontrado",
            ],
        )
