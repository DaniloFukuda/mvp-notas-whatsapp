import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unicodedata import normalize

import cv2
import numpy as np


WINDOWS_TESSERACT_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


@dataclass
class InvoiceQRCodeResult:
    success: bool
    qr_code_data: str
    message: str
    needs_manual_key: bool = False
    suggestion: str = ""
    processing_attempts: list[str] = field(default_factory=list)
    structured_data: dict = field(default_factory=dict)


class InvoiceAgent:
    def read_qr_code(self, image_path: str) -> InvoiceQRCodeResult:
        image = self._read_image(image_path)

        if image is None:
            return InvoiceQRCodeResult(
                success=False,
                qr_code_data=self._manual_action_data(["read_image"]),
                message="Erro: não foi possível abrir a imagem informada.",
                needs_manual_key=True,
                suggestion=self._manual_action_suggestion(),
                processing_attempts=["read_image"],
            )

        attempts: list[str] = []

        original_data = self._try_decode_qr(image)
        attempts.append("original")
        if original_data:
            return self._success_result(original_data, attempts, image_path)

        for name, processed_image in self._generate_preprocessed_images(image):
            attempts.append(name)
            qr_code_data = self._try_decode_qr(processed_image)
            if qr_code_data:
                return self._success_result(qr_code_data, attempts, image_path)

        for crop_name, crop in self._generate_candidate_crops(image):
            attempts.append(crop_name)
            qr_code_data = self._try_decode_qr(crop)
            if qr_code_data:
                return self._success_result(qr_code_data, attempts, image_path)

            for processed_name, processed_crop in self._generate_preprocessed_images(crop):
                attempt_name = f"{crop_name}_{processed_name}"
                attempts.append(attempt_name)
                qr_code_data = self._try_decode_qr(processed_crop)
                if qr_code_data:
                    return self._success_result(qr_code_data, attempts, image_path)

        ocr_data = self.enrich_invoice_data_with_ocr(image_path, {})
        return InvoiceQRCodeResult(
            success=False,
            qr_code_data=self._manual_action_data(attempts, ocr_data),
            message="Não foi possível ler o QR Code automaticamente.",
            needs_manual_key=True,
            suggestion=self._manual_action_suggestion(),
            processing_attempts=attempts,
            structured_data=ocr_data,
        )

    def _read_image(self, path: str) -> np.ndarray | None:
        if not path or not path.strip():
            return None

        image_path = Path(path)
        if not image_path.exists() or not image_path.is_file():
            return None

        return cv2.imread(str(image_path))

    def _try_decode_qr(self, image: np.ndarray | None) -> str:
        if image is None or image.size == 0:
            return ""

        detector = cv2.QRCodeDetector()
        qr_code_data, _, _ = detector.detectAndDecode(image)
        if qr_code_data:
            return qr_code_data.strip()

        try:
            decoded, decoded_info, _, _ = detector.detectAndDecodeMulti(image)
        except cv2.error:
            return ""

        if not decoded:
            return ""

        for data in decoded_info:
            if data:
                return data.strip()

        return ""

    def _generate_preprocessed_images(self, image: np.ndarray) -> list[tuple[str, np.ndarray]]:
        grayscale = self._to_grayscale(image)
        resized = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast = clahe.apply(grayscale)

        threshold = cv2.adaptiveThreshold(
            grayscale,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            2,
        )

        return [
            ("grayscale", grayscale),
            ("resized", resized),
            ("contrast", contrast),
            ("threshold", threshold),
        ]

    def _generate_candidate_crops(self, image: np.ndarray) -> list[tuple[str, np.ndarray]]:
        height, width = image.shape[:2]
        if height < 2 or width < 2:
            return []

        bottom_half = image[height // 2 : height, 0:width]
        bottom_third = image[(height * 2) // 3 : height, 0:width]

        center_left = width // 4
        center_right = (width * 3) // 4
        center_top = height // 2
        center_bottom = image[center_top:height, center_left:center_right]

        return [
            ("bottom_half", bottom_half),
            ("bottom_third", bottom_third),
            ("center_bottom", center_bottom),
        ]

    def _extract_access_key_from_text_placeholder(self, _: str = "") -> str:
        return ""

    def _success_result(
        self,
        qr_code_data: str,
        attempts: list[str],
        image_path: str,
    ) -> InvoiceQRCodeResult:
        structured_data = self.enrich_invoice_data_with_ocr(image_path, {})
        result_data = qr_code_data
        if structured_data:
            result_data = json.dumps(
                {
                    "qr_code_data": qr_code_data,
                    "ocr": self._ocr_payload(structured_data),
                },
                ensure_ascii=False,
            )

        return InvoiceQRCodeResult(
            success=True,
            qr_code_data=result_data,
            message="QR Code lido com sucesso.",
            processing_attempts=attempts,
            structured_data=structured_data,
        )

    def _manual_action_data(self, attempts: list[str], ocr_data: dict | None = None) -> str:
        data = {
            "needs_manual_key": True,
            "suggestion": self._manual_action_suggestion(),
            "processing_attempts": attempts,
        }
        if ocr_data:
            data["ocr"] = self._ocr_payload(ocr_data)

        return json.dumps(data, ensure_ascii=False)

    def _manual_action_suggestion(self) -> str:
        return "Envie uma foto mais próxima do QR Code ou informe a chave de acesso da nota fiscal."

    def _to_grayscale(self, image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 2:
            return image

        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def enrich_invoice_data_with_ocr(self, image_path: str, current_data: dict | None) -> dict:
        current_data = current_data or {}
        image = self._read_image(image_path)
        if image is None:
            return {}

        pytesseract = self._load_pytesseract()
        if pytesseract is None:
            return {}

        extracted_texts = []
        for _, processed_image in self._generate_ocr_images(image):
            text = self._run_ocr(pytesseract, processed_image)
            if text:
                extracted_texts.append(text)

        combined_text = "\n".join(extracted_texts).strip()
        if not combined_text:
            return {}

        date_time = extract_date_time_from_text(combined_text)
        ocr_data = {
            "data_documento": date_time.get("data_documento", ""),
            "hora_documento": date_time.get("hora_documento", ""),
            "valor_total": extract_total_value_from_text(combined_text),
            "fornecedor": extract_supplier_from_text(combined_text),
            "forma_pagamento": extract_payment_method_from_text(combined_text),
            "texto_detectado": self._summarize_ocr_text(combined_text),
        }

        enriched = {}
        for key, value in ocr_data.items():
            if key in ("forma_pagamento", "texto_detectado"):
                if value:
                    enriched[key] = value
                continue

            if self._is_empty(current_data.get(key)) and value not in (None, ""):
                enriched[key] = value

        if enriched.get("forma_pagamento") and self._is_empty(current_data.get("observacao")):
            enriched["observacao"] = f"Forma de pagamento: {enriched['forma_pagamento']}"

        return enriched

    def _load_pytesseract(self):
        try:
            import pytesseract
        except ImportError:
            return None

        if WINDOWS_TESSERACT_PATH.exists():
            pytesseract.pytesseract.tesseract_cmd = str(WINDOWS_TESSERACT_PATH)

        try:
            pytesseract.get_tesseract_version()
        except pytesseract.TesseractNotFoundError:
            return None

        return pytesseract

    def _generate_ocr_images(self, image: np.ndarray) -> list[tuple[str, np.ndarray]]:
        grayscale = self._to_grayscale(image)
        resized = cv2.resize(grayscale, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast = clahe.apply(grayscale)

        threshold = cv2.adaptiveThreshold(
            grayscale,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            2,
        )

        return [
            ("grayscale", grayscale),
            ("resized", resized),
            ("contrast", contrast),
            ("threshold", threshold),
        ]

    def _run_ocr(self, pytesseract, image: np.ndarray) -> str:
        config = "--psm 6"

        for lang in ("por", "eng", None):
            try:
                if lang is None:
                    return pytesseract.image_to_string(image, config=config).strip()

                return pytesseract.image_to_string(image, lang=lang, config=config).strip()
            except pytesseract.TesseractError as exc:
                message = str(exc).lower()
                if lang in ("por", "eng") and ("language" in message or lang in message):
                    continue
                return ""
            except RuntimeError:
                return ""

        return ""

    def _summarize_ocr_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:12])[:1000]

    def _ocr_payload(self, data: dict) -> dict:
        return {
            key: value
            for key, value in data.items()
            if key in (
                "data_documento",
                "hora_documento",
                "valor_total",
                "fornecedor",
                "forma_pagamento",
                "texto_detectado",
            )
            and value not in (None, "")
        }

    def _is_empty(self, value: object) -> bool:
        return value in (None, "")


def extract_date_time_from_text(text: str) -> dict:
    data = {"data_documento": "", "hora_documento": ""}

    date_match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", text or "")
    if date_match:
        data["data_documento"] = _normalize_invoice_date(date_match.group(1))

    time_match = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text or "")
    if time_match:
        hour = int(time_match.group(1))
        minute = time_match.group(2)
        second = time_match.group(3)
        data["hora_documento"] = f"{hour:02d}:{minute}:{second}" if second else f"{hour:02d}:{minute}"

    return data


def extract_total_value_from_text(text: str) -> float | None:
    patterns = [
        r"\bVALOR\s+TOTAL\b[^\d]{0,40}(\d{1,9}(?:[.,]\d{2}))",
        r"\bTOTAL\s+R?\$?\b[^\d]{0,40}(\d{1,9}(?:[.,]\d{2}))",
        r"\bVALOR\s+PAGO\b[^\d]{0,40}(\d{1,9}(?:[.,]\d{2}))",
        r"\bVALOR\s+INFORMADO\b[^\d]{0,40}(\d{1,9}(?:[.,]\d{2}))",
    ]

    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return _to_invoice_float(match.group(1))

    return None


def extract_payment_method_from_text(text: str) -> str:
    normalized_text = _normalize_invoice_text(text)
    payment_methods = [
        ("CARTAO DE DEBITO", "Cartao de Debito"),
        ("CARTAO DE CREDITO", "Cartao de Credito"),
        ("PIX", "Pix"),
        ("DINHEIRO", "Dinheiro"),
    ]

    for marker, label in payment_methods:
        if marker in normalized_text:
            return label

    return ""


def extract_supplier_from_text(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    ignored_markers = ("NFC-E", "CNPJ", "VALOR", "TOTAL", "CARTAO", "PIX", "DINHEIRO")

    for line in lines[:6]:
        normalized_line = _normalize_invoice_text(line)
        if any(marker in normalized_line for marker in ignored_markers):
            continue
        if len(line) >= 3 and re.search(r"[A-Za-zÀ-ÿ]", line):
            return line[:120]

    return ""


def _normalize_invoice_date(value: str) -> str:
    for date_format in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return value


def _to_invoice_float(value: str) -> float | None:
    normalized_value = str(value or "").strip()
    if "," in normalized_value:
        normalized_value = normalized_value.replace(".", "").replace(",", ".")

    try:
        return float(normalized_value)
    except (TypeError, ValueError):
        return None


def _normalize_invoice_text(text: str) -> str:
    normalized = normalize("NFKD", text or "")
    return normalized.encode("ascii", "ignore").decode("ascii").upper()
