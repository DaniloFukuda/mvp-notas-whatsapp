import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_receipt_analysis_service import RDVReceiptAnalysisResult
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
            assert "Digite km para registrar inicio/fim de viagem." in greeting

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
            initial_message = api_whatsapp._normalize_caption(sent_messages[0][1])
            assert "informar o valor manualmente" in initial_message
            assert "nao consegui detectar" in initial_message
            assert "nova foto mais nitida" in initial_message
            assert "qr code visivel" in initial_message
            assert "exemplo: 64,00" in initial_message
            expense = service.get_by_whatsapp_message_id("wamid.flow.test")
            assert expense is not None
            assert expense["colaborador_id"] == collaborator["id"]
            assert expense["colaborador"] == "Danilo"
            assert expense["telefone_origem"] == sender
            assert expense["tipo_entrada"] == "imagem"
            assert expense["status_fluxo"] == "aguardando_valor"
            assert expense["falha_leitura"] == 1
            assert expense["motivo_revisao"]
            assert expense["caminho_arquivo"].endswith("comprovante_teste.jpg")

            value_reply = api_whatsapp.handle_rdv_text_message(sender, "89,90")
            assert value_reply is not None
            assert "categoria" in value_reply.lower()
            assert "valor registrado manualmente: r$ 89,90" in value_reply.lower()
            assert value_reply.splitlines()[0] == (
                "Valor registrado manualmente: R$ 89,90. Qual a categoria?"
            )
            after_value = service.get_expense(expense["id"])
            assert after_value is not None
            assert after_value["valor"] == 89.9
            assert after_value["origem_valor"] == "manual"
            assert after_value["falha_leitura"] == 1
            assert after_value["motivo_revisao"] == (
                "valor informado manualmente após falha de leitura"
            )
            assert after_value["status_fluxo"] == "aguardando_categoria"

            category_reply = api_whatsapp.handle_rdv_text_message(sender, "1")
            assert category_reply is not None
            assert "registrado com sucesso" in category_reply.lower()
            completed = service.get_expense(expense["id"])
            assert completed is not None
            assert completed["categoria"] == "combustivel"
            assert completed["status_fluxo"] == "completo"
            assert completed["status_revisao"] == "pendente"
            assert "status: completo." in category_reply.lower()
            assert "valor informado manualmente" in category_reply.lower()
            assert "pendente de revisao" not in category_reply.lower()
            assert (
                "para receber a planilha semanal, envie: planilha."
                in category_reply.lower()
            )

            retry_collaborator = service.get_collaborator_by_phone("5500000000002")
            assert retry_collaborator is not None
            retry_sender = retry_collaborator["telefone_whatsapp"]
            original_analyzer = api_whatsapp.rdv_receipt_analysis_service
            try:
                api_whatsapp.rdv_receipt_analysis_service = _NoValueReceiptAnalyzer()
                retry_initial = api_whatsapp._register_received_media_as_rdv(
                    sender_phone=retry_sender,
                    caminho_arquivo=str(Path(temp_dir) / "nfce_sem_valor_1.jpg"),
                    whatsapp_message_id="wamid.flow.retry.initial",
                    message_type="image",
                    received_at="2026-06-09T14:00:00",
                )
                retry_messages = []
                original_download = api_whatsapp.download_media
                original_sender = api_whatsapp.send_whatsapp_text
                original_message_check = api_whatsapp._was_whatsapp_message_processed
                original_image_check = (
                    api_whatsapp._was_whatsapp_image_processed_for_sender
                )
                api_whatsapp.download_media = (
                    lambda media_id, destination: Path(destination)
                )
                api_whatsapp.send_whatsapp_text = (
                    lambda to, message: retry_messages.append((to, message))
                )
                api_whatsapp._was_whatsapp_message_processed = lambda message_id: False
                api_whatsapp._was_whatsapp_image_processed_for_sender = (
                    lambda image_sha256, phone: False
                )
                api_whatsapp._handle_whatsapp_message(
                    _image_message(
                        retry_sender,
                        "wamid.flow.retry.failed",
                        "media.retry.failed",
                        "sha256-retry-failed",
                    )
                )
                retry_failed = service.get_by_whatsapp_message_id(
                    "wamid.flow.retry.failed"
                )
                assert retry_failed is not None
                assert retry_failed["id"] == retry_initial["id"]
                assert retry_failed["status_fluxo"] == "aguardando_valor"
                retry_message = api_whatsapp._normalize_caption(
                    retry_messages[-1][1]
                )
                assert "ainda nao consegui detectar" in retry_message
                assert "foto mais nitida" in retry_message
                assert service.get_by_whatsapp_message_id(
                    "wamid.flow.retry.failed"
                )["id"] == retry_initial["id"]

                api_whatsapp.rdv_receipt_analysis_service = _DetectedReceiptAnalyzer()
                api_whatsapp._handle_whatsapp_message(
                    _image_message(
                        retry_sender,
                        "wamid.flow.retry.detected",
                        "media.retry.detected",
                        "sha256-retry-detected",
                    )
                )
                detected = service.get_by_whatsapp_message_id(
                    "wamid.flow.retry.detected"
                )
                assert detected is not None
            finally:
                api_whatsapp.rdv_receipt_analysis_service = original_analyzer
                api_whatsapp.download_media = original_download
                api_whatsapp.send_whatsapp_text = original_sender
                api_whatsapp._was_whatsapp_message_processed = original_message_check
                api_whatsapp._was_whatsapp_image_processed_for_sender = (
                    original_image_check
                )

            assert detected["id"] == retry_initial["id"]
            assert detected["valor"] == 64.0
            assert detected["valor_detectado"] == 64.0
            assert detected["origem_valor"] == "ocr"
            assert detected["falha_leitura"] == 0
            assert detected["status_fluxo"] == "aguardando_categoria"
            detected_reply = api_whatsapp._rdv_received_message(detected)
            assert "detectei o valor r$ 64,00" in detected_reply.lower()
            assert "categoria" in detected_reply.lower()
            assert "informe o valor" not in detected_reply.lower()

            detected_category_reply = api_whatsapp.handle_rdv_text_message(
                retry_sender,
                "2",
            )
            assert detected_category_reply is not None
            assert "registrado com sucesso" in detected_category_reply.lower()
            detected_completed = service.get_expense(detected["id"])
            assert detected_completed is not None
            assert detected_completed["categoria"] == "alimentacao"
            assert detected_completed["status_fluxo"] == "completo"
            assert detected_completed["status_revisao"] == "aprovado"
            assert detected_completed["falha_leitura"] == 0
            assert "status: completo." in detected_category_reply.lower()
            assert "valor informado manualmente" not in detected_category_reply.lower()
            assert "pendente de revisao" not in detected_category_reply.lower()
            assert (
                "para receber a planilha semanal, envie: planilha."
                in detected_category_reply.lower()
            )

            assert api_whatsapp._parse_km_value("120350") == 120350
            assert api_whatsapp._parse_km_value("120.350") == 120350
            assert api_whatsapp._parse_km_value("120350 km") == 120350
            assert api_whatsapp._parse_km_value("120350,5 km") == 120350.5

            km_reply = api_whatsapp.handle_rdv_text_message(sender, "km")
            assert km_reply == "Saindo de onde?"
            km_pending = service.get_open_launch_by_phone(sender)
            assert km_pending is not None
            assert km_pending["status_fluxo"] == "aguardando_km_origem"

            assert (
                api_whatsapp.handle_rdv_text_message(sender, "Ribeirao Preto")
                == "Indo para onde?"
            )
            assert (
                api_whatsapp.handle_rdv_text_message(sender, "Sertaozinho")
                == "Qual a quilometragem inicial do carro?"
            )
            assert (
                api_whatsapp.handle_rdv_text_message(sender, "120.350 km")
                == "Qual a quilometragem final do carro?"
            )

            invalid_end_reply = api_whatsapp.handle_rdv_text_message(
                sender,
                "120.300",
            )
            assert "nao pode ser menor" in invalid_end_reply.lower()
            still_pending = service.get_open_launch_by_phone(sender)
            assert still_pending is not None
            assert still_pending["status_fluxo"] == "aguardando_km_fim"

            completed_km_reply = api_whatsapp.handle_rdv_text_message(
                sender,
                "120500 km",
            )
            assert completed_km_reply is not None
            assert "Quilometragem registrada com sucesso." in completed_km_reply
            assert "Trajeto: Ribeirao Preto \u2192 Sertaozinho" in completed_km_reply
            assert "KM inicial: 120350" in completed_km_reply
            assert "KM final: 120500" in completed_km_reply
            assert "KM rodado: 150 km" in completed_km_reply

            completed_km = service.get_expense(km_pending["id"])
            assert completed_km is not None
            assert completed_km["cidade_origem"] == "Ribeirao Preto"
            assert completed_km["cidade_destino"] == "Sertaozinho"
            assert completed_km["km_inicio"] == 120350
            assert completed_km["km_fim"] == 120500
            assert completed_km["km_rodado"] == 150
            assert completed_km["quilometragem"] == 150
            assert completed_km["status_fluxo"] == "completo"
            assert completed_km["status_revisao"] == "pendente"
            assert service.get_open_launch_by_phone(sender) is None

            weekly_summary = api_whatsapp.handle_rdv_text_message(
                sender,
                "meu resumo",
            )
            assert weekly_summary is not None
            assert "KM rodado: 150 km" in weekly_summary

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

    print("OK: fluxos de comprovante e quilometragem pelo WhatsApp validados.")


class _DetectedReceiptAnalyzer:
    def analyze_file(self, file_path: str) -> RDVReceiptAnalysisResult:
        return RDVReceiptAnalysisResult(
            valor_detectado=64.0,
            data_detectada="2026-05-13",
            fornecedor_detectado="MERCADO FICTICIO LTDA",
            chave_acesso="1" * 44,
            origem_valor="ocr",
            confidence=0.85,
            reasons=["valor_encontrado_ocr"],
        )


class _NoValueReceiptAnalyzer:
    def analyze_file(self, file_path: str) -> RDVReceiptAnalysisResult:
        return RDVReceiptAnalysisResult(
            confidence=0.0,
            reasons=["valor_nao_detectado"],
        )


def _image_message(
    sender: str,
    message_id: str,
    media_id: str,
    sha256: str,
) -> dict:
    return {
        "from": sender,
        "id": message_id,
        "timestamp": "1781001000",
        "type": "image",
        "image": {
            "id": media_id,
            "mime_type": "image/jpeg",
            "sha256": sha256,
        },
    }


if __name__ == "__main__":
    main()
