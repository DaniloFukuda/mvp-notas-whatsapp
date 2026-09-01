import sqlite3
from contextlib import closing
from pathlib import Path


def migrate_add_is_test(db_path: str | Path) -> bool:
    """Adiciona is_test uma única vez. Retorna True somente quando alterou."""
    path = Path(db_path)
    with closing(sqlite3.connect(path)) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(visitas_tecnicas)")
        }
        if not columns:
            raise RuntimeError("Tabela visitas_tecnicas não encontrada.")
        if "is_test" in columns:
            return False
        connection.execute(
            "ALTER TABLE visitas_tecnicas "
            "ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0"
        )
        connection.commit()
    return True
