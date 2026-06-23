import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.cleanup_danilo_teste import find_cleanup_plan, run_cleanup
from services.visitas_service import VisitasTecnicasService


def test_dry_run_nao_altera_banco():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "visitas.db"
        service = VisitasTecnicasService(db_path)
        visita = service.criar_visita(
            "5500000000001",
            tecnico_nome="Danilo Teste",
            fazenda="Fazenda Teste",
        )
        service.adicionar_observacao(visita["id"], "Observacao Danilo Teste")

        result = run_cleanup(db_path, confirm=False, output=lambda _message: None)

        assert result["changed"] is False
        assert result["backup_path"] == ""
        assert service.obter_visita(visita["id"])["status"] == "aberta"


def test_confirm_cancela_somente_registros_de_danilo_teste():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "visitas.db"
        backup_dir = Path(temp_dir) / "backups"
        service = VisitasTecnicasService(db_path)
        teste = service.criar_visita(
            "5500000000001",
            tecnico_nome="Danilo Teste",
            fazenda="Fazenda Teste",
        )
        outro = service.criar_visita(
            "5500000000002",
            tecnico_nome="Danilo",
            fazenda="Fazenda Real",
        )
        service.atualizar_campo(outro["id"], "gerente", "Marcelo")

        result = run_cleanup(
            db_path,
            confirm=True,
            backup_dir=backup_dir,
            output=lambda _message: None,
        )

        assert result["changed"] is True
        assert Path(result["backup_path"]).exists()
        assert service.obter_visita(teste["id"])["status"] == "cancelada"
        assert service.obter_visita(outro["id"])["status"] == "aberta"


def test_confirm_apaga_apenas_orfaos_de_danilo_teste():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "visitas.db"
        backup_dir = Path(temp_dir) / "backups"
        service = VisitasTecnicasService(db_path)
        service.ensure_schema()
        visita_real = service.criar_visita(
            "5500000000002",
            tecnico_nome="Marcelo",
            fazenda="Fazenda Real",
        )
        service.adicionar_dado_coletado(
            visita_real["id"],
            "responsavel",
            "Marcelo",
            observacao="Registro real",
        )

        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                """
                INSERT INTO visita_dados_coletados (
                    visita_id, chave, valor, observacao, criado_em
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (9999, "responsavel", "Danilo Teste", "orfao de teste", "2026-06-23"),
            )
            connection.commit()

        plan = find_cleanup_plan(db_path)
        assert len(plan["orphan_related"]["visita_dados_coletados"]) == 1

        run_cleanup(
            db_path,
            confirm=True,
            backup_dir=backup_dir,
            output=lambda _message: None,
        )

        with closing(sqlite3.connect(db_path)) as connection:
            orphan_count = connection.execute(
                "SELECT COUNT(*) FROM visita_dados_coletados WHERE visita_id = 9999"
            ).fetchone()[0]
            real_count = connection.execute(
                "SELECT COUNT(*) FROM visita_dados_coletados WHERE visita_id = ?",
                (visita_real["id"],),
            ).fetchone()[0]

        assert orphan_count == 0
        assert real_count == 1
        assert service.obter_visita(visita_real["id"])["status"] == "aberta"
