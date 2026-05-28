import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from core.database import parse_nfce_qr_data, save_processed_document


CSV_PATH = "output/documentos_processados.csv"
CSV_COLUMNS = [
    "data_processamento",
    "tipo_documento",
    "caminho_imagem",
    "sucesso",
    "mensagem",
    "dados_extraidos",
    "data_documento",
    "fornecedor",
    "valor",
    "categoria",
    "responsavel",
    "observacao",
    "document_kind",
    "hora_documento",
    "favorecido",
    "id_transacao",
    "comentario",
    "conta_origem",
    "texto_extraido",
    "needs_review",
    "whatsapp_message_id",
    "whatsapp_media_id",
    "whatsapp_image_sha256",
    "whatsapp_timestamp",
    "data_hora_recebimento",
]


def save_processing_result(
    tipo_documento: str,
    caminho_imagem: str,
    sucesso: bool,
    mensagem: str,
    dados_extraidos: str = "",
    data_documento: str = "",
    fornecedor: str = "",
    valor: str = "",
    categoria: str = "",
    responsavel: str = "",
    observacao: str = "",
    document_kind: str = "",
    hora_documento: str = "",
    favorecido: str = "",
    id_transacao: str = "",
    comentario: str = "",
    conta_origem: str = "",
    texto_extraido: str = "",
    needs_review: bool = False,
    whatsapp_message_id: str = "",
    whatsapp_media_id: str = "",
    whatsapp_image_sha256: str = "",
    whatsapp_timestamp: str = "",
    data_hora_recebimento: str = "",
) -> None:
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    _ensure_csv_columns()
    file_exists = os.path.exists(CSV_PATH)
    data_processamento = datetime.now().isoformat(timespec="seconds")
    valor_total = _resolve_valor_total(dados_extraidos, valor)
    record = {
        "data_processamento": data_processamento,
        "tipo_documento": tipo_documento,
        "caminho_imagem": caminho_imagem,
        "caminho_arquivo": caminho_imagem,
        "sucesso": sucesso,
        "mensagem": mensagem,
        "dados_extraidos": dados_extraidos,
        "valor_total": valor_total,
        "data_documento": data_documento,
        "fornecedor": fornecedor,
        "categoria": categoria,
        "responsavel": responsavel,
        "observacao": observacao,
        "document_kind": document_kind,
        "hora_documento": hora_documento,
        "favorecido": favorecido,
        "id_transacao": id_transacao,
        "comentario": comentario,
        "conta_origem": conta_origem,
        "texto_extraido": texto_extraido,
        "needs_review": needs_review,
        "whatsapp_message_id": whatsapp_message_id,
        "whatsapp_media_id": whatsapp_media_id,
        "whatsapp_image_sha256": whatsapp_image_sha256,
        "whatsapp_timestamp": whatsapp_timestamp,
        "data_hora_recebimento": data_hora_recebimento,
        "status_conferencia": "pendente",
    }

    try:
        save_processed_document(record)
    except sqlite3.IntegrityError as exc:
        if record["whatsapp_message_id"] or record["whatsapp_image_sha256"]:
            print("Documento WhatsApp duplicado ignorado pelo SQLite.")
            return
        print(f"Erro ao salvar documento no SQLite: {exc}")
    except Exception as exc:
        print(f"Erro ao salvar documento no SQLite: {exc}")

    with open(CSV_PATH, mode="a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "data_processamento": record["data_processamento"],
                "tipo_documento": record["tipo_documento"],
                "caminho_imagem": record["caminho_imagem"],
                "sucesso": record["sucesso"],
                "mensagem": record["mensagem"],
                "dados_extraidos": record["dados_extraidos"],
                "data_documento": record["data_documento"],
                "fornecedor": record["fornecedor"],
                "valor": record["valor_total"],
                "categoria": record["categoria"],
                "responsavel": record["responsavel"],
                "observacao": record["observacao"],
                "document_kind": record["document_kind"],
                "hora_documento": record["hora_documento"],
                "favorecido": record["favorecido"],
                "id_transacao": record["id_transacao"],
                "comentario": record["comentario"],
                "conta_origem": record["conta_origem"],
                "texto_extraido": record["texto_extraido"],
                "needs_review": record["needs_review"],
                "whatsapp_message_id": record["whatsapp_message_id"],
                "whatsapp_media_id": record["whatsapp_media_id"],
                "whatsapp_image_sha256": record["whatsapp_image_sha256"],
                "whatsapp_timestamp": record["whatsapp_timestamp"],
                "data_hora_recebimento": record["data_hora_recebimento"],
            }
        )


def _resolve_valor_total(dados_extraidos: str, valor_manual: str) -> str:
    nfce_data = parse_nfce_qr_data(dados_extraidos)
    if nfce_data["valor_total"] is not None:
        return f"{nfce_data['valor_total']:.2f}"

    valor_normalizado = _normalize_decimal_text(valor_manual)
    return valor_normalizado


def _normalize_decimal_text(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""

    try:
        return f"{float(value.replace(',', '.')):.2f}"
    except ValueError:
        return value


def _ensure_csv_columns() -> None:
    csv_path = Path(CSV_PATH)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return

    with csv_path.open(mode="r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        existing_columns = reader.fieldnames or []
        if all(column in existing_columns for column in CSV_COLUMNS):
            return

        rows = list(reader)

    with csv_path.open(mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
