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
            api_whatsapp.rdv_service = RDVService(Path(temp_dir) / "rdv_whatsapp_test.db")
            api_whatsapp.clear_rdv_sessions()
            sender = "5511999999999"

            assert "Ciclus Agro - RDV por WhatsApp" in api_whatsapp.handle_rdv_text_message(
                sender, "oi"
            )
            assert "Ciclus Agro - RDV por WhatsApp" in api_whatsapp.handle_rdv_text_message(
                sender, "ola"
            )
            assert "colaborador" in api_whatsapp.handle_rdv_text_message(sender, "1").lower()
            assert "categoria" in api_whatsapp.handle_rdv_text_message(sender, "4").lower()
            assert "valor" in api_whatsapp.handle_rdv_text_message(sender, "1").lower()
            assert "comprovante" in api_whatsapp.handle_rdv_text_message(
                sender, "89,90"
            ).lower()

            expense = api_whatsapp._register_received_media_as_rdv(
                sender_phone=sender,
                caminho_arquivo="data/documentos/uploads/whatsapp/comprovante_teste.jpg",
                whatsapp_message_id="wamid.flow.test",
            )
            assert expense["colaborador"] == "Danilo"
            assert expense["categoria"] == "combustivel"
            assert expense["valor"] == 89.9
            assert expense["status_revisao"] == "pendente"

            no_context = api_whatsapp._register_received_media_as_rdv(
                sender_phone="5511888888888",
                caminho_arquivo="data/documentos/uploads/whatsapp/sem_contexto.pdf",
                whatsapp_message_id="wamid.no.context",
            )
            assert no_context["colaborador"] == "Outro"
            assert no_context["categoria"] == "outro"
            assert no_context["observacao"] == "arquivo recebido sem contexto de RDV"

            summary = api_whatsapp.handle_rdv_text_message(sender, "3")
            assert "Resumo da semana" in summary
            assert "Despesas: 2" in summary

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
                                            "text": {"body": "menu"},
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
            assert api_whatsapp._extract_text(extracted[0]) == "menu"
            assert api_whatsapp._extract_messages(status_payload) == []
            assert api_whatsapp._count_status_events(status_payload) == 1

            sent_messages = []
            original_sender = api_whatsapp.send_whatsapp_text
            try:
                api_whatsapp.send_whatsapp_text = (
                    lambda to, message: sent_messages.append((to, message))
                )
                api_whatsapp._handle_whatsapp_message(extracted[0])
            finally:
                api_whatsapp.send_whatsapp_text = original_sender
            assert sent_messages
            assert sent_messages[0][0] == sender
            assert "Ciclus Agro - RDV por WhatsApp" in sent_messages[0][1]
    finally:
        api_whatsapp.clear_rdv_sessions()
        api_whatsapp.rdv_service = original_service

    print("OK: fluxo WhatsApp RDV simulado com banco temporario.")


if __name__ == "__main__":
    main()
