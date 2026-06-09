import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import web_upload
from services.rdv_service import RDVService


def main() -> None:
    original_service = web_upload.rdv_service
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RDVService(Path(temp_dir) / "rdv_web_test.db")
            web_upload.rdv_service = service
            collaborator = service.get_collaborator_by_phone("5500000000002")
            assert collaborator is not None

            pending = service.create_whatsapp_receipt(
                collaborator_id=collaborator["id"],
                phone=collaborator["telefone_whatsapp"],
                input_type="imagem",
                file_path="data/documentos/uploads/whatsapp/web_demo.jpg",
                whatsapp_message_id="wamid.web.test",
                received_at="2026-06-09T11:00:00",
            )
            service.save_launch_value(pending["id"], "75,25")
            service.complete_launch_category(pending["id"], "pedagio")
            service.create_whatsapp_receipt(
                collaborator_id=collaborator["id"],
                phone=collaborator["telefone_whatsapp"],
                input_type="documento",
                file_path="data/documentos/uploads/whatsapp/pendente_demo.pdf",
                whatsapp_message_id="wamid.web.pending.test",
                received_at="2026-06-09T12:00:00",
            )

            page = web_upload.listar_rdv_ciclus(
                colaborador_id=str(collaborator["id"]),
                status="completo",
                semana="2026-W24",
            )
            assert "Ciclus Agro - RDV por colaborador" in page
            assert collaborator["nome"] in page
            assert "R$ 75,25" in page
            assert "<td>Completo</td>" in page
            assert "<td>Aguardando Valor</td>" not in page

            report = web_upload.relatorio_semanal_rdv_ciclus(
                semana="2026-W24",
                colaborador_id=str(collaborator["id"]),
                status="completo",
            )
            assert report["total_geral"] == 75.25
            assert report["quantidade_comprovantes"] == 1
            assert report["por_colaborador"][collaborator["nome"]] == 75.25
    finally:
        web_upload.rdv_service = original_service

    print("OK: tela e relatorio semanal do RDV por colaborador validados.")


if __name__ == "__main__":
    main()
