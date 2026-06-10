import os
import logging
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService


def main() -> None:
    original_service = api_whatsapp.rdv_service
    original_document_sender = api_whatsapp.send_whatsapp_document
    original_text_sender = api_whatsapp.send_whatsapp_text
    original_requests_module = api_whatsapp._requests_module
    original_env = {
        key: os.environ.get(key)
        for key in (
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_GRAPH_API_VERSION",
            "BASE_PUBLIC_URL",
        )
    }
    xlsx_before = set(PROJECT_ROOT.rglob("*.xlsx"))

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv_whatsapp_excel_test.db")
            api_whatsapp.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000001")
            assert collaborator is not None
            sender = collaborator["telefone_whatsapp"]
            for command in (
                "planilha",
                "excel",
                "relatorio",
                "relatório",
                "relatorio semanal",
                "relatório semanal",
                "rdv",
            ):
                assert api_whatsapp._is_rdv_excel_command(command)

            sent_documents = []
            sent_texts = []
            api_whatsapp.send_whatsapp_document = (
                lambda to, content, filename, caption, mime_type: sent_documents.append(
                    {
                        "to": to,
                        "content": content,
                        "filename": filename,
                        "caption": caption,
                        "mime_type": mime_type,
                    }
                )
            )
            api_whatsapp.send_whatsapp_text = (
                lambda to, message: sent_texts.append((to, message))
            )

            for index, command in enumerate(("planilha", "excel"), start=1):
                api_whatsapp._handle_whatsapp_message(
                    {
                        "from": sender,
                        "id": f"wamid.excel.command.{index}",
                        "type": "text",
                        "text": {"body": command},
                    }
                )

            assert len(sent_documents) == 2
            for document in sent_documents:
                assert document["to"] == sender
                assert document["content"].startswith(b"PK")
                assert document["filename"] == "rdv_ciclus_relatorio_semanal.xlsx"
                assert document["mime_type"] == (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                )
                assert "planilha semanal" in document["caption"].lower()
            assert sent_texts == []

            attempts_before = len(sent_documents)
            api_whatsapp._handle_whatsapp_message(
                {
                    "from": "5599999999999",
                    "id": "wamid.excel.unauthorized",
                    "type": "text",
                    "text": {"body": "planilha"},
                }
            )
            assert len(sent_documents) == attempts_before
            assert "nao esta cadastrado" in sent_texts[-1][1].lower()

            os.environ["BASE_PUBLIC_URL"] = "https://painel.exemplo.invalid"
            api_whatsapp.send_whatsapp_document = _raise_document_error
            logging.disable(logging.CRITICAL)
            try:
                api_whatsapp._handle_whatsapp_message(
                    {
                        "from": sender,
                        "id": "wamid.excel.failure",
                        "type": "text",
                        "text": {"body": "relatório semanal"},
                    }
                )
            finally:
                logging.disable(logging.NOTSET)
            fallback = sent_texts[-1][1]
            assert "nao consegui enviar o arquivo" in fallback.lower()
            assert (
                "https://painel.exemplo.invalid/ciclus/rdv/"
                "relatorio-semanal.xlsx"
            ) in fallback
            assert str(PROJECT_ROOT) not in fallback

            fake_requests = _FakeRequests()
            api_whatsapp._requests_module = lambda: fake_requests
            os.environ["WHATSAPP_ACCESS_TOKEN"] = "token-ficticio"
            os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "phone-id-ficticio"
            os.environ["WHATSAPP_GRAPH_API_VERSION"] = "v99.0"
            api_whatsapp.send_whatsapp_document = original_document_sender
            api_whatsapp.send_whatsapp_document(
                sender,
                b"PK-conteudo-xlsx-ficticio",
            )
            assert len(fake_requests.calls) == 2
            upload_call, send_call = fake_requests.calls
            assert upload_call["url"].endswith(
                "/v99.0/phone-id-ficticio/media"
            )
            assert upload_call["files"]["file"][0].endswith(".xlsx")
            assert upload_call["files"]["file"][2] == api_whatsapp.RDV_EXCEL_MIME_TYPE
            assert send_call["url"].endswith(
                "/v99.0/phone-id-ficticio/messages"
            )
            assert send_call["json"]["type"] == "document"
            assert send_call["json"]["document"]["id"] == "media-ficticia"

            status_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "statuses": [
                                        {
                                            "id": "wamid.outgoing.excel",
                                            "status": "delivered",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
            assert api_whatsapp._extract_messages(status_payload) == []
            assert api_whatsapp._count_status_events(status_payload) == 1
    finally:
        api_whatsapp.rdv_service = original_service
        api_whatsapp.send_whatsapp_document = original_document_sender
        api_whatsapp.send_whatsapp_text = original_text_sender
        api_whatsapp._requests_module = original_requests_module
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert set(PROJECT_ROOT.rglob("*.xlsx")) == xlsx_before
    print("OK: envio do Excel semanal do RDV pelo WhatsApp validado.")


def _raise_document_error(*args, **kwargs) -> None:
    raise RuntimeError("falha simulada no envio")


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRequests:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if url.endswith("/media"):
            return _FakeResponse(200, {"id": "media-ficticia"})
        return _FakeResponse(200, {"messages": [{"id": "wamid.ficticia"}]})


if __name__ == "__main__":
    main()
