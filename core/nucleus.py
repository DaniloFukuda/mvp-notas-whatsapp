from dataclasses import dataclass

from agents.invoice_agent import InvoiceAgent
from agents.receipt_agent import ReceiptAgent


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
            result = self.invoice_agent.read_qr_code(image_path)
            return NucleusResult(
                success=result.success,
                message=result.message,
                data=result.qr_code_data,
            )

        if document_type == "2":
            result = self.receipt_agent.process(image_path)
            return NucleusResult(
                success=result.success,
                message=result.message,
                data=result.data,
            )

        return NucleusResult(
            success=False,
            message="Tipo de documento inválido. Informe 1 para nota fiscal ou 2 para recibo/comprovante.",
        )
