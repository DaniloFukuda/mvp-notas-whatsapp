import argparse
import sqlite3
from pathlib import Path


def mark_test_visits(
    db_path: str | Path,
    ids: list[int],
    *,
    apply: bool = False,
    unmark: bool = False,
    _fail_after: int | None = None,
) -> dict:
    visit_ids = sorted({int(value) for value in ids})
    if not visit_ids:
        raise ValueError("Informe ao menos um ID explícito.")
    target = 0 if unmark else 1
    connection = sqlite3.connect(Path(db_path))
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(visitas_tecnicas)")}
        if "is_test" not in columns:
            raise RuntimeError("Migration is_test ainda não aplicada.")
        placeholders = ",".join("?" for _ in visit_ids)
        rows = connection.execute(
            f"SELECT id, status, telefone_origem, is_test FROM visitas_tecnicas WHERE id IN ({placeholders})",
            visit_ids,
        ).fetchall()
        found = {int(row[0]) for row in rows}
        missing = [value for value in visit_ids if value not in found]
        if missing:
            raise ValueError(f"IDs inexistentes: {missing}")
        if not apply:
            return {"dry_run": True, "ids": visit_ids, "target_is_test": target}
        connection.execute("BEGIN IMMEDIATE")
        for index, visit_id in enumerate(visit_ids, start=1):
            connection.execute(
                "UPDATE visitas_tecnicas SET is_test = ? WHERE id = ?",
                (target, visit_id),
            )
            if _fail_after is not None and index >= _fail_after:
                raise RuntimeError("Falha simulada durante marcação.")
        connection.commit()
        return {"dry_run": False, "ids": visit_ids, "target_is_test": target}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Marca visitas explícitas como teste (dry-run por padrão).")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--ids", type=int, nargs="+", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--unmark", action="store_true")
    args = parser.parse_args()
    result = mark_test_visits(args.db, args.ids, apply=args.apply, unmark=args.unmark)
    print(f"DRY_RUN={'false' if args.apply else 'true'}")
    print(f"TARGET_COUNT={len(result['ids'])}")
    print("MISSING_IDS=0")
    print(f"ACTION={'unmark' if args.unmark else 'mark'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
