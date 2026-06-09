import csv
import io
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path


DEFAULT_DB_PATH = Path("data/app.db")
CATEGORIES = (
    "combustivel",
    "alimentacao",
    "hotel",
    "pedagio",
    "manutencao",
    "outro",
)
COLLABORATORS = ("Marcelo", "Henrique", "Anderson", "Danilo", "Outro")
REVIEW_STATUSES = ("pendente", "aprovado", "rejeitado")
RDV_COLUMNS = (
    "id",
    "colaborador",
    "data_despesa",
    "semana_referencia",
    "categoria",
    "valor",
    "fornecedor",
    "cidade_origem",
    "cidade_destino",
    "km_inicio",
    "km_fim",
    "km_rodado",
    "observacao",
    "origem",
    "whatsapp_message_id",
    "caminho_arquivo",
    "status_revisao",
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
                CREATE TABLE IF NOT EXISTS rdv_despesas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    colaborador TEXT NOT NULL,
                    data_despesa TEXT NOT NULL,
                    semana_referencia TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    valor REAL,
                    fornecedor TEXT,
                    cidade_origem TEXT,
                    cidade_destino TEXT,
                    km_inicio REAL,
                    km_fim REAL,
                    km_rodado REAL,
                    observacao TEXT,
                    origem TEXT NOT NULL DEFAULT 'web',
                    whatsapp_message_id TEXT,
                    caminho_arquivo TEXT,
                    status_revisao TEXT NOT NULL DEFAULT 'pendente',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
            connection.commit()

    def register_manual_expense(self, **data) -> dict:
        data["origem"] = "web"
        return self._register_expense(data)

    def register_whatsapp_expense(self, **data) -> dict:
        data["origem"] = "whatsapp"
        data.setdefault("status_revisao", "pendente")
        return self._register_expense(data)

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

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {", ".join(RDV_COLUMNS)}
                FROM rdv_despesas
                {where_clause}
                ORDER BY data_despesa DESC, id DESC
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

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
        return dict(row) if row is not None else None

    def update_review_status(self, expense_id: int, status: str) -> bool:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in REVIEW_STATUSES:
            raise ValueError("Status de revisao invalido.")

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
        colaborador = _validate_choice(
            data.get("colaborador") or "Outro",
            COLLABORATORS,
            "colaborador",
        )
        categoria = _validate_choice(
            str(data.get("categoria") or "outro").lower(),
            CATEGORIES,
            "categoria",
        )
        status = _validate_choice(
            str(data.get("status_revisao") or "pendente").lower(),
            REVIEW_STATUSES,
            "status de revisao",
        )
        km_inicio = _to_float(data.get("km_inicio"))
        km_fim = _to_float(data.get("km_fim"))
        if km_inicio is not None and km_fim is not None and km_fim < km_inicio:
            raise ValueError("km_fim nao pode ser menor que km_inicio.")

        now = datetime.now().isoformat(timespec="seconds")
        record = {
            "colaborador": colaborador,
            "data_despesa": data_despesa,
            "semana_referencia": calculate_week_reference(data_despesa),
            "categoria": categoria,
            "valor": _to_float(data.get("valor")),
            "fornecedor": _clean(data.get("fornecedor")),
            "cidade_origem": _clean(data.get("cidade_origem")),
            "cidade_destino": _clean(data.get("cidade_destino")),
            "km_inicio": km_inicio,
            "km_fim": km_fim,
            "km_rodado": calculate_distance(km_inicio, km_fim),
            "observacao": _clean(data.get("observacao")),
            "origem": _clean(data.get("origem")) or "web",
            "whatsapp_message_id": _clean(data.get("whatsapp_message_id")),
            "caminho_arquivo": _clean(data.get("caminho_arquivo")),
            "status_revisao": status,
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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection


def calculate_week_reference(value: str | date | datetime) -> str:
    expense_date = _date_value(value)
    iso_year, iso_week, _ = expense_date.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def calculate_distance(km_inicio: object, km_fim: object) -> float | None:
    start = _to_float(km_inicio)
    end = _to_float(km_fim)
    if start is None or end is None:
        return None
    return end - start


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


def _validate_choice(value: object, choices: tuple[str, ...], field: str) -> str:
    normalized = str(value or "").strip()
    matches = {choice.lower(): choice for choice in choices}
    if normalized.lower() not in matches:
        raise ValueError(f"{field.capitalize()} invalido.")
    return matches[normalized.lower()]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _add_total(totals: dict[str, float], key: object, value: float) -> None:
    normalized_key = str(key or "").strip() or "Nao informado"
    totals[normalized_key] = totals.get(normalized_key, 0.0) + value
