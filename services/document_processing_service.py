from dataclasses import dataclass

from core.database import list_processed_documents
from core.nucleus import Nucleus


DOCUMENT_TYPE_CODES = {
    "1": "1",
    "nota": "1",
    "nf": "1",
    "nfc-e": "1",
    "nfce": "1",
    "nota_fiscal": "1",
    "nota fiscal": "1",
    "2": "2",
    "recibo": "2",
    "comprovante": "2",
    "recibo_comprovante": "2",
    "recibo/comprovante": "2",
}


@dataclass
class DocumentProcessingResult:
    sucesso: bool
    mensagem: str
    tipo_documento: str
    fornecedor: str = ""
    valor_total: str = ""
    data_documento: str = ""
    status_conferencia: str = ""
    needs_review: bool = False
    id_documento: int | None = None


def process_document_file(
    tipo_documento: str,
    caminho_arquivo: str,
    origem: str = "web",
    telefone_remetente: str = "",
    whatsapp_message_id: str = "",
    whatsapp_media_id: str = "",
    whatsapp_image_sha256: str = "",
    whatsapp_timestamp: str = "",
    data_hora_recebimento: str = "",
) -> DocumentProcessingResult:
    document_code = _normalize_document_type(tipo_documento)
    metadata = _build_metadata(
        origem=origem,
        telefone_remetente=telefone_remetente,
        whatsapp_message_id=whatsapp_message_id,
        whatsapp_media_id=whatsapp_media_id,
        whatsapp_image_sha256=whatsapp_image_sha256,
        whatsapp_timestamp=whatsapp_timestamp,
        data_hora_recebimento=data_hora_recebimento,
    )

    result = Nucleus().process_document(
        document_type=document_code,
        image_path=caminho_arquivo,
        metadata=metadata,
    )
    saved_document = _find_saved_document(caminho_arquivo)
    saved_type = saved_document.get("tipo_documento") if saved_document else ""

    return DocumentProcessingResult(
        sucesso=result.success,
        mensagem=result.message,
        tipo_documento=str(saved_type or _canonical_document_type(document_code)),
        fornecedor=str((saved_document or {}).get("fornecedor") or ""),
        valor_total=_format_value((saved_document or {}).get("valor_total")),
        data_documento=str((saved_document or {}).get("data_documento") or ""),
        status_conferencia=str((saved_document or {}).get("status_conferencia") or "pendente"),
        needs_review=bool((saved_document or {}).get("needs_review")),
        id_documento=(saved_document or {}).get("id"),
    )


def _normalize_document_type(tipo_documento: str) -> str:
    normalized = str(tipo_documento or "").strip().lower()
    return DOCUMENT_TYPE_CODES.get(normalized, normalized)


def _canonical_document_type(document_code: str) -> str:
    if document_code == "1":
        return "nota_fiscal"
    if document_code == "2":
        return "recibo_comprovante"
    return "tipo_invalido"


def _build_metadata(
    origem: str,
    telefone_remetente: str,
    whatsapp_message_id: str,
    whatsapp_media_id: str,
    whatsapp_image_sha256: str,
    whatsapp_timestamp: str,
    data_hora_recebimento: str,
) -> dict:
    if (
        origem != "whatsapp"
        and not telefone_remetente
        and not whatsapp_message_id
        and not whatsapp_media_id
        and not whatsapp_image_sha256
        and not whatsapp_timestamp
        and not data_hora_recebimento
    ):
        return {}

    notes = [f"origem: {origem}"]
    if telefone_remetente:
        notes.append(f"telefone_remetente: {telefone_remetente}")

    metadata = {
        "responsavel": origem,
        "observacao": " | ".join(notes),
    }
    if whatsapp_message_id:
        metadata["whatsapp_message_id"] = whatsapp_message_id
    if whatsapp_media_id:
        metadata["whatsapp_media_id"] = whatsapp_media_id
    if whatsapp_image_sha256:
        metadata["whatsapp_image_sha256"] = whatsapp_image_sha256
    if whatsapp_timestamp:
        metadata["whatsapp_timestamp"] = whatsapp_timestamp
    if data_hora_recebimento:
        metadata["data_hora_recebimento"] = data_hora_recebimento

    return metadata


def _find_saved_document(caminho_arquivo: str) -> dict | None:
    for document in list_processed_documents(limit=100, include_invalid=True):
        if str(document.get("caminho_arquivo") or "") == caminho_arquivo:
            return document
    return None


def _format_value(value: object) -> str:
    if value in (None, ""):
        return ""

    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)
