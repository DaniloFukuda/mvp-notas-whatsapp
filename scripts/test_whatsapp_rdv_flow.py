import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def main() -> None:
    original_service = api_whatsapp.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv_whatsapp_test.db")
            api_whatsapp.rdv_service = service
            api_whatsapp.clear_rdv_sessions()

            collaborator = service.get_collaborator_by_phone("5500000000001")
            assert collaborator is not None
            sender = collaborator["telefone_whatsapp"]

            greeting = api_whatsapp.handle_rdv_text_message(sender, "oi")
            assert greeting is not None
            assert "Ciclus Agro - RDV por WhatsApp" in greeting
            assert collaborator["nome"] in greeting

            sent_messages = []
            original_download = api_whatsapp.download_media
            original_sender = api_whatsapp.send_whatsapp_text
            original_message_check = api_whatsapp._was_whatsapp_message_processed
            original_image_check = api_whatsapp._was_whatsapp_image_processed_for_sender
            try:
                api_whatsapp.download_media = (
                    lambda media_id, destination: Path(temp_dir) / "comprovante_teste.jpg"
                )
                api_whatsapp.send_whatsapp_text = (
                    lambda to, message: sent_messages.append((to, message))
                )
                api_whatsapp._was_whatsapp_message_processed = lambda message_id: False
                api_whatsapp._was_whatsapp_image_processed_for_sender = (
                    lambda image_sha256, phone: False
                )
                api_whatsapp._handle_whatsapp_message(
                    {
                        "from": sender,
                        "id": "wamid.flow.test",
                        "timestamp": "1781001000",
                        "type": "image",
                        "image": {
                            "id": "media.test",
                            "mime_type": "image/jpeg",
                            "sha256": "sha256-test",
                        },
                    }
                )
            finally:
                api_whatsapp.download_media = original_download
                api_whatsapp.send_whatsapp_text = original_sender
                api_whatsapp._was_whatsapp_message_processed = original_message_check
                api_whatsapp._was_whatsapp_image_processed_for_sender = original_image_check

            assert sent_messages
            assert sent_messages[0][0] == sender
            assert "informe o valor" in sent_messages[0][1].lower()
            expense = service.get_by_whatsapp_message_id("wamid.flow.test")
            assert expense is not None
            assert expense["colaborador_id"] == collaborator["id"]
            assert expense["colaborador"] == "Danilo"
            assert expense["telefone_origem"] == sender
            assert expense["tipo_entrada"] == "imagem"
            assert expense["status_fluxo"] == "aguardando_valor"
            assert expense["caminho_arquivo"].endswith("comprovante_teste.jpg")

            value_reply = api_whatsapp.handle_rdv_text_message(sender, "89,90")
            assert value_reply is not None
            assert "categoria" in value_reply.lower()
            after_value = service.get_expense(expense["id"])
            assert after_value is not None
            assert after_value["valor"] == 89.9
            assert after_value["status_fluxo"] == "aguardando_categoria"

            category_reply = api_whatsapp.handle_rdv_text_message(sender, "1")
            assert category_reply is not None
            assert "registrado com sucesso" in category_reply.lower()
            completed = service.get_expense(expense["id"])
            assert completed is not None
            assert completed["categoria"] == "combustivel"
            assert completed["status_fluxo"] == "completo"
            assert completed["status_revisao"] == "pendente"

            unknown_sender = "5599999999999"
            unknown_reply = api_whatsapp.handle_rdv_text_message(
                unknown_sender,
                "oi",
            )
            assert unknown_reply is not None
            assert "nao esta cadastrado" in unknown_reply.lower()
            assert service.get_open_launch_by_phone(unknown_sender) is None

            message_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": sender,
                                            "id": "wamid.text.test",
                                            "type": "text",
                                            "text": {"body": "resumo"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
            status_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "statuses": [
                                        {
                                            "id": "wamid.outgoing.test",
                                            "status": "delivered",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
            extracted = api_whatsapp._extract_messages(message_payload)
            assert len(extracted) == 1
            assert extracted[0]["from"] == sender
            assert api_whatsapp._extract_text(extracted[0]) == "resumo"
            assert api_whatsapp._extract_messages(status_payload) == []
            assert api_whatsapp._count_status_events(status_payload) == 1
    finally:
        api_whatsapp.clear_rdv_sessions()
        api_whatsapp.rdv_service = original_service

    print("OK: fluxo comprovante -> valor -> categoria -> completo validado.")


if __name__ == "__main__":
    main()
