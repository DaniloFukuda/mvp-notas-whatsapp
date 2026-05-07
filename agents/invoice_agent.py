from dataclasses import dataclass

import cv2


@dataclass
class InvoiceQRCodeResult:
    success: bool
    qr_code_data: str
    message: str


class InvoiceAgent:
    def read_qr_code(self, image_path: str) -> InvoiceQRCodeResult:
        image = cv2.imread(image_path)

        if image is None:
            return InvoiceQRCodeResult(
                success=False,
                qr_code_data="",
                message="Erro: não foi possível abrir a imagem informada.",
            )

        detector = cv2.QRCodeDetector()
        qr_code_data, _, _ = detector.detectAndDecode(image)

        if qr_code_data:
            return InvoiceQRCodeResult(
                success=True,
                qr_code_data=qr_code_data,
                message="QR Code lido com sucesso.",
            )

        return InvoiceQRCodeResult(
            success=False,
            qr_code_data="",
            message="Não foi possível ler o QR Code. Tente enviar uma imagem mais nítida.",
        )
