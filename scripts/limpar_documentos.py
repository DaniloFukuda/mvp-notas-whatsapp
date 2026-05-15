import sqlite3
from pathlib import Path


DB_PATH = Path("data/app.db")
TABLE_NAME = "documentos_processados"
CONFIRMATION_TEXT = "CONFIRMAR"


def main() -> int:
    print(f"Banco SQLite: {DB_PATH}")
    print(f"Tabela que sera limpa: {TABLE_NAME}")

    if not DB_PATH.exists():
        print("Banco nao encontrado. Nenhum registro foi removido.")
        return 0

    try:
        total_before = count_records()
    except sqlite3.OperationalError as exc:
        print(f"Nao foi possivel acessar a tabela {TABLE_NAME}: {exc}")
        return 1

    print(f"Quantidade de registros antes da limpeza: {total_before}")
    answer = input(f"Digite {CONFIRMATION_TEXT} para apagar os registros: ")
    if answer != CONFIRMATION_TEXT:
        print("Operacao cancelada. Nenhum registro foi removido.")
        return 1

    removed_rows = clear_documents()
    print(f"Registros removidos: {removed_rows}")
    return 0


def count_records() -> int:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()

    return int(row[0] if row else 0)


def clear_documents() -> int:
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(f"DELETE FROM {TABLE_NAME}")
        connection.commit()

    return cursor.rowcount if cursor.rowcount is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
