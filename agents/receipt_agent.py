from dataclasses import dataclass


@dataclass
class ReceiptProcessingResult:
    success: bool
    message: str
    data: str = ""


class ReceiptAgent:
    def process(self, image_path: str) -> ReceiptProcessingResult:
        return ReceiptProcessingResult(
            success=False,
            message="O processamento de recibos/comprovantes será implementado depois.",
            data="",
        )
