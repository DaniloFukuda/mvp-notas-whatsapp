import sys
import tempfile
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def main() -> None:
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv_clear_km_test.db")
            api_whatsapp.rdv_service = service

            collaborator = service.get_collaborator_by_phone("5500000000001")
            assert collaborator is not None
            sender = collaborator["telefone_whatsapp"]
            collaborator_count = len(service.list_collaborators(active_only=False))

            fuel = service.register_manual_expense(
                colaborador_id=collaborator["id"],
                data_despesa=date.today().isoformat(),
                categoria="combustivel",
                valor=250,
                fornecedor="Posto Teste",
            )
            food = service.register_manual_expense(
                colaborador_id=collaborator["id"],
                data_despesa=date.today().isoformat(),
                categoria="alimentacao",
                valor=45,
                fornecedor="Restaurante Teste",
            )
            receipt = service.create_whatsapp_receipt(
                collaborator_id=collaborator["id"],
                phone=sender,
                input_type="imagem",
                file_path="comprovante_teste.jpg",
                whatsapp_message_id="wamid.clear.km.receipt",
                analysis={
                    "valor_detectado": 80,
                    "origem_valor": "ocr",
                },
            )
            service.complete_launch_category(receipt["id"], "alimentacao")

            _complete_trip(sender, "1000", "1120")
            assert _km_launches(service)

            warning = api_whatsapp.handle_rdv_text_message(
                sender,
                "limpar km",
            )
            assert warning == api_whatsapp.KM_CLEAR_WARNING
            assert _km_launches(service)

            assert api_whatsapp.handle_rdv_text_message(
                sender,
                "LIMPAR QUILOMETRAGENS",
            ) == api_whatsapp.KM_CLEAR_WARNING
            assert _km_launches(service)

            assert api_whatsapp.handle_rdv_text_message(
                sender,
                "km inicio 2000",
            ).startswith("Viagem iniciada com sucesso.")
            assert service.get_open_km_launch_by_phone(sender) is not None

            result = api_whatsapp.handle_rdv_text_message(
                sender,
                "CONFIRMAR LIMPAR KM",
            )
            assert result == api_whatsapp.KM_CLEAR_SUCCESS
            assert not _km_launches(service)
            assert service.get_open_km_launch_by_phone(sender) is None
            assert service.clear_km_trips() == 0

            status = api_whatsapp.handle_rdv_text_message(sender, "status km")
            assert status is not None
            assert "nenhuma viagem em andamento" in (
                api_whatsapp._normalize_caption(status)
            )

            summary = api_whatsapp.handle_rdv_text_message(sender, "meu resumo")
            assert summary is not None
            assert "KM rodado: 0 km" in summary
            assert "Viagens em aberto: 0" in summary

            assert (
                len(service.list_collaborators(active_only=False))
                == collaborator_count
            )
            remaining_ids = {launch["id"] for launch in service.list_launches()}
            assert fuel["id"] in remaining_ids
            assert food["id"] in remaining_ids
            assert receipt["id"] in remaining_ids
            assert service.get_by_whatsapp_message_id(
                "wamid.clear.km.receipt"
            ) is not None
            assert service.get_expense(fuel["id"])["categoria"] == "combustivel"
            assert service.get_expense(food["id"])["categoria"] == "alimentacao"
    finally:
        api_whatsapp.rdv_service = original_service

    print("OK: comando de limpeza de quilometragens RDV validado.")


def _complete_trip(sender: str, start: str, end: str) -> None:
    api_whatsapp.handle_rdv_text_message(sender, f"km inicio {start}")
    api_whatsapp.handle_rdv_text_message(sender, f"km termino {end}")


def _km_launches(service: RDVService) -> list[dict]:
    return [
        launch
        for launch in service.list_launches()
        if launch.get("observacao")
        in {
            "quilometragem registrada pelo WhatsApp",
            "viagem cancelada pelo WhatsApp",
        }
        or launch.get("km_inicio") is not None
        or launch.get("km_fim") is not None
        or launch.get("km_rodado") is not None
        or launch.get("quilometragem") is not None
    ]


if __name__ == "__main__":
    main()
