import tempfile
import pytest
import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.rdv_service import (
    RDVService,
    calculate_month_reference,
    calculate_week_reference,
)


def test_calculate_month_reference_returns_year_month():
    assert calculate_month_reference(date(2026, 6, 14)) == "2026-06"


def test_service_starts_trip_waiting_for_origin_and_completes_with_route():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        trip = service.create_whatsapp_km_launch(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            km_start=120350,
        )
        assert trip["status_fluxo"] == "aguardando_km_origem"
        assert trip["km_inicio"] == 120350
        assert not trip["cidade_origem"]
        assert not trip["cidade_destino"]

        with pytest.raises(ValueError):
            service.complete_km_end(trip["id"], 120500)

        with_origin = service.save_km_origin(trip["id"], "Formosa")
        assert with_origin["status_fluxo"] == "aguardando_km_destino"
        assert with_origin["cidade_origem"] == "Formosa"

        underway = service.save_km_destination(trip["id"], "Fazenda Santa Rita")
        assert underway["status_fluxo"] == "viagem_em_andamento"
        assert underway["cidade_destino"] == "Fazenda Santa Rita"

        completed = service.complete_km_end(trip["id"], 120500)
        assert completed["status_fluxo"] == "completo"
        assert completed["cidade_origem"] == "Formosa"
        assert completed["cidade_destino"] == "Fazenda Santa Rita"
        assert completed["km_fim"] == 120500
        assert completed["km_rodado"] == 150
        assert completed["quilometragem"] == 150


def test_receipt_with_detected_value_and_valid_date_waits_for_category():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")

        receipt = service.create_whatsapp_receipt(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            input_type="imagem",
            file_path="cupom.jpg",
            whatsapp_message_id="wamid.valid-date",
            received_at="16/06/2026 10:00",
            analysis={
                "valor_detectado": 64,
                "data_detectada": "2026-06-11",
                "origem_valor": "ocr",
            },
        )

        assert receipt["status_fluxo"] == "aguardando_categoria"
        assert receipt["data_despesa"] == "2026-06-11"
        assert receipt["data_detectada"] == "2026-06-11"
        assert receipt["semana_referencia"] == calculate_week_reference("2026-06-11")


def test_ocr_receipt_uses_document_date_week_instead_of_received_date():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")

        receipt = service.create_whatsapp_receipt(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            input_type="imagem",
            file_path="mercado_pago.jpg",
            whatsapp_message_id="wamid.mercado-pago-date",
            received_at="16/06/2026 10:00",
            analysis={
                "valor_detectado": 80,
                "data_detectada": "2026-06-14",
                "fornecedor_detectado": "Mercado Pago",
                "origem_valor": "ocr",
            },
        )

        assert receipt["status_fluxo"] == "aguardando_categoria"
        assert receipt["valor"] == 80
        assert receipt["data_despesa"] == "2026-06-14"
        assert receipt["data_detectada"] == "2026-06-14"
        assert receipt["recebido_em"].startswith("2026-06-16")
        assert receipt["semana_referencia"] == calculate_week_reference("2026-06-14")
        assert calculate_week_reference("2026-06-14") == "2026-W24"
        assert calculate_week_reference("2026-06-16") == "2026-W25"


def test_receipt_with_detected_value_without_date_waits_for_manual_date():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")

        receipt = service.create_whatsapp_receipt(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            input_type="imagem",
            file_path="cupom.jpg",
            whatsapp_message_id="wamid.no-date",
            received_at="16/06/2026 10:00",
            analysis={"valor_detectado": 64, "origem_valor": "ocr"},
        )

        assert receipt["status_fluxo"] == "aguardando_data_comprovante"
        assert receipt["data_despesa"] == "2026-06-16"
        assert receipt["data_detectada"] == ""


def test_manual_receipt_date_updates_expense_date_detected_date_and_week():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        receipt = service.create_whatsapp_receipt(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            input_type="imagem",
            file_path="cupom.jpg",
            whatsapp_message_id="wamid.manual-date",
            received_at="16/06/2026 10:00",
            analysis={"valor_detectado": 64, "origem_valor": "ocr"},
        )

        saved = service.save_launch_receipt_date(receipt["id"], "11.06.2026")

        assert saved["status_fluxo"] == "aguardando_categoria"
        assert saved["data_despesa"] == "2026-06-11"
        assert saved["data_detectada"] == "2026-06-11"
        assert saved["semana_referencia"] == calculate_week_reference("2026-06-11")


