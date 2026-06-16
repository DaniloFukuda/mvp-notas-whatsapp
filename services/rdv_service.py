import csv
import io
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path


DEFAULT_DB_PATH = Path("data/app.db")
CATEGORIES = (
    "combustivel",
    "alimentacao",
    "pedagio",
    "hospedagem",
    "manutencao",
    "outro",
)
COLLABORATORS = ("Marcelo", "Henrique", "Anderson", "Danilo", "Outro")
REVIEW_STATUSES = ("pendente", "aprovado", "rejeitado")
FLOW_STATUSES = (
    "pendente",
    "aguardando_valor",
    "aguardando_data_comprovante",
    "aguardando_categoria",
    "aguardando_km_origem",
    "aguardando_km_destino",
    "aguardando_km_inicio",
    "aguardando_km_fim",
    "viagem_em_andamento",
    "cancelado",
    "completo",
    "revisao",
)
OPEN_FLOW_STATUSES = (
    "aguardando_valor",
    "aguardando_data_comprovante",
    "aguardando_categoria",
    "aguardando_km_origem",
    "aguardando_km_destino",
    "aguardando_km_inicio",
    "aguardando_km_fim",
    "viagem_em_andamento",
)
INTERACTIVE_EXPENSE_FLOW_STATUSES = (
    "aguardando_valor",
    "aguardando_data_comprovante",
    "aguardando_categoria",
)
LEGACY_KM_FLOW_STATUSES = (
    "aguardando_km_origem",
    "aguardando_km_destino",
    "aguardando_km_inicio",
    "aguardando_km_fim",
)
ALL_OPEN_KM_FLOW_STATUSES = (
    *LEGACY_KM_FLOW_STATUSES,
    "viagem_em_andamento",
)
OPEN_KM_FLOW_STATUSES = ALL_OPEN_KM_FLOW_STATUSES
KM_FLOW_OBSERVATIONS = (
    "quilometragem registrada pelo WhatsApp",
    "viagem cancelada pelo WhatsApp",
)
INPUT_TYPES = ("texto", "imagem", "documento")
DEMO_COLLABORATORS = (
    ("Danilo", "5500000000001"),
    ("Marcelo", "5500000000002"),
    ("Henrique", "5500000000003"),
    ("Anderson", "5500000000004"),
)
RDV_COLUMNS = (
    "id",
    "colaborador_id",
    "colaborador",
    "telefone_origem",
    "tipo_entrada",
    "data_despesa",
    "semana_referencia",
    "categoria",
    "valor",
    "fornecedor",
    "qr_code_text",
    "qr_code_url",
    "chave_acesso",
    "valor_detectado",
    "data_detectada",
    "fornecedor_detectado",
    "origem_valor",
    "falha_leitura",
    "motivo_revisao",
    "cidade_origem",
    "cidade_destino",
    "km_inicio",
    "km_fim",
    "km_rodado",
    "quilometragem",
    "observacao",
    "origem",
    "whatsapp_message_id",
    "caminho_arquivo",
    "status_fluxo",
    "status_revisao",
    "recebido_em",
    "created_at",
    "updated_at",
)


