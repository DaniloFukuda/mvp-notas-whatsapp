import tempfile
from pathlib import Path

from services.rdv_service import RDVService


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
