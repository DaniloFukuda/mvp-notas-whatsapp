import tempfile
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.rdv_service import RDVService, calculate_week_reference


def test_service_starts_and_completes_trip_without_route_fields():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv.db")
        collaborator = service.get_collaborator_by_phone("5500000000001")
        trip = service.create_whatsapp_km_launch(
            collaborator_id=collaborator["id"],
            phone=collaborator["telefone_whatsapp"],
            km_start=120350,
        )
        assert trip["status_fluxo"] == "viagem_em_andamento"
        assert trip["km_inicio"] == 120350
        assert not trip["cidade_origem"]
        assert not trip["cidade_destino"]

        completed = service.complete_km_end(trip["id"], 120500)
        assert completed["status_fluxo"] == "completo"
        assert completed["km_fim"] == 120500
        assert completed["km_rodado"] == 150
        assert completed["quilometragem"] == 150


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
