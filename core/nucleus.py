from dataclasses import dataclass

from agents.invoice_agent import InvoiceAgent
from agents.receipt_agent import ReceiptAgent
from core.storage import save_processing_result


@dataclass
class NucleusResult:
    success: bool
    message: str
    data: str = ""


class Nucleus:
    def __init__(self) -> None:
        self.invoice_agent = InvoiceAgent()
        self.receipt_agent = ReceiptAgent()

    def process_document(self, document_type: str, image_path: str) -> NucleusResult:
        if document_type == "1":
            invoice_result = self.invoice_agent.read_qr_code(image_path)
            result = NucleusResult(
                success=invoice_result.success,
                message=invoice_result.message,
                data=invoice_result.qr_code_data,
            )
            self._save_result("nota_fiscal", image_path, result)
            return result

        if document_type == "2":
            receipt_result = self.receipt_agent.process_receipt(image_path)
            result = NucleusResult(
                success=receipt_result.success,
                message=receipt_result.message,
                data=receipt_result.extracted_data or "",
            )
            self._save_result("recibo_comprovante", image_path, result)
            return result

        result = NucleusResult(
            success=False,
            message="Tipo de documento inválido. Informe 1 para nota fiscal ou 2 para recibo/comprovante.",
        )
        self._save_result("tipo_invalido", image_path, result)
        return result

    def _save_result(
        self,
        document_type: str,
        image_path: str,
        result: NucleusResult,
    ) -> None:
        save_processing_result(
            tipo_documento=document_type,
            caminho_imagem=image_path,
            sucesso=result.success,
            mensagem=result.message,
            dados_extraidos=result.data,
        )
