import argparse
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.visitas_service import DEFAULT_DB_PATH, VisitasTecnicasService


TARGET_TEXT = "Danilo Teste"
VISITA_MATCH_COLUMNS = (
    "tecnico_nome",
    "fazenda",
    "proprietario",
    "gerente",
    "objetivo",
    "observacoes",
)
RELATED_TABLES = {
    "visita_midias": ("tipo", "media_id_whatsapp", "caminho_arquivo", "legenda"),
    "visita_localizacoes": ("maps_url", "descricao"),
    "visita_dados_coletados": ("chave", "valor", "observacao"),
    "visita_edicoes": ("telefone_editor", "campo", "valor_anterior", "valor_novo"),
}


def find_cleanup_plan(db_path: str | Path, target_text: str = TARGET_TEXT) -> dict:
    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "db_path": str(db_path),
            "target_text": target_text,
            "visitas": [],
            "related": {},
            "orphan_related": {},
        }

    VisitasTecnicasService(db_path).ensure_schema()
    with closing(_connect(db_path)) as connection:
        visita_ids = set()
        visitas_by_id: dict[int, dict] = {}

        for row in _find_visitas_by_own_fields(connection, target_text):
            visita = dict(row)
            visita_id = int(visita["id"])
            visita_ids.add(visita_id)
            visitas_by_id[visita_id] = visita

        related: dict[str, list[dict]] = {}
        orphan_related: dict[str, list[dict]] = {}
        for table, columns in RELATED_TABLES.items():
            rows = [dict(row) for row in _find_related_rows(connection, table, columns, target_text)]
            related[table] = []
            orphan_related[table] = []
            for row in rows:
                visita_id = int(row["visita_id"])
                visita = _get_visita(connection, visita_id)
                if visita is None:
                    orphan_related[table].append(row)
                    continue
                visita_ids.add(visita_id)
                visitas_by_id[visita_id] = visita
                related[table].append(row)

        visitas = [visitas_by_id[visita_id] for visita_id in sorted(visita_ids)]
        return {
            "db_path": str(db_path),
            "target_text": target_text,
            "visitas": visitas,
            "related": related,
            "orphan_related": orphan_related,
        }


def run_cleanup(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    confirm: bool = False,
    backup_dir: str | Path | None = None,
    output=print,
) -> dict:
    db_path = Path(db_path)
    plan = find_cleanup_plan(db_path)
    _print_plan(plan, output=output)

    result = {"plan": plan, "changed": False, "backup_path": ""}
    if not confirm:
        output("")
        output("Modo dry-run: nenhuma alteracao foi feita.")
        output("Para executar, rode com --confirm.")
        return result

    backup_path = create_backup(db_path, backup_dir=backup_dir)
    output("")
    output(f"Backup criado: {backup_path}")
    _apply_cleanup(db_path, plan)
    output("Limpeza concluida.")
    result["changed"] = True
    result["backup_path"] = str(backup_path)
    return result


def create_backup(db_path: str | Path, backup_dir: str | Path | None = None) -> Path:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Banco nao encontrado: {db_path}")

    target_dir = Path(backup_dir) if backup_dir is not None else db_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = target_dir / f"{db_path.stem}.backup-danilo-teste-{timestamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _apply_cleanup(db_path: Path, plan: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    visita_ids = [int(visita["id"]) for visita in plan["visitas"]]
    with closing(_connect(db_path)) as connection:
        for visita_id in visita_ids:
            connection.execute(
                """
                UPDATE visitas_tecnicas
                SET status = 'cancelada',
                    estado_fluxo = 'cancelada',
                    fechado_em = COALESCE(fechado_em, ?),
                    atualizado_em = ?
                WHERE id = ?
                """,
                (now, now, visita_id),
            )

        for table, rows in plan["orphan_related"].items():
            for row in rows:
                connection.execute(f"DELETE FROM {table} WHERE id = ?", (int(row["id"]),))

        connection.commit()


def _find_visitas_by_own_fields(connection: sqlite3.Connection, target_text: str):
    where = " OR ".join(f"{column} LIKE ?" for column in VISITA_MATCH_COLUMNS)
    values = [f"%{target_text}%" for _ in VISITA_MATCH_COLUMNS]
    return connection.execute(
        f"""
        SELECT *
        FROM visitas_tecnicas
        WHERE {where}
        ORDER BY id
        """,
        values,
    ).fetchall()


def _find_related_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    target_text: str,
):
    where = " OR ".join(f"{column} LIKE ?" for column in columns)
    values = [f"%{target_text}%" for _ in columns]
    return connection.execute(
        f"""
        SELECT *
        FROM {table}
        WHERE {where}
        ORDER BY visita_id, id
        """,
        values,
    ).fetchall()


def _get_visita(connection: sqlite3.Connection, visita_id: int) -> dict | None:
    row = connection.execute(
        "SELECT * FROM visitas_tecnicas WHERE id = ?",
        (int(visita_id),),
    ).fetchone()
    return dict(row) if row is not None else None


def _print_plan(plan: dict, *, output=print) -> None:
    output(f"Banco: {plan['db_path']}")
    output(f"Filtro restrito: {plan['target_text']}")
    output("")
    output(f"Visitas que serao marcadas como canceladas: {len(plan['visitas'])}")
    for visita in plan["visitas"]:
        output(
            " - "
            f"#{visita['id']} "
            f"status={visita.get('status') or '-'} "
            f"tecnico={visita.get('tecnico_nome') or '-'} "
            f"fazenda={visita.get('fazenda') or '-'}"
        )

    output("")
    output("Registros vinculados encontrados:")
    for table, rows in plan["related"].items():
        output(f" - {table}: {len(rows)}")

    output("")
    output("Registros orfaos de teste que serao apagados somente com --confirm:")
    for table, rows in plan["orphan_related"].items():
        output(f" - {table}: {len(rows)}")
        for row in rows:
            output(f"   - #{row['id']} visita_id={row['visita_id']}")


def _connect(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cancela visitas de teste do usuario Danilo Teste com backup seguro."
    )
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Caminho do SQLite.")
    parser.add_argument(
        "--backup-dir",
        default="backups/cleanup",
        help="Diretorio onde o backup sera criado antes do --confirm.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra a previa sem alterar o banco. E o modo padrao.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Executa a limpeza depois de criar backup automatico.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_cleanup(
        args.db_path,
        confirm=bool(args.confirm),
        backup_dir=args.backup_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
