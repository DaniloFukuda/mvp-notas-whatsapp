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

    def process_document(
        self,
        document_type: str,
        image_path: str,
        metadata: dict | None = None,
    ) -> NucleusResult:
        if document_type == "1":
            invoice_result = self.invoice_agent.read_qr_code(image_path)
            result = NucleusResult(
                success=invoice_result.success,
                message=invoice_result.message,
                data=invoice_result.qr_code_data,
            )
            invoice_metadata = self._merge_invoice_metadata(
                metadata or {},
                invoice_result.structured_data,
            )
            self._save_result("nota_fiscal", image_path, result, invoice_metadata)
            return result

        if document_type == "2":
            receipt_result = self.receipt_agent.process_receipt(image_path)
            result = NucleusResult(
                success=receipt_result.success,
                message=receipt_result.message,
                data=receipt_result.extracted_data or "",
            )
            receipt_metadata = self._merge_receipt_metadata(
                metadata or {},
                receipt_result.structured_data,
            )
            self._save_result("recibo_comprovante", image_path, result, receipt_metadata)
            return result

        result = NucleusResult(
            success=False,
            message="Tipo de documento inválido. Informe 1 para nota fiscal ou 2 para recibo/comprovante.",
        )
        self._save_result("tipo_invalido", image_path, result, metadata)
        return result

    def _save_result(
        self,
        document_type: str,
        image_path: str,
        result: NucleusResult,
        metadata: dict | None = None,
    ) -> None:
        metadata = metadata or {}
        save_processing_result(
            tipo_documento=document_type,
            caminho_imagem=image_path,
            sucesso=result.success,
            mensagem=result.message,
            dados_extraidos=result.data,
            data_documento=metadata.get("data_documento", ""),
            fornecedor=metadata.get("fornecedor", ""),
            valor=metadata.get("valor_total", ""),
            categoria=metadata.get("categoria", ""),
            responsavel=metadata.get("responsavel", ""),
            observacao=metadata.get("observacao", ""),
            document_kind=metadata.get("document_kind", ""),
            hora_documento=metadata.get("hora_documento", ""),
            favorecido=metadata.get("favorecido", ""),
            id_transacao=metadata.get("id_transacao", ""),
            comentario=metadata.get("comentario", ""),
            conta_origem=metadata.get("conta_origem", ""),
            texto_extraido=metadata.get("texto_extraido", ""),
            needs_review=metadata.get("needs_review", False),
        )

    def _merge_receipt_metadata(self, manual_metadata: dict, ocr_metadata: dict) -> dict:
        merged = dict(manual_metadata)
        ocr_metadata = ocr_metadata or {}

        for key, value in ocr_metadata.items():
            if key == "valor_total":
                if value is not None:
                    merged[key] = value
                continue

            if key == "needs_review":
                merged[key] = bool(value)
                continue

            if value not in (None, ""):
                merged[key] = value

        if "needs_review" not in merged:
            merged["needs_review"] = bool(ocr_metadata)

        return merged

    def _merge_invoice_metadata(self, manual_metadata: dict, ocr_metadata: dict) -> dict:
        merged = dict(manual_metadata)
        ocr_metadata = ocr_metadata or {}

        for key in ("data_documento", "hora_documento", "fornecedor"):
            if not merged.get(key) and ocr_metadata.get(key):
                merged[key] = ocr_metadata[key]

        if not merged.get("valor_total") and ocr_metadata.get("valor_total") is not None:
            merged["valor_total"] = ocr_metadata["valor_total"]

        if not merged.get("observacao") and ocr_metadata.get("forma_pagamento"):
            merged["observacao"] = f"Forma de pagamento: {ocr_metadata['forma_pagamento']}"

        return merged