class RDVService:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def init_database(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rdv_colaboradores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL UNIQUE,
                    telefone_whatsapp TEXT NOT NULL UNIQUE,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    criado_em TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rdv_despesas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    colaborador_id INTEGER,
                    colaborador TEXT NOT NULL,
                    telefone_origem TEXT,
                    tipo_entrada TEXT NOT NULL DEFAULT 'texto',
                    data_despesa TEXT NOT NULL,
                    semana_referencia TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    valor REAL,
                    fornecedor TEXT,
                    qr_code_text TEXT,
                    qr_code_url TEXT,
                    chave_acesso TEXT,
                    valor_detectado REAL,
                    data_detectada TEXT,
                    fornecedor_detectado TEXT,
                    origem_valor TEXT,
                    falha_leitura INTEGER NOT NULL DEFAULT 0,
                    motivo_revisao TEXT,
                    cidade_origem TEXT,
                    cidade_destino TEXT,
                    km_inicio REAL,
                    km_fim REAL,
                    km_rodado REAL,
                    quilometragem REAL,
                    observacao TEXT,
                    origem TEXT NOT NULL DEFAULT 'web',
                    whatsapp_message_id TEXT,
                    caminho_arquivo TEXT,
                    status_fluxo TEXT NOT NULL DEFAULT 'completo',
                    status_revisao TEXT NOT NULL DEFAULT 'pendente',
                    recebido_em TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (colaborador_id) REFERENCES rdv_colaboradores (id)
                )
                """
            )
            self._migrate_expense_columns(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rdv_tentativas_comprovante (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rdv_despesa_id INTEGER NOT NULL,
                    whatsapp_message_id TEXT NOT NULL UNIQUE,
                    caminho_arquivo TEXT,
                    valor_detectado REAL,
                    origem_valor TEXT,
                    sucesso_leitura INTEGER NOT NULL DEFAULT 0,
                    criado_em TEXT NOT NULL,
                    FOREIGN KEY (rdv_despesa_id) REFERENCES rdv_despesas (id)
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_rdv_whatsapp_message_id
                ON rdv_despesas (whatsapp_message_id)
                WHERE whatsapp_message_id IS NOT NULL
                  AND whatsapp_message_id != ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rdv_filtros
                ON rdv_despesas (
                    semana_referencia,
                    colaborador,
                    categoria,
                    status_revisao
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rdv_fluxo_telefone
                ON rdv_despesas (telefone_origem, status_fluxo, id)
                """
            )
            self._seed_demo_collaborators(connection)
            connection.commit()

    def list_collaborators(self, active_only: bool = True) -> list[dict]:
        self.init_database()
        where_clause = "WHERE ativo = 1" if active_only else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, nome, telefone_whatsapp, ativo, criado_em
                FROM rdv_colaboradores
                {where_clause}
                ORDER BY nome
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_collaborator(self, collaborator_id: int) -> dict | None:
        self.init_database()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, nome, telefone_whatsapp, ativo, criado_em
                FROM rdv_colaboradores
                WHERE id = ?
                """,
                (int(collaborator_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_collaborator_by_phone(self, phone: str) -> dict | None:
        self.init_database()
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, nome, telefone_whatsapp, ativo, criado_em
                FROM rdv_colaboradores
                WHERE telefone_whatsapp = ? AND ativo = 1
                """,
                (normalized_phone,),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_collaborator(
        self,
        nome: str,
        telefone_whatsapp: str,
        ativo: bool = True,
    ) -> dict:
        self.init_database()
        safe_name = _clean(nome)
        safe_phone = normalize_phone(telefone_whatsapp)
        if not safe_name:
            raise ValueError("Nome do colaborador e obrigatorio.")
        if not safe_phone:
            raise ValueError("Telefone do colaborador e obrigatorio.")

        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO rdv_colaboradores (
                    nome, telefone_whatsapp, ativo, criado_em
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(nome) DO UPDATE SET
                    telefone_whatsapp = excluded.telefone_whatsapp,
                    ativo = excluded.ativo
                """,
                (safe_name, safe_phone, int(bool(ativo)), now),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT id, nome, telefone_whatsapp, ativo, criado_em
                FROM rdv_colaboradores
                WHERE nome = ?
                """,
                (safe_name,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def register_manual_expense(self, **data) -> dict:
        data["origem"] = "web"
        data.setdefault("tipo_entrada", "texto")
        data.setdefault("status_fluxo", "completo")
        return self._register_expense(data)

    def register_whatsapp_expense(self, **data) -> dict:
        data["origem"] = "whatsapp"
        data.setdefault("status_revisao", "pendente")
        return self._register_expense(data)

    def create_whatsapp_receipt(
        self,
        collaborator_id: int,
        phone: str,
        input_type: str,
        file_path: str,
        whatsapp_message_id: str,
        received_at: str | datetime | None = None,
        observation: str = "",
        analysis: dict | None = None,
    ) -> dict:
        collaborator = self.get_collaborator(collaborator_id)
        if collaborator is None or not collaborator["ativo"]:
            raise ValueError("Colaborador inativo ou nao encontrado.")

        safe_input_type = _validate_choice(input_type, INPUT_TYPES, "tipo de entrada")
        analysis = analysis or {}
        detected_value = _to_float(analysis.get("valor_detectado"))
        detected_date = _valid_receipt_date(analysis.get("data_detectada"))
        expense_date = detected_date or _date_from_received_at(received_at)
        automatic_read_ok = (
            detected_value is not None
            and detected_date is not None
            and _clean(analysis.get("origem_valor")) in {"qr_code", "ocr"}
        )
        if detected_value is None:
            flow_status = "aguardando_valor"
        elif detected_date is None:
            flow_status = "aguardando_data_comprovante"
        else:
            flow_status = "aguardando_categoria"
        return self.register_whatsapp_expense(
            colaborador_id=collaborator["id"],
            colaborador=collaborator["nome"],
            telefone_origem=normalize_phone(phone),
            tipo_entrada=safe_input_type,
            data_despesa=expense_date.isoformat(),
            categoria="outro",
            valor=detected_value,
            fornecedor=_clean(analysis.get("fornecedor_detectado")),
            qr_code_text=_clean(analysis.get("qr_code_text")),
            qr_code_url=_clean(analysis.get("qr_code_url")),
            chave_acesso=_clean(analysis.get("chave_acesso")),
            valor_detectado=detected_value,
            data_detectada=detected_date.isoformat() if detected_date else "",
            fornecedor_detectado=_clean(analysis.get("fornecedor_detectado")),
            origem_valor=_clean(analysis.get("origem_valor")),
            falha_leitura=0 if automatic_read_ok else 1,
            motivo_revisao=(
                ""
                if automatic_read_ok
                else _analysis_failure_reason(analysis.get("reasons"))
            ),
            caminho_arquivo=file_path,
            whatsapp_message_id=whatsapp_message_id,
            status_fluxo=flow_status,
            recebido_em=_normalize_datetime(received_at),
            observacao=observation or "comprovante recebido pelo WhatsApp",
        )

    def get_open_launch_by_phone(self, phone: str) -> dict | None:
        self.init_database()
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            return None
        placeholders = ", ".join(
            "?" for _ in INTERACTIVE_EXPENSE_FLOW_STATUSES
        )
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(RDV_COLUMNS)}
                FROM rdv_despesas
                WHERE telefone_origem = ?
                  AND status_fluxo IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
                """,
                (normalized_phone, *INTERACTIVE_EXPENSE_FLOW_STATUSES),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_open_km_launch_by_phone(self, phone: str) -> dict | None:
        self.init_database()
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            return None
        placeholders = ", ".join("?" for _ in OPEN_KM_FLOW_STATUSES)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(RDV_COLUMNS)}
                FROM rdv_despesas
                WHERE telefone_origem = ?
                  AND status_fluxo IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
                """,
                (normalized_phone, *OPEN_KM_FLOW_STATUSES),
            ).fetchone()
        return dict(row) if row is not None else None

    def create_whatsapp_km_launch(
        self,
        collaborator_id: int,
        phone: str,
        km_start: object,
        received_at: str | datetime | None = None,
    ) -> dict:
        collaborator = self.get_collaborator(collaborator_id)
        if collaborator is None or not collaborator["ativo"]:
            raise ValueError("Colaborador inativo ou nao encontrado.")
        if self.get_open_km_launch_by_phone(phone) is not None:
            raise ValueError("Ja existe uma viagem em andamento.")
        parsed_start = _to_float(km_start)
        if parsed_start is None or parsed_start < 0:
            raise ValueError("Quilometragem inicial invalida.")

        return self.register_whatsapp_expense(
            colaborador_id=collaborator["id"],
            colaborador=collaborator["nome"],
            telefone_origem=normalize_phone(phone),
            tipo_entrada="texto",
            data_despesa=_date_from_received_at(received_at).isoformat(),
            categoria="outro",
            valor=None,
            km_inicio=parsed_start,
            observacao="quilometragem registrada pelo WhatsApp",
            status_fluxo="aguardando_km_origem",
            status_revisao="pendente",
            recebido_em=_normalize_datetime(received_at),
        )

    def save_km_origin(self, expense_id: int, origin: str) -> dict:
        safe_origin = _clean(origin)
        if not safe_origin:
            raise ValueError("Cidade de origem e obrigatoria.")
        return self._update_launch(
            expense_id,
            expected_status="aguardando_km_origem",
            updates={
                "cidade_origem": safe_origin,
                "status_fluxo": "aguardando_km_destino",
            },
        )

    def save_km_destination(self, expense_id: int, destination: str) -> dict:
        safe_destination = _clean(destination)
        if not safe_destination:
            raise ValueError("Cidade de destino e obrigatoria.")
        return self._update_launch(
            expense_id,
            expected_status="aguardando_km_destino",
            updates={
                "cidade_destino": safe_destination,
                "status_fluxo": "viagem_em_andamento",
            },
        )

    def save_km_start(self, expense_id: int, km_start: object) -> dict:
        parsed_start = _to_float(km_start)
        if parsed_start is None or parsed_start < 0:
            raise ValueError("Quilometragem inicial invalida.")
        return self._update_launch(
            expense_id,
            expected_status="aguardando_km_inicio",
            updates={
                "km_inicio": parsed_start,
                "status_fluxo": "viagem_em_andamento",
            },
        )

    def request_km_end(self, expense_id: int) -> dict:
        return self._update_launch(
            expense_id,
            expected_status="viagem_em_andamento",
            updates={"status_fluxo": "aguardando_km_fim"},
        )

    def complete_km_end(self, expense_id: int, km_end: object) -> dict:
        parsed_end = _to_float(km_end)
        if parsed_end is None or parsed_end < 0:
            raise ValueError("Quilometragem final invalida.")

        current = self.get_expense(expense_id)
        if current is None:
            raise ValueError("Lancamento RDV nao encontrado.")
        if current.get("status_fluxo") != "viagem_em_andamento":
            raise ValueError("Lancamento RDV fora da etapa esperada.")
        if not _clean(current.get("cidade_origem")) or not _clean(
            current.get("cidade_destino")
        ):
            raise ValueError("Informe origem e destino antes de finalizar a viagem.")

        parsed_start = _to_float(current.get("km_inicio"))
        if parsed_start is None:
            raise ValueError("Quilometragem inicial nao informada.")
        if parsed_end <= parsed_start:
            raise ValueError("km_fim deve ser maior que km_inicio.")

        distance = parsed_end - parsed_start
        return self._update_launch(
            expense_id,
            expected_status="viagem_em_andamento",
            updates={
                "km_fim": parsed_end,
                "km_rodado": distance,
                "quilometragem": distance,
                "status_fluxo": "completo",
                "status_revisao": "pendente",
            },
        )

    def cancel_km_launch(self, expense_id: int) -> dict:
        current = self.get_expense(expense_id)
        if current is None:
            raise ValueError("Lancamento RDV nao encontrado.")
        if current.get("status_fluxo") not in ALL_OPEN_KM_FLOW_STATUSES:
            raise ValueError("Nao existe viagem em andamento para cancelar.")
        return self._update_launch(
            expense_id,
            expected_status=str(current["status_fluxo"]),
            updates={
                "status_fluxo": "cancelado",
                "status_revisao": "pendente",
                "observacao": "viagem cancelada pelo WhatsApp",
            },
        )

    def cancel_legacy_km_launches_by_phone(self, phone: str) -> int:
        return 0

    def clear_km_trips(self) -> int:
        self.init_database()
        km_status_placeholders = ", ".join(
            "?" for _ in ALL_OPEN_KM_FLOW_STATUSES
        )
        observation_placeholders = ", ".join("?" for _ in KM_FLOW_OBSERVATIONS)
        km_filter = f"""
            status_fluxo IN ({km_status_placeholders})
            OR observacao IN ({observation_placeholders})
            OR km_inicio IS NOT NULL
            OR km_fim IS NOT NULL
            OR km_rodado IS NOT NULL
            OR quilometragem IS NOT NULL
        """
        parameters = (*ALL_OPEN_KM_FLOW_STATUSES, *KM_FLOW_OBSERVATIONS)

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"""
                DELETE FROM rdv_tentativas_comprovante
                WHERE rdv_despesa_id IN (
                    SELECT id
                    FROM rdv_despesas
                    WHERE {km_filter}
                )
                """,
                parameters,
            )
            cursor = connection.execute(
                f"DELETE FROM rdv_despesas WHERE {km_filter}",
                parameters,
            )
            connection.commit()
        return max(int(cursor.rowcount or 0), 0)

    def save_launch_value(self, expense_id: int, value: object) -> dict:
        parsed_value = _to_float(value)
        if parsed_value is None or parsed_value < 0:
            raise ValueError("Valor da despesa invalido.")
        current = self.get_expense(expense_id)
        if current is None:
            raise ValueError("Lancamento RDV nao encontrado.")
        receipt_date = _valid_receipt_date(current.get("data_detectada"))
        updates = {
            "valor": parsed_value,
            "origem_valor": "manual",
            "falha_leitura": 1,
            "motivo_revisao": "valor informado manualmente apos falha de leitura",
            "status_fluxo": (
                "aguardando_categoria"
                if receipt_date is not None
                else "aguardando_data_comprovante"
            ),
        }
        if receipt_date is not None:
            updates.update(
                {
                    "data_despesa": receipt_date.isoformat(),
                    "semana_referencia": calculate_week_reference(receipt_date),
                }
            )
        return self._update_launch(
            expense_id,
            expected_status="aguardando_valor",
            updates=updates,
        )

    def save_launch_receipt_date(self, expense_id: int, value: object) -> dict:
        receipt_date = parse_receipt_date(value)
        return self._update_launch(
            expense_id,
            expected_status="aguardando_data_comprovante",
            updates={
                "data_despesa": receipt_date.isoformat(),
                "data_detectada": receipt_date.isoformat(),
                "semana_referencia": calculate_week_reference(receipt_date),
                "status_fluxo": "aguardando_categoria",
            },
        )

    def retry_whatsapp_receipt(
        self,
        expense_id: int,
        input_type: str,
        file_path: str,
        whatsapp_message_id: str,
        analysis: dict | None = None,
    ) -> dict:
        self.init_database()
        current = self.get_expense(expense_id)
        if current is None:
            raise ValueError("Lancamento RDV nao encontrado.")
        if current.get("status_fluxo") != "aguardando_valor":
            raise ValueError("Lancamento RDV fora da etapa esperada.")

        safe_message_id = _clean(whatsapp_message_id)
        if not safe_message_id:
            raise ValueError("ID da mensagem WhatsApp e obrigatorio.")
        safe_input_type = _validate_choice(input_type, INPUT_TYPES, "tipo de entrada")
        analysis = analysis or {}
        detected_value = _to_float(analysis.get("valor_detectado"))
        detected_date = _valid_receipt_date(analysis.get("data_detectada"))
        automatic_read_ok = (
            detected_value is not None
            and detected_date is not None
            and _clean(analysis.get("origem_valor")) in {"qr_code", "ocr"}
        )
        updates = {
            "tipo_entrada": safe_input_type,
            "caminho_arquivo": _clean(file_path),
            "qr_code_text": _clean(analysis.get("qr_code_text")),
            "qr_code_url": _clean(analysis.get("qr_code_url")),
            "chave_acesso": _clean(analysis.get("chave_acesso")),
            "data_detectada": detected_date.isoformat() if detected_date else "",
            "fornecedor_detectado": _clean(analysis.get("fornecedor_detectado")),
            "fornecedor": _clean(analysis.get("fornecedor_detectado")),
            "falha_leitura": 0 if automatic_read_ok else 1,
            "motivo_revisao": (
                ""
                if automatic_read_ok
                else _analysis_failure_reason(analysis.get("reasons"))
            ),
        }
        if detected_date is not None:
            updates.update(
                {
                    "data_despesa": detected_date.isoformat(),
                    "semana_referencia": calculate_week_reference(detected_date),
                }
            )
        if automatic_read_ok:
            updates.update(
                {
                    "valor": detected_value,
                    "valor_detectado": detected_value,
                    "origem_valor": _clean(analysis.get("origem_valor")),
                    "status_fluxo": "aguardando_categoria",
                }
            )
        elif detected_value is not None:
            updates.update(
                {
                    "valor": detected_value,
                    "valor_detectado": detected_value,
                    "origem_valor": _clean(analysis.get("origem_valor")),
                    "status_fluxo": "aguardando_data_comprovante",
                }
            )

        now = datetime.now().isoformat(timespec="seconds")
        safe_updates = dict(updates)
        safe_updates["updated_at"] = now
        assignments = ", ".join(f"{column} = ?" for column in safe_updates)
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """
                SELECT rdv_despesa_id
                FROM rdv_tentativas_comprovante
                WHERE whatsapp_message_id = ?
                """,
                (safe_message_id,),
            ).fetchone()
            if existing is not None:
                return self.get_expense(existing["rdv_despesa_id"]) or {}

            connection.execute(
                f"UPDATE rdv_despesas SET {assignments} WHERE id = ?",
                (*safe_updates.values(), int(expense_id)),
            )
            connection.execute(
                """
                INSERT INTO rdv_tentativas_comprovante (
                    rdv_despesa_id,
                    whatsapp_message_id,
                    caminho_arquivo,
                    valor_detectado,
                    origem_valor,
                    sucesso_leitura,
                    criado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(expense_id),
                    safe_message_id,
                    _clean(file_path),
                    detected_value,
                    _clean(analysis.get("origem_valor")),
                    int(automatic_read_ok),
                    now,
                ),
            )
            connection.commit()
        return self.get_expense(expense_id) or {}

    def complete_launch_category(self, expense_id: int, category: str) -> dict:
        normalized_category = _normalize_category(category)
        current = self.get_expense(expense_id)
        if current is None:
            raise ValueError("Lancamento RDV nao encontrado.")
        receipt_date = _valid_receipt_date(current.get("data_detectada"))
        if receipt_date is None:
            raise ValueError("Data do comprovante nao informada.")
        automatic_read_ok = (
            current.get("origem_valor") in {"qr_code", "ocr"}
            and current.get("valor_detectado") is not None
            and not bool(current.get("falha_leitura"))
        )
        return self._update_launch(
            expense_id,
            expected_status="aguardando_categoria",
            updates={
                "categoria": normalized_category,
                "data_despesa": receipt_date.isoformat(),
                "semana_referencia": calculate_week_reference(receipt_date),
                "status_fluxo": "completo",
                "status_revisao": "aprovado" if automatic_read_ok else "pendente",
            },
        )

    def mark_launch_for_review(self, expense_id: int) -> dict:
        return self._update_launch(
            expense_id,
            updates={
                "status_fluxo": "revisao",
                "status_revisao": "pendente",
            },
        )

    def list_expenses(
        self,
        colaborador: str = "",
        semana: str = "",
        categoria: str = "",
        status: str = "",
    ) -> list[dict]:
        self.init_database()
        clauses = []
        values = []
        for column, value in (
            ("colaborador", colaborador),
            ("semana_referencia", semana),
            ("categoria", categoria),
            ("status_revisao", status),
        ):
            normalized = str(value or "").strip()
            if normalized:
                clauses.append(f"{column} = ?")
                values.append(normalized)

        return self._select_expenses(clauses, values)

    def list_launches(
        self,
        collaborator_id: int | str = "",
        status: str = "",
        week: str = "",
    ) -> list[dict]:
        self.init_database()
        clauses = []
        values = []
        if str(collaborator_id or "").strip():
            clauses.append("colaborador_id = ?")
            values.append(int(collaborator_id))
        if str(status or "").strip():
            clauses.append("status_fluxo = ?")
            values.append(_validate_choice(status, FLOW_STATUSES, "status"))
        if str(week or "").strip():
            clauses.append("semana_referencia = ?")
            values.append(str(week).strip())
        return self._select_expenses(clauses, values)

    def get_expense(self, expense_id: int) -> dict | None:
        self.init_database()
        try:
            safe_id = int(expense_id)
        except (TypeError, ValueError):
            return None

        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(RDV_COLUMNS)}
                FROM rdv_despesas
                WHERE id = ?
                """,
                (safe_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_by_whatsapp_message_id(self, message_id: str) -> dict | None:
        self.init_database()
        safe_message_id = str(message_id or "").strip()
        if not safe_message_id:
            return None

        with closing(self._connect()) as connection:
            row = connection.execute(
                f"""
                SELECT {", ".join(RDV_COLUMNS)}
                FROM rdv_despesas
                WHERE whatsapp_message_id = ?
                """,
                (safe_message_id,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    f"""
                    SELECT {", ".join(f"d.{column}" for column in RDV_COLUMNS)}
                    FROM rdv_tentativas_comprovante AS t
                    JOIN rdv_despesas AS d ON d.id = t.rdv_despesa_id
                    WHERE t.whatsapp_message_id = ?
                    """,
                    (safe_message_id,),
                ).fetchone()
        return dict(row) if row is not None else None

    def update_review_status(self, expense_id: int, status: str) -> bool:
        normalized_status = _validate_choice(status, REVIEW_STATUSES, "status de revisao")
        self.init_database()
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE rdv_despesas
                SET status_revisao = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_status, now, int(expense_id)),
            )
            connection.commit()
        return cursor.rowcount > 0

    def summarize(
        self,
        colaborador: str = "",
        semana: str = "",
        categoria: str = "",
        status: str = "",
    ) -> dict:
        expenses = self.list_expenses(
            colaborador=colaborador,
            semana=semana,
            categoria=categoria,
            status=status,
        )
        return _summarize_expenses(expenses)

    def weekly_report(
        self,
        week: str = "",
        collaborator_id: int | str = "",
        status: str = "",
    ) -> dict:
        dataset = self.weekly_report_data(
            week=week,
            collaborator_id=collaborator_id,
            status=status,
        )
        expenses = dataset["lancamentos"]
        km_launches = dataset.get("quilometragens") or []
        summary = _summarize_expenses(expenses)
        return {
            "semana": dataset["semana"],
            "total_geral": summary["total_geral"],
            "por_colaborador": summary["por_colaborador"],
            "por_categoria": summary["por_categoria"],
            "quantidade_comprovantes": sum(
                1 for expense in expenses if _has_receipt_attachment(expense)
            ),
            "quilometragem_total": sum(
                float(expense.get("quilometragem") or expense.get("km_rodado") or 0)
                for expense in km_launches
                if expense.get("status_fluxo") in {"completo", "revisao"}
            ),
            "viagens_em_aberto": sum(
                1
                for expense in km_launches
                if expense.get("status_fluxo") in ALL_OPEN_KM_FLOW_STATUSES
            ),
            "quantidade_lancamentos": len(expenses),
            "pendentes_revisao": len(dataset["pendencias"]),
        }

    def weekly_report_data(
        self,
        week: str = "",
        collaborator_id: int | str = "",
        status: str = "",
    ) -> dict:
        selected_week = str(week or "").strip() or calculate_week_reference(date.today())
        expenses = self.list_launches(
            collaborator_id=collaborator_id,
            status=status,
            week=selected_week,
        )
        report_expenses = [
            expense for expense in expenses if _is_reportable_expense(expense)
        ]
        km_launches = [
            expense
            for expense in expenses
            if not _is_cancelled_launch(expense) and _is_km_launch(expense)
        ]
        by_collaborator: dict[str, dict] = {}
        by_category: dict[str, dict] = {}
        pending = []
        for expense in report_expenses:
            value = float(expense.get("valor") or 0)
            collaborator = str(expense.get("colaborador") or "Nao informado")
            category = str(expense.get("categoria") or "outro")

            collaborator_summary = by_collaborator.setdefault(
                collaborator,
                {
                    "colaborador": collaborator,
                    "total": 0.0,
                    "quantidade": 0,
                    "quilometragem_total": 0.0,
                    "pendentes": 0,
                },
            )
            collaborator_summary["total"] += value
            collaborator_summary["quantidade"] += 1

            category_summary = by_category.setdefault(
                category,
                {
                    "categoria": category,
                    "total": 0.0,
                    "quantidade": 0,
                },
            )
            category_summary["total"] += value
            category_summary["quantidade"] += 1

            if _is_pending_launch(expense):
                pending.append(expense)
                collaborator_summary["pendentes"] += 1

        for expense in km_launches:
            distance = float(
                expense.get("quilometragem") or expense.get("km_rodado") or 0
            )
            collaborator = str(expense.get("colaborador") or "Nao informado")
            collaborator_summary = by_collaborator.setdefault(
                collaborator,
                {
                    "colaborador": collaborator,
                    "total": 0.0,
                    "quantidade": 0,
                    "quilometragem_total": 0.0,
                    "pendentes": 0,
                },
            )
            collaborator_summary["quantidade"] += 1
            collaborator_summary["quilometragem_total"] += distance
            if _is_pending_launch(expense):
                pending.append(expense)
                collaborator_summary["pendentes"] += 1

        return {
            "semana": selected_week,
            "lancamentos": report_expenses,
            "quilometragens": km_launches,
            "resumo_colaboradores": sorted(
                by_collaborator.values(),
                key=lambda item: item["colaborador"],
            ),
            "resumo_categorias": sorted(
                by_category.values(),
                key=lambda item: item["categoria"],
            ),
            "pendencias": pending,
        }

    def export_csv(
        self,
        colaborador: str = "",
        semana: str = "",
        categoria: str = "",
        status: str = "",
    ) -> str:
        expenses = self.list_expenses(
            colaborador=colaborador,
            semana=semana,
            categoria=categoria,
            status=status,
        )
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=RDV_COLUMNS, delimiter=";")
        writer.writeheader()
        for expense in expenses:
            writer.writerow(expense)
        return output.getvalue()

    def _register_expense(self, data: dict) -> dict:
        self.init_database()
        data_despesa = _normalize_date(data.get("data_despesa"))
        collaborator = self._resolve_collaborator(data)
        collaborator_name = (
            collaborator["nome"]
            if collaborator is not None
            else _validate_choice(
                data.get("colaborador") or "Outro",
                COLLABORATORS,
                "colaborador",
            )
        )
        status = _validate_choice(
            str(data.get("status_revisao") or "pendente").lower(),
            REVIEW_STATUSES,
            "status de revisao",
        )
        flow_status = _validate_choice(
            str(data.get("status_fluxo") or "completo").lower(),
            FLOW_STATUSES,
            "status do fluxo",
        )
        input_type = _validate_choice(
            str(data.get("tipo_entrada") or "texto").lower(),
            INPUT_TYPES,
            "tipo de entrada",
        )
        km_inicio = _to_float(data.get("km_inicio"))
        km_fim = _to_float(data.get("km_fim"))
        if km_inicio is not None and km_fim is not None and km_fim < km_inicio:
            raise ValueError("km_fim nao pode ser menor que km_inicio.")

        now = datetime.now().isoformat(timespec="seconds")
        km_rodado = calculate_distance(km_inicio, km_fim)
        record = {
            "colaborador_id": collaborator["id"] if collaborator else None,
            "colaborador": collaborator_name,
            "telefone_origem": normalize_phone(data.get("telefone_origem")),
            "tipo_entrada": input_type,
            "data_despesa": data_despesa,
            "semana_referencia": calculate_week_reference(data_despesa),
            "categoria": _normalize_category(data.get("categoria") or "outro"),
            "valor": _to_float(data.get("valor")),
            "fornecedor": _clean(data.get("fornecedor")),
            "qr_code_text": _clean(data.get("qr_code_text")),
            "qr_code_url": _clean(data.get("qr_code_url")),
            "chave_acesso": _clean(data.get("chave_acesso")),
            "valor_detectado": _to_float(data.get("valor_detectado")),
            "data_detectada": _clean(data.get("data_detectada")),
            "fornecedor_detectado": _clean(data.get("fornecedor_detectado")),
            "origem_valor": _clean(data.get("origem_valor")),
            "falha_leitura": int(bool(data.get("falha_leitura"))),
            "motivo_revisao": _clean(data.get("motivo_revisao")),
            "cidade_origem": _clean(data.get("cidade_origem")),
            "cidade_destino": _clean(data.get("cidade_destino")),
            "km_inicio": km_inicio,
            "km_fim": km_fim,
            "km_rodado": km_rodado,
            "quilometragem": _to_float(data.get("quilometragem")) or km_rodado,
            "observacao": _clean(data.get("observacao")),
            "origem": _clean(data.get("origem")) or "web",
            "whatsapp_message_id": _clean(data.get("whatsapp_message_id")),
            "caminho_arquivo": _clean(data.get("caminho_arquivo")),
            "status_fluxo": flow_status,
            "status_revisao": status,
            "recebido_em": _normalize_datetime(data.get("recebido_em")),
            "created_at": now,
            "updated_at": now,
        }
        columns = tuple(column for column in RDV_COLUMNS if column != "id")
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO rdv_despesas ({", ".join(columns)})
                VALUES ({", ".join("?" for _ in columns)})
                """,
                tuple(record[column] for column in columns),
            )
            connection.commit()
            expense_id = cursor.lastrowid
        return self.get_expense(expense_id) or {}

    def _resolve_collaborator(self, data: dict) -> dict | None:
        collaborator_id = data.get("colaborador_id")
        if collaborator_id not in (None, ""):
            return self.get_collaborator(int(collaborator_id))

        phone = normalize_phone(data.get("telefone_origem"))
        if phone:
            collaborator = self.get_collaborator_by_phone(phone)
            if collaborator is not None:
                return collaborator

        name = _clean(data.get("colaborador"))
        if not name or name == "Outro":
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, nome, telefone_whatsapp, ativo, criado_em
                FROM rdv_colaboradores
                WHERE lower(nome) = lower(?)
                """,
                (name,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _select_expenses(self, clauses: list[str], values: list) -> list[dict]:
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {", ".join(RDV_COLUMNS)}
                FROM rdv_despesas
                {where_clause}
                ORDER BY recebido_em DESC, id DESC
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def _update_launch(
        self,
        expense_id: int,
        updates: dict,
        expected_status: str = "",
    ) -> dict:
        self.init_database()
        allowed_columns = {
            "valor",
            "data_despesa",
            "semana_referencia",
            "origem_valor",
            "falha_leitura",
            "motivo_revisao",
            "categoria",
            "cidade_origem",
            "cidade_destino",
            "km_inicio",
            "km_fim",
            "km_rodado",
            "quilometragem",
            "observacao",
            "status_fluxo",
            "status_revisao",
            "tipo_entrada",
            "caminho_arquivo",
            "qr_code_text",
            "qr_code_url",
            "chave_acesso",
            "valor_detectado",
            "data_detectada",
            "fornecedor_detectado",
            "fornecedor",
        }
        invalid_columns = set(updates) - allowed_columns
        if invalid_columns:
            raise ValueError("Campos de atualizacao invalidos.")

        current = self.get_expense(expense_id)
        if current is None:
            raise ValueError("Lancamento RDV nao encontrado.")
        if expected_status and current.get("status_fluxo") != expected_status:
            raise ValueError("Lancamento RDV fora da etapa esperada.")

        safe_updates = dict(updates)
        safe_updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
        assignments = ", ".join(f"{column} = ?" for column in safe_updates)
        with closing(self._connect()) as connection:
            connection.execute(
                f"UPDATE rdv_despesas SET {assignments} WHERE id = ?",
                (*safe_updates.values(), int(expense_id)),
            )
            connection.commit()
        return self.get_expense(expense_id) or {}

    def _migrate_expense_columns(self, connection: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(rdv_despesas)").fetchall()
        }
        migrations = {
            "colaborador_id": "INTEGER",
            "telefone_origem": "TEXT",
            "tipo_entrada": "TEXT NOT NULL DEFAULT 'texto'",
            "quilometragem": "REAL",
            "status_fluxo": "TEXT NOT NULL DEFAULT 'completo'",
            "recebido_em": "TEXT",
            "qr_code_text": "TEXT",
            "qr_code_url": "TEXT",
            "chave_acesso": "TEXT",
            "valor_detectado": "REAL",
            "data_detectada": "TEXT",
            "fornecedor_detectado": "TEXT",
            "origem_valor": "TEXT",
            "falha_leitura": "INTEGER NOT NULL DEFAULT 0",
            "motivo_revisao": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE rdv_despesas ADD COLUMN {column} {definition}"
                )
        connection.execute(
            """
            UPDATE rdv_despesas
            SET recebido_em = COALESCE(NULLIF(recebido_em, ''), created_at)
            WHERE recebido_em IS NULL OR recebido_em = ''
            """
        )

    def _seed_demo_collaborators(self, connection: sqlite3.Connection) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        connection.executemany(
            """
            INSERT OR IGNORE INTO rdv_colaboradores (
                nome, telefone_whatsapp, ativo, criado_em
            ) VALUES (?, ?, 1, ?)
            """,
            [(name, phone, now) for name, phone in DEMO_COLLABORATORS],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def calculate_week_reference(value: str | date | datetime) -> str:
    expense_date = _date_value(value)
    iso_year, iso_week, _ = expense_date.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def parse_receipt_date(value: object) -> date:
    parsed = _parse_receipt_date_value(value)
    if parsed is None or parsed > date.today():
        raise ValueError("Data da despesa invalida.")
    return parsed


def calculate_distance(km_inicio: object, km_fim: object) -> float | None:
    start = _to_float(km_inicio)
    end = _to_float(km_fim)
    if start is None or end is None:
        return None
    return end - start


def normalize_phone(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _normalize_date(value: object) -> str:
    if value in (None, ""):
        return date.today().isoformat()
    return _date_value(value).isoformat()


def _date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise ValueError("Data da despesa invalida.")


def _valid_receipt_date(value: object) -> date | None:
    parsed = _parse_receipt_date_value(value)
    if parsed is None or parsed > date.today():
        return None
    return parsed


def _parse_receipt_date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    textual = re.search(
        r"\b(\d{1,2})\s*(?:/|\s+de\s+)\s*"
        r"(janeiro|fevereiro|mar(?:c|\u00e7)o|abril|maio|junho|julho|agosto|"
        r"setembro|outubro|novembro|dezembro)"
        r"\s*(?:/|\s+de\s+)\s*(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if textual:
        month = _portuguese_month_number(textual.group(2))
        if month:
            try:
                return date(int(textual.group(3)), month, int(textual.group(1)))
            except ValueError:
                return None

    for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def _portuguese_month_number(value: str) -> int:
    normalized = _strip_accents(value).lower()
    months = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    return months.get(normalized, 0)


def _strip_accents(value: str) -> str:
    replacements = str.maketrans(
        {
            "\u00e1": "a",
            "\u00e0": "a",
            "\u00e2": "a",
            "\u00e3": "a",
            "\u00e9": "e",
            "\u00ea": "e",
            "\u00ed": "i",
            "\u00f3": "o",
            "\u00f4": "o",
            "\u00f5": "o",
            "\u00fa": "u",
            "\u00e7": "c",
            "\u00c1": "A",
            "\u00c0": "A",
            "\u00c2": "A",
            "\u00c3": "A",
            "\u00c9": "E",
            "\u00ca": "E",
            "\u00cd": "I",
            "\u00d3": "O",
            "\u00d4": "O",
            "\u00d5": "O",
            "\u00da": "U",
            "\u00c7": "C",
        }
    )
    return str(value or "").translate(replacements)


def _date_from_received_at(value: str | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if text:
        for date_format in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(text, date_format).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return date.today()


def _normalize_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    text = str(value or "").strip()
    if text:
        for date_format in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(text, date_format).isoformat(timespec="seconds")
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat(
                timespec="seconds"
            )
        except ValueError:
            pass
    return datetime.now().isoformat(timespec="seconds")


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valor numerico invalido: {value}") from exc


def _normalize_category(value: object) -> str:
    normalized = _clean(value).lower()
    if normalized == "hotel":
        normalized = "hospedagem"
    return _validate_choice(normalized, CATEGORIES, "categoria")


def _validate_choice(value: object, choices: tuple[str, ...], field: str) -> str:
    normalized = str(value or "").strip()
    matches = {choice.lower(): choice for choice in choices}
    if normalized.lower() not in matches:
        raise ValueError(f"{field.capitalize()} invalido.")
    return matches[normalized.lower()]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _summarize_expenses(expenses: list[dict]) -> dict:
    by_collaborator: dict[str, float] = {}
    by_week: dict[str, float] = {}
    by_category: dict[str, float] = {}
    total = 0.0
    for expense in expenses:
        value = float(expense.get("valor") or 0)
        total += value
        _add_total(by_collaborator, expense.get("colaborador"), value)
        _add_total(by_week, expense.get("semana_referencia"), value)
        _add_total(by_category, expense.get("categoria"), value)
    return {
        "total_geral": total,
        "quantidade": len(expenses),
        "por_colaborador": by_collaborator,
        "por_semana": by_week,
        "por_categoria": by_category,
    }


def _is_cancelled_launch(expense: dict) -> bool:
    return str(expense.get("status_fluxo") or "").lower() == "cancelado"


def _is_km_launch(expense: dict) -> bool:
    if any(
        expense.get(field) not in (None, "")
        for field in ("km_inicio", "km_fim", "km_rodado", "quilometragem")
    ):
        return True
    observation = str(expense.get("observacao") or "").lower()
    return "quilometragem" in observation or "viagem" in observation


def _has_receipt_attachment(expense: dict) -> bool:
    input_type = str(expense.get("tipo_entrada") or "").lower()
    return bool(expense.get("caminho_arquivo")) or input_type in {
        "imagem",
        "documento",
    }


def _is_reportable_expense(expense: dict) -> bool:
    if _is_cancelled_launch(expense) or _is_km_launch(expense):
        return False
    if _has_receipt_attachment(expense):
        return True
    if str(expense.get("origem") or "").lower() == "web":
        return True
    if expense.get("whatsapp_message_id"):
        return True
    value = expense.get("valor")
    try:
        return float(value) != 0
    except (TypeError, ValueError):
        return False


def _is_pending_launch(expense: dict) -> bool:
    return (
        expense.get("status_fluxo")
        in {"pendente", *OPEN_FLOW_STATUSES, "revisao"}
        or bool(expense.get("falha_leitura"))
        or expense.get("status_revisao") == "rejeitado"
    )


def _analysis_failure_reason(reasons: object) -> str:
    if not isinstance(reasons, (list, tuple)):
        return "valor_nao_detectado_automaticamente"
    safe_reasons = [
        str(reason).strip()
        for reason in reasons
        if str(reason).strip()
    ]
    return ",".join(safe_reasons)[:500] or "valor_nao_detectado_automaticamente"


def _add_total(totals: dict[str, float], key: object, value: float) -> None:
    normalized_key = str(key or "").strip() or "Nao informado"
    totals[normalized_key] = totals.get(normalized_key, 0.0) + value
