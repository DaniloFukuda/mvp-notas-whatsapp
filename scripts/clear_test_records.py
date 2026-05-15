import argparse
import sqlite3
from pathlib import Path


DB_PATH = Path("data/app.db")
CSV_PATH = Path("output/documentos_processados.csv")
UPLOADS_DIR = Path("data/documentos/uploads")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Limpa registros de teste do MVP sem remover a estrutura do projeto."
    )
    parser.add_argument("--db", action="store_true", help="Apaga registros do SQLite.")
    parser.add_argument("--csv", action="store_true", help="Limpa o CSV mantendo o cabeçalho.")
    parser.add_argument(
        "--uploads",
        action="store_true",
        help="Apaga arquivos diretamente dentro de data/documentos/uploads/.",
    )
    parser.add_argument("--yes", action="store_true", help="Pula a confirmação manual.")
    args = parser.parse_args()

    if not any((args.db, args.csv, args.uploads)):
        print("Nenhuma ação selecionada. Use --db, --csv e/ou --uploads.")
        return 0

    print_selected_actions(args)
    if not args.yes and not confirm():
        print("Operação cancelada.")
        return 1

    if args.db:
        deleted_rows = clear_database()
        print(f"Registros apagados do SQLite: {deleted_rows}")

    if args.csv:
        csv_cleaned = clear_csv_keep_header()
        print(f"CSV limpo: {'sim' if csv_cleaned else 'não'}")

    if args.uploads:
        deleted_files = clear_uploads()
        print(f"Arquivos de upload apagados: {deleted_files}")

    print("Concluído.")
    return 0


def clear_database() -> int:
    if not DB_PATH.exists():
        print(f"Aviso: banco não encontrado: {DB_PATH}")
        return 0

    with sqlite3.connect(DB_PATH) as connection:
        try:
            cursor = connection.execute("DELETE FROM documentos_processados")
        except sqlite3.OperationalError as exc:
            print(f"Aviso: não foi possível limpar a tabela documentos_processados: {exc}")
            return 0

        connection.commit()
        return cursor.rowcount if cursor.rowcount is not None else 0


def clear_csv_keep_header() -> bool:
    if not CSV_PATH.exists():
        print(f"Aviso: CSV não encontrado: {CSV_PATH}")
        return False

    with CSV_PATH.open(mode="r", encoding="utf-8", newline="") as csv_file:
        header = csv_file.readline()

    with CSV_PATH.open(mode="w", encoding="utf-8", newline="") as csv_file:
        if header:
            csv_file.write(header)

    return True


def clear_uploads() -> int:
    if not UPLOADS_DIR.exists():
        print(f"Aviso: pasta de uploads não encontrada: {UPLOADS_DIR}")
        return 0

    deleted_files = 0
    for path in UPLOADS_DIR.iterdir():
        if not path.is_file():
            continue

        path.unlink()
        deleted_files += 1

    return deleted_files


def confirm() -> bool:
    answer = input(
        "Tem certeza que deseja apagar os registros selecionados? Digite SIM para continuar: "
    )
    return answer == "SIM"


def print_selected_actions(args: argparse.Namespace) -> None:
    selected_actions = []
    if args.db:
        selected_actions.append(f"SQLite: apagar linhas da tabela documentos_processados em {DB_PATH}")
    if args.csv:
        selected_actions.append(f"CSV: manter apenas o cabeçalho em {CSV_PATH}")
    if args.uploads:
        selected_actions.append(f"Uploads: apagar arquivos diretamente dentro de {UPLOADS_DIR}")

    print("Ações selecionadas:")
    for action in selected_actions:
        print(f"- {action}")


if __name__ == "__main__":
    raise SystemExit(main())
