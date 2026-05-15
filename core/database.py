import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DB_PATH = Path("data/app.db")

TABLE_COLUMNS = [
    "id",
    "data_processamento",
    "tipo_documento",
    "caminho_arquivo",
    "sucesso",
    "mensagem",
    "dados_extraidos",
    "chave_acesso",
    "url_consulta",
    "valor_total",
    "data_documento",
    "fornecedor",
    "categoria",
    "responsavel",
    "observacao",
    "status_conferencia",
    "document_kind",
    "hora_documento",
    "favorecido",
    "id_transacao",
    "comentario",
    "conta_origem",
    "texto_extraido",
    "needs_review",
]


def init_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documentos_processados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_processamento TEXT,
                tipo_documento TEXT,
                caminho_arquivo TEXT,
                sucesso INTEGER,
                mensagem TEXT,
                dados_extraidos TEXT,
                chave_acesso TEXT,
                url_consulta TEXT,
                valor_total REAL,
                data_documento TEXT,
                fornecedor TEXT,
                categoria TEXT,
                responsavel TEXT,
                observacao TEXT,
                status_conferencia TEXT,
                document_kind TEXT,
                hora_documento TEXT,
                favorecido TEXT,
                id_transacao TEXT,
                comentario TEXT,
                conta_origem TEXT,
                texto_extraido TEXT,
                needs_review INTEGER
            )
            """
        )
        _ensure_columns(connection)
        connection.commit()


def _ensure_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(documentos_processados)").fetchall()
    }
    required_columns = {
        "data_processamento": "TEXT",
        "tipo_documento": "TEXT",
        "caminho_arquivo": "TEXT",
        "sucesso": "INTEGER",
        "mensagem": "TEXT",
        "dados_extraidos": "TEXT",
        "chave_acesso": "TEXT",
        "url_consulta": "TEXT",
        "valor_total": "REAL",
        "data_documento": "TEXT",
        "fornecedor": "TEXT",
        "categoria": "TEXT",
        "responsavel": "TEXT",
        "observacao": "TEXT",
        "status_conferencia": "TEXT",
        "document_kind": "TEXT",
        "hora_documento": "TEXT",
        "favorecido": "TEXT",
        "id_transacao": "TEXT",
        "comentario": "TEXT",
        "conta_origem": "TEXT",
        "texto_extraido": "TEXT",
        "needs_review": "INTEGER",
    }

    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            connection.execute(
                f"ALTER TABLE documentos_processados ADD COLUMN {column_name} {column_type}"
            )


def parse_nfce_qr_data(dados_extraidos: str) -> dict:
    structured_data = _parse_structured_data(dados_extraidos)
    if structured_data:
        qr_code_data = (
            structured_data.get("qr_code_data")
            or structured_data.get("url_consulta")
            or structured_data.get("qr")
            or ""
        )
        if qr_code_data:
            return parse_nfce_qr_data(str(qr_code_data))

    if not dados_extraidos or not dados_extraidos.startswith(("http://", "https://")):
        return {
            "url_consulta": "",
            "chave_acesso": "",
            "valor_total": None,
        }

    parsed_url = urlparse(dados_extraidos)
    query_params = parse_qs(parsed_url.query)
    p_values = query_params.get("p") or []
    p_value = p_values[0] if p_values else ""
    parts = p_value.split("|") if p_value else []

    return {
        "url_consulta": dados_extraidos,
        "chave_acesso": parts[0] if len(parts) >= 1 else "",
        "valor_total": _to_float(parts[4]) if len(parts) >= 5 else None,
    }


def save_processed_document(record: dict) -> None:
    init_database()

    dados_extraidos = str(record.get("dados_extraidos") or "")
    structured_data = _parse_structured_data(dados_extraidos)
    ocr_data = structured_data.get("ocr") if isinstance(structured_data.get("ocr"), dict) else {}
    nfce_data = parse_nfce_qr_data(dados_extraidos)
    record_value_total = _to_float(record.get("valor_total"))
    valor_total = nfce_data["valor_total"]
    if valor_total is None:
        valor_total = record_value_total
    if valor_total is None:
        valor_total = _to_float(structured_data.get("valor_total"))
    if valor_total is None:
        valor_total = _to_float(ocr_data.get("valor_total"))

    data = {
        "data_processamento": record.get("data_processamento") or "",
        "tipo_documento": record.get("tipo_documento") or "",
        "caminho_arquivo": record.get("caminho_arquivo")
        or record.get("caminho_imagem")
        or "",
        "sucesso": 1 if bool(record.get("sucesso")) else 0,
        "mensagem": record.get("mensagem") or "",
        "dados_extraidos": dados_extraidos,
        "chave_acesso": record.get("chave_acesso") or nfce_data["chave_acesso"],
        "url_consulta": record.get("url_consulta") or nfce_data["url_consulta"],
        "valor_total": valor_total,
        "data_documento": record.get("data_documento") or structured_data.get("data_documento") or ocr_data.get("data_documento") or "",
        "fornecedor": record.get("fornecedor") or "",
        "categoria": record.get("categoria") or "",
        "responsavel": record.get("responsavel") or "",
        "observacao": record.get("observacao") or "",
        "status_conferencia": record.get("status_conferencia") or "pendente",
        "document_kind": record.get("document_kind") or structured_data.get("document_kind") or "",
        "hora_documento": record.get("hora_documento") or structured_data.get("hora_documento") or ocr_data.get("hora_documento") or "",
        "favorecido": record.get("favorecido") or structured_data.get("favorecido") or "",
        "id_transacao": record.get("id_transacao") or structured_data.get("id_transacao") or "",
        "comentario": record.get("comentario") or structured_data.get("comentario") or "",
        "conta_origem": record.get("conta_origem") or structured_data.get("conta_origem") or "",
        "texto_extraido": record.get("texto_extraido") or structured_data.get("texto_extraido") or "",
        "needs_review": _to_int_bool(record.get("needs_review", structured_data.get("needs_review", False))),
    }

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO documentos_processados (
                data_processamento,
                tipo_documento,
                caminho_arquivo,
                sucesso,
                mensagem,
                dados_extraidos,
                chave_acesso,
                url_consulta,
                valor_total,
                data_documento,
                fornecedor,
                categoria,
                responsavel,
                observacao,
                status_conferencia,
                document_kind,
                hora_documento,
                favorecido,
                id_transacao,
                comentario,
                conta_origem,
                texto_extraido,
                needs_review
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["data_processamento"],
                data["tipo_documento"],
                data["caminho_arquivo"],
                data["sucesso"],
                data["mensagem"],
                data["dados_extraidos"],
                data["chave_acesso"],
                data["url_consulta"],
                data["valor_total"],
                data["data_documento"],
                data["fornecedor"],
                data["categoria"],
                data["responsavel"],
                data["observacao"],
                data["status_conferencia"],
                data["document_kind"],
                data["hora_documento"],
                data["favorecido"],
                data["id_transacao"],
                data["comentario"],
                data["conta_origem"],
                data["texto_extraido"],
                data["needs_review"],
            ),
        )
        connection.commit()


def list_processed_documents(limit: int = 50, include_invalid: bool = False) -> list[dict]:
    init_database()
    try:
        safe_limit = int(limit)
    except (TypeError, ValueError):
        safe_limit = 50

    safe_limit = max(1, min(safe_limit, 500))

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                id,
                data_processamento,
                tipo_documento,
                caminho_arquivo,
                sucesso,
                mensagem,
                dados_extraidos,
                chave_acesso,
                url_consulta,
                valor_total,
                data_documento,
                fornecedor,
                categoria,
                responsavel,
                observacao,
                status_conferencia,
                document_kind,
                hora_documento,
                favorecido,
                id_transacao,
                comentario,
                conta_origem,
                texto_extraido,
                needs_review
            FROM documentos_processados
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    documents = [dict(row) for row in rows]
    if include_invalid:
        return documents

    return [document for document in documents if is_useful_document(document)]


def get_processed_document_by_id(documento_id: int) -> dict | None:
    init_database()

    try:
        safe_id = int(documento_id)
    except (TypeError, ValueError):
        return None

    columns = ",\n                ".join(TABLE_COLUMNS)
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            f"""
            SELECT
                {columns}
            FROM documentos_processados
            WHERE id = ?
            """,
            (safe_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def update_processed_document(documento_id: int, dados: dict) -> bool:
    init_database()

    try:
        safe_id = int(documento_id)
    except (TypeError, ValueError):
        return False

    allowed_fields = {
        "tipo_documento",
        "fornecedor",
        "valor_total",
        "data_documento",
        "categoria",
        "responsavel",
        "observacao",
        "status_conferencia",
    }
    update_data = {
        field: dados.get(field)
        for field in allowed_fields
        if field in dados
    }
    if not update_data:
        return False

    set_clause = ", ".join(f"{field} = ?" for field in update_data)
    values = list(update_data.values())
    values.append(safe_id)

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(
            f"""
            UPDATE documentos_processados
            SET {set_clause}
            WHERE id = ?
            """,
            values,
        )
        connection.commit()

    return cursor.rowcount > 0


def delete_processed_document(documento_id: int) -> bool:
    init_database()

    try:
        safe_id = int(documento_id)
    except (TypeError, ValueError):
        return False

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(
            """
            DELETE FROM documentos_processados
            WHERE id = ?
            """,
            (safe_id,),
        )
        connection.commit()

    return cursor.rowcount > 0


def list_invalid_documents(limit: int = 50) -> list[dict]:
    documents = list_processed_documents(limit=limit, include_invalid=True)
    return [document for document in documents if not is_useful_document(document)]


def is_useful_document(record: dict) -> bool:
    valor_total = _to_float(record.get("valor_total"))
    if valor_total is not None:
        return True

    if str(record.get("chave_acesso") or "").strip():
        return True

    document_kind = str(record.get("document_kind") or "").strip().lower()
    if document_kind and document_kind != "desconhecido":
        return True

    if _is_truthy(record.get("sucesso")) and _has_useful_extracted_data(record):
        return True

    return False


def get_documents_summary() -> dict:
    summary = {
        "total_geral": 0.0,
        "total_notas_fiscais": 0.0,
        "total_recibos_comprovantes": 0.0,
        "quantidade_total_documentos": 0,
        "quantidade_notas_fiscais": 0,
        "quantidade_recibos_comprovantes": 0,
        "quantidade_pendentes_revisao": 0,
    }

    if not DB_PATH.exists():
        return summary

    try:
        init_database()
        with sqlite3.connect(DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT
                    id,
                    data_processamento,
                    tipo_documento,
                    caminho_arquivo,
                    sucesso,
                    mensagem,
                    dados_extraidos,
                    chave_acesso,
                    url_consulta,
                    valor_total,
                    data_documento,
                    fornecedor,
                    categoria,
                    responsavel,
                    observacao,
                    status_conferencia,
                    document_kind,
                    hora_documento,
                    favorecido,
                    id_transacao,
                    comentario,
                    conta_origem,
                    texto_extraido,
                    needs_review
                FROM documentos_processados
                """
            ).fetchall()
    except sqlite3.Error:
        return summary

    for row in rows:
        row = dict(row)
        if not is_useful_document(row):
            continue

        tipo_documento = str(row["tipo_documento"] or "").lower()
        valor_total = _to_float(row["valor_total"]) or 0.0

        summary["quantidade_total_documentos"] += 1
        summary["total_geral"] += valor_total

        if "nota" in tipo_documento:
            summary["quantidade_notas_fiscais"] += 1
            summary["total_notas_fiscais"] += valor_total

        if "recibo" in tipo_documento or "comprovante" in tipo_documento:
            summary["quantidade_recibos_comprovantes"] += 1
            summary["total_recibos_comprovantes"] += valor_total

        if _is_pending_review_status(row.get("status_conferencia")):
            summary["quantidade_pendentes_revisao"] += 1

    return summary


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_structured_data(value: str) -> dict:
    if not value:
        return {}

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    return parsed