def test_manual_textual_receipt_dates_update_expense_date_detected_date_and_week():
    examples = (
        "14/06/2026",
        "14-06-2026",
        "14.06.2026",
        "2026-06-14",
        "14/junho/2026",
        "14 de junho de 2026",
    )
    for index, value in enumerate(examples):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv.db")
            collaborator = service.get_collaborator_by_phone("5500000000001")
            receipt = service.create_whatsapp_receipt(
                collaborator_id=collaborator["id"],
                phone=collaborator["telefone_whatsapp"],
                input_type="imagem",
                file_path=f"cupom-{index}.jpg",
                whatsapp_message_id=f"wamid.manual-date-{index}",
                received_at="16/06/2026 10:00",
                analysis={"valor_detectado": 64, "origem_valor": "ocr"},
            )

            saved = service.save_launch_receipt_date(receipt["id"], value)

            assert saved["status_fluxo"] == "aguardando_categoria"
            assert saved["data_despesa"] == "2026-06-14"
            assert saved["data_detectada"] == "2026-06-14"
            assert saved["semana_referencia"] == calculate_week_reference("2026-06-14")


def test_manual_value_then_manual_date_and_category_enter_correct_weekly_report():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        receipt = service.create_whatsapp_receipt(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            input_type="imagem",
            file_path="cupom.jpg",
            whatsapp_message_id="wamid.manual-report",
            received_at="16/06/2026 10:00",
        )

        with_value = service.save_launch_value(receipt["id"], "80,00")
        assert with_value["status_fluxo"] == "aguardando_data_comprovante"

        with_date = service.save_launch_receipt_date(receipt["id"], "14/junho/2026")
        assert with_date["status_fluxo"] == "aguardando_categoria"

        completed = service.complete_launch_category(receipt["id"], "alimentacao")
        assert completed["status_fluxo"] == "completo"
        assert completed["data_despesa"] == "2026-06-14"
        assert completed["data_detectada"] == "2026-06-14"

        document_week = calculate_week_reference("2026-06-14")
        received_week = calculate_week_reference("2026-06-16")
        document_report = service.weekly_report_data(week=document_week)
        received_report = service.weekly_report_data(week=received_week)
        weekly_summary = service.weekly_report(week=document_week)

        assert [item["id"] for item in document_report["lancamentos"]] == [
            completed["id"]
        ]
        assert received_report["lancamentos"] == []
        assert weekly_summary["quantidade_lancamentos"] == 1
        assert weekly_summary["total_geral"] == 80


def test_future_receipt_date_is_rejected():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        receipt = service.create_whatsapp_receipt(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            input_type="imagem",
            file_path="cupom.jpg",
            whatsapp_message_id="wamid.future-date",
            received_at="16/06/2026 10:00",
            analysis={"valor_detectado": 64, "origem_valor": "ocr"},
        )

        future_date = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
        with pytest.raises(ValueError):
            service.save_launch_receipt_date(receipt["id"], future_date)


def test_weekly_report_ignores_cancelled_launches():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        service.register_whatsapp_expense(
            colaborador_id=collaborator["id"],
            colaborador=collaborator["nome"],
            telefone_origem=collaborator["telefone_whatsapp"],
            tipo_entrada="texto",
            categoria="outro",
            valor=0,
            status_fluxo="cancelado",
            observacao="viagem cancelada pelo WhatsApp",
        )

        report = service.weekly_report(week=calculate_week_reference(date.today()))

        assert report["quantidade_lancamentos"] == 0
        assert report["quantidade_comprovantes"] == 0
        assert report["total_geral"] == 0
        assert report["por_categoria"] == {}


def test_weekly_report_keeps_completed_km_out_of_expense_totals():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        trip = service.create_whatsapp_km_launch(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            km_start=1200,
        )
        service.save_km_origin(trip["id"], "Formosa")
        service.save_km_destination(trip["id"], "Fazenda Santa Rita")
        service.complete_km_end(trip["id"], 1300)

        report = service.weekly_report(week=calculate_week_reference(date.today()))

        assert report["quantidade_lancamentos"] == 0
        assert report["quantidade_comprovantes"] == 0
        assert report["total_geral"] == 0
        assert report["por_categoria"] == {}
        assert report["quilometragem_total"] == 100


def test_weekly_report_sums_real_expense_total_and_category():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        service.register_whatsapp_expense(
            colaborador_id=collaborator["id"],
            colaborador=collaborator["nome"],
            telefone_origem=collaborator["telefone_whatsapp"],
            tipo_entrada="imagem",
            categoria="combustivel",
            valor=150,
            caminho_arquivo="comprovante.jpg",
            status_fluxo="completo",
        )

        report = service.weekly_report(week=calculate_week_reference(date.today()))

        assert report["quantidade_lancamentos"] == 1
        assert report["quantidade_comprovantes"] == 1
        assert report["total_geral"] == 150
        assert report["por_categoria"] == {"combustivel": 150}
        assert report["quilometragem_total"] == 0


