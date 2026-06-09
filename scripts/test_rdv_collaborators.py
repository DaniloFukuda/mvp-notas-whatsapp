import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.rdv_service import DEMO_COLLABORATORS, RDVService


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv_collaborators_test.db")
        collaborators = service.list_collaborators()

        assert {item["nome"] for item in collaborators} == {
            "Danilo",
            "Marcelo",
            "Henrique",
            "Anderson",
        }
        assert {item["telefone_whatsapp"] for item in collaborators} == {
            phone for _, phone in DEMO_COLLABORATORS
        }

        danilo = service.get_collaborator_by_phone("+55 00 00000-0001")
        assert danilo is not None
        assert danilo["nome"] == "Danilo"
        assert danilo["ativo"] == 1

        demo = service.save_collaborator(
            nome="Colaborador Demo",
            telefone_whatsapp="+55 00 00000-0099",
        )
        assert demo["telefone_whatsapp"] == "5500000000099"

        pending = service.create_whatsapp_receipt(
            collaborator_id=demo["id"],
            phone=demo["telefone_whatsapp"],
            input_type="documento",
            file_path="data/documentos/uploads/whatsapp/demo.pdf",
            whatsapp_message_id="wamid.collaborator.test",
            received_at="2026-06-09T09:00:00",
        )
        assert pending["status_fluxo"] == "aguardando_valor"
        assert service.get_open_launch_by_phone(demo["telefone_whatsapp"])["id"] == pending["id"]

        service.save_launch_value(pending["id"], "120,50")
        completed = service.complete_launch_category(pending["id"], "alimentacao")
        assert completed["status_fluxo"] == "completo"
        assert completed["valor"] == 120.5
        assert completed["categoria"] == "alimentacao"

        report = service.weekly_report(
            week="2026-W24",
            collaborator_id=demo["id"],
        )
        assert report["quantidade_lancamentos"] == 1
        assert report["quantidade_comprovantes"] == 1
        assert report["total_geral"] == 120.5
        assert report["por_categoria"]["alimentacao"] == 120.5

        legacy_db = Path(temp_dir) / "rdv_legacy_test.db"
        with closing(sqlite3.connect(legacy_db)) as connection:
            connection.execute(
                """
                CREATE TABLE rdv_despesas (
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
            connection.commit()
        legacy_service = RDVService(legacy_db)
        legacy_service.init_database()
        with closing(sqlite3.connect(legacy_db)) as connection:
            migrated_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(rdv_despesas)")
            }
        assert {
            "colaborador_id",
            "telefone_origem",
            "tipo_entrada",
            "quilometragem",
            "status_fluxo",
            "recebido_em",
        }.issubset(migrated_columns)
        assert len(legacy_service.list_collaborators()) == 4

    print("OK: colaboradores, mapeamento por telefone e relatorio semanal validados.")


if __name__ == "__main__":
    main()