def _to_int_bool(value: object) -> int:
    if isinstance(value, str):
        return 1 if value.strip().lower() in ("1", "true", "sim", "yes") else 0

    return 1 if bool(value) else 0


def _is_truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "sim", "yes")

    return bool(value)


def _is_pending_review_status(value: object) -> bool:
    return str(value or "").strip().lower() != "revisado"


def _has_useful_extracted_data(record: dict) -> bool:
    message = str(record.get("mensagem") or "").lower()
    if any(
        pattern in message
        for pattern in (
            "não foi possível ler",
            "nao foi possivel ler",
            "ocr não está configurado",
            "ocr nao esta configurado",
            "não foi possível extrair",
            "nao foi possivel extrair",
        )
    ):
        return False

    dados_extraidos = str(record.get("dados_extraidos") or "").strip()
    if not dados_extraidos:
        return False

    structured_data = _parse_structured_data(dados_extraidos)
    if structured_data:
        if _to_float(structured_data.get("valor_total")) is not None:
            return True

        document_kind = str(structured_data.get("document_kind") or "").strip().lower()
        if document_kind and document_kind != "desconhecido":
            return True

        if str(structured_data.get("chave_acesso") or "").strip():
            return True

        if str(structured_data.get("texto_extraido") or "").strip() and any(
            str(structured_data.get(field) or "").strip()
            for field in ("data_documento", "hora_documento", "favorecido", "id_transacao")
        ):
            return True

        return False

    if dados_extraidos.startswith(("http://", "https://")):
        return True

    fallback_markers = (
        "needs_manual_key",
        "processing_attempts",
        "arquivo recebido:",
        "desconhecido",
    )
    normalized_data = dados_extraidos.lower()
    return not any(marker in normalized_data for marker in fallback_markers)
