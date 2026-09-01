import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.visitas_migration import migrate_add_is_test


def main() -> int:
    parser = argparse.ArgumentParser(description="Adiciona is_test ao schema de visitas.")
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    changed = migrate_add_is_test(args.db)
    print("migration=applied" if changed else "migration=no-op")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
