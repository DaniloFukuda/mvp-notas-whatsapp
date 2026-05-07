from dataclasses import dataclass


@dataclass
class ReceiptProcessingResult:
    success: bool
    extracted_data: str | None
    message: str


class ReceiptAgent:
    def process_receipt(self, image_path: str) -> ReceiptProcessingResult:
        if not image_path.strip():
            return ReceiptProcessingResult(
                success=False,
                extracted_data=None,
                message="Erro: informe o caminho da imagem do recibo/comprovante.",
            )

        return ReceiptProcessingResult(
            success=True,
            extracted_data=f"Arquivo recebido: {image_path}",
            message="Recibo/comprovante recebido e registrado para processamento futuro.",
        )
