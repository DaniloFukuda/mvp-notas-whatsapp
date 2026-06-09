import csv
import io
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.rdv_service import RDVService, calculate_week_reference


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        service = RDVService(Path(temp_dir) / "rdv_test.db")
        manual = service.register_manual_expense(
            colaborador="Danilo",
            data_despesa="2026-06-08",
            categoria="combustivel",
            valor="150,75",
            fornecedor="Posto Teste",
            km_inicio="1000",
            km_fim="1125.5",
            observacao="registro unitario",
        )
        service.register_whatsapp_expense(
            colaborador="Marcelo",
            data_despesa="2026-06-09",
            categoria="alimentacao",
            valor="42,30",
            whatsapp_message_id="wamid.test.rdv",
            caminho_arquivo="data/documentos/uploads/whatsapp/teste.jpg",
        )

        assert manual["origem"] == "web"
        assert manual["km_rodado"] == 125.5
        assert manual["semana_referencia"] == calculate_week_reference("2026-06-08")
        assert len(service.list_expenses(colaborador="Danilo")) == 1
        assert len(service.list_expenses(categoria="alimentacao")) == 1

        summary = service.summarize(semana="2026-W24")
        assert summary["quantidade"] == 2
        assert round(summary["total_geral"], 2) == 193.05
        assert round(summary["por_colaborador"]["Danilo"], 2) == 150.75

        assert service.update_review_status(manual["id"], "aprovado")
        approved = service.get_expense(manual["id"])
        assert approved is not None
        assert approved["status_revisao"] == "aprovado"

        exported = list(csv.DictReader(io.StringIO(service.export_csv()), delimiter=";"))
        assert len(exported) == 2
        assert {row["origem"] for row in exported} == {"web", "whatsapp"}

    print("OK: servico RDV validado com SQLite temporario.")


if __name__ == "__main__":
    main()