def test_weekly_report_shows_km_separate_from_real_expense():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        trip = service.create_whatsapp_km_launch(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            km_start=1200,
        )
        service.save_km_origin(trip["id"], "Formosa")
        service.save_km_destination(trip["id"], "Fazenda Santa Rita")
        service.complete_km_end(trip["id"], 1300)
        service.register_whatsapp_expense(
            colaborador_id=collaborator["id"],
            colaborador=collaborator["nome"],
            telefone_origem=collaborator["telefone_whatsapp"],
            tipo_entrada="imagem",
            categoria="pedagio",
            valor=25,
            caminho_arquivo="pedagio.jpg",
            status_fluxo="completo",
        )

        report = service.weekly_report(week=calculate_week_reference(date.today()))

        assert report["quantidade_lancamentos"] == 1
        assert report["quantidade_comprovantes"] == 1
        assert report["total_geral"] == 25
        assert report["por_categoria"] == {"pedagio": 25}
        assert report["quilometragem_total"] == 100


def test_weekly_report_ignores_zero_text_without_receipt_or_real_expense():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        service.register_whatsapp_expense(
            colaborador_id=collaborator["id"],
            colaborador=collaborator["nome"],
            telefone_origem=collaborator["telefone_whatsapp"],
            tipo_entrada="texto",
            categoria="outro",
            valor=0,
            status_fluxo="completo",
        )

        report = service.weekly_report(week=calculate_week_reference(date.today()))

        assert report["quantidade_lancamentos"] == 0
        assert report["quantidade_comprovantes"] == 0
        assert report["total_geral"] == 0
        assert report["por_categoria"] == {}


def test_monthly_report_includes_only_document_month_and_sums_totals():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        danilo = service.get_collaborator_by_phone("5500000000001")
        marcelo = service.get_collaborator_by_phone("5500000000002")

        june = service.create_whatsapp_receipt(
            collaborator_id=danilo["id"],
            phone=danilo["telefone_whatsapp"],
            input_type="imagem",
            file_path="junho.jpg",
            whatsapp_message_id="wamid.month.june",
            received_at="2026-07-01T09:00:00",
            analysis={
                "valor_detectado": 80,
                "data_detectada": "2026-06-14",
                "origem_valor": "ocr",
            },
        )
        service.complete_launch_category(june["id"], "alimentacao")
        service.register_whatsapp_expense(
            colaborador_id=marcelo["id"],
            colaborador=marcelo["nome"],
            telefone_origem=marcelo["telefone_whatsapp"],
            tipo_entrada="imagem",
            data_despesa="2026-06-20",
            data_detectada="2026-06-20",
            categoria="pedagio",
            valor=25,
            caminho_arquivo="pedagio.jpg",
            status_fluxo="completo",
        )
        service.register_whatsapp_expense(
            colaborador_id=danilo["id"],
            colaborador=danilo["nome"],
            telefone_origem=danilo["telefone_whatsapp"],
            tipo_entrada="imagem",
            data_despesa="2026-05-31",
            data_detectada="2026-05-31",
            categoria="combustivel",
            valor=200,
            caminho_arquivo="maio.jpg",
            status_fluxo="completo",
        )

        report_data = service.monthly_report_data(month="2026-06")
        report = service.monthly_report(month="2026-06")

        assert report_data["mes"] == "2026-06"
        assert {item["data_despesa"] for item in report_data["lancamentos"]} == {
            "2026-06-14",
            "2026-06-20",
        }
        assert report["quantidade_lancamentos"] == 2
        assert report["quantidade_comprovantes"] == 2
        assert report["total_geral"] == 105
        assert report["por_colaborador"] == {
            "Danilo": 80,
            "Marcelo": 25,
        }
        assert report["por_categoria"] == {
            "alimentacao": 80,
            "pedagio": 25,
        }


def test_monthly_report_includes_km_for_month():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        trip = service.create_whatsapp_km_launch(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            km_start=1000,
            received_at="2026-06-10T08:00:00",
        )
        service.save_km_origin(trip["id"], "Formosa")
        service.save_km_destination(trip["id"], "Fazenda")
        service.complete_km_end(trip["id"], 1120)

        report = service.monthly_report(month="2026-06")
        report_data = service.monthly_report_data(month="2026-06")

        assert report["quantidade_lancamentos"] == 0
        assert report["quilometragem_total"] == 120
        assert len(report_data["quilometragens"]) == 1
