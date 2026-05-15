import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unicodedata import normalize

import cv2


WINDOWS_TESSERACT_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


@dataclass
class ReceiptProcessingResult:
    success: bool
    extracted_data: str | None
    message: str
    structured_data: dict = field(default_factory=dict)


class ReceiptAgent:
    def process_receipt(self, image_path: str) -> ReceiptProcessingResult:
        if not image_path.strip():
            return ReceiptProcessingResult(
                success=False,
                extracted_data=None,
                message="Erro: informe o caminho da imagem do recibo/comprovante.",
            )

        image = self._read_image(image_path)
        if image is None:
            data = self._default_data()
            return ReceiptProcessingResult(
                success=True,
                extracted_data=self._to_json(data),
                message="Recibo/comprovante recebido, mas não foi possível abrir a imagem para OCR.",
                structured_data=data,
            )

        pytesseract = self._load_pytesseract()
        if pytesseract is None:
            data = self._default_data()
            return ReceiptProcessingResult(
                success=True,
                extracted_data=self._to_json(data),
                message="Recibo/comprovante recebido, mas OCR não está configurado.",
                structured_data=data,
            )

        extracted_texts = []
        for _, processed_image in self._generate_preprocessed_images(image):
            text = self._run_ocr(pytesseract, processed_image)
            if text:
                extracted_texts.append(text)

        combined_text = "\n".join(extracted_texts).strip()
        data = self._extract_structured_data(combined_text)

        if self._has_primary_data(data):
            message = "Recibo/comprovante analisado automaticamente. Confira os dados extraídos."
        else:
            message = "Recibo/comprovante recebido, mas não foi possível extrair dados principais automaticamente."

        return ReceiptProcessingResult(
            success=True,
            extracted_data=self._to_json(data),
            message=message,
            structured_data=data,
        )

    def _read_image(self, image_path: str):
        path = Path(image_path)
        if not path.exists() or not path.is_file():
            return None

        return cv2.imread(str(path))

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

    def _generate_preprocessed_images(self, image) -> list[tuple[str, object]]:
        grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
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
            ("original", image),
            ("escala de cinza", grayscale),
            ("redimensionada 2x", resized),
            ("contraste melhorado", contrast),
            ("threshold adaptativo", threshold),
        ]

    def _run_ocr(self, pytesseract, image) -> str:
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

    def _extract_structured_data(self, text: str) -> dict:
        return {
            "document_kind": self._classify_document(text),
            "valor_total": self._extract_value(text),
            "data_documento": self._extract_date(text),
            "hora_documento": self._extract_time(text),
            "favorecido": self._extract_favorecido(text),
            "id_transacao": self._extract_id_transacao(text),
            "comentario": self._extract_comentario(text),
            "conta_origem": self._extract_conta_origem(text),
            "texto_extraido": text,
            "needs_review": True,
        }

    def _classify_document(self, text: str) -> str:
        normalized_text = self._normalize_text(text)

        if "PIX" in normalized_text:
            return "comprovante_pix"
        if any(term in normalized_text for term in ("BANCO", "AGENCIA", "CONTA")):
            return "comprovante_bancario"
        if any(term in normalized_text for term in ("CARTAO", "DEBITO", "CREDITO")):
            return "comprovante_cartao"
        if "EXTRATO" in normalized_text or "SALDO" in normalized_text:
            return "extrato_bancario"
        if "TRANSFERENCIA" in normalized_text:
            return "comprovante_transferencia"

        return "desconhecido"

    def _extract_value(self, text: str) -> float | None:
        contextual_patterns = [
            r"\bVALOR\s+ORIGINAL\b[^\d]{0,30}(\d{1,6}(?:[.,]\d{2}))",
            r"\bVALOR\s+TOTAL\b[^\d]{0,30}(\d{1,6}(?:[.,]\d{2}))",
            r"\bVALOR\b[^\d]{0,30}(\d{1,6}(?:[.,]\d{2}))",
            r"\bTOTAL\b[^\d]{0,30}(\d{1,6}(?:[.,]\d{2}))",
            r"\bPAGO\b[^\d]{0,30}(\d{1,6}(?:[.,]\d{2}))",
            r"\bPAGAMENTO\b[^\d]{0,30}(\d{1,6}(?:[.,]\d{2}))",
            r"R\$\s*(\d{1,6}(?:[.,]\d{2}))",
        ]

        for pattern in contextual_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return self._to_float(match.group(1))

        values = [
            self._to_float(match)
            for match in re.findall(r"\b\d{1,6}(?:[.,]\d{2})\b", text)
        ]
        values = [value for value in values if value is not None]

        if not values:
            return None

        return max(values)

    def _extract_date(self, text: str) -> str:
        for pattern in (r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", r"\b(\d{4}-\d{2}-\d{2})\b"):
            match = re.search(pattern, text)
            if match:
                return self._normalize_date(match.group(1))

        return ""

    def _extract_time(self, text: str) -> str:
        match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"

        match = re.search(r"\b(\d{1,2})h(\d{2})\b", text, flags=re.IGNORECASE)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"

        return ""

    def _extract_favorecido(self, text: str) -> str:
        lines = self._clean_lines(text)
        normalized_lines = [self._normalize_text(line) for line in lines]

        for index, normalized_line in enumerate(normalized_lines):
            if "PIX REALIZADO" in normalized_line:
                candidate = self._next_relevant_line(lines, index)
                if candidate:
                    return candidate

        receiver_terms = ("RECEBEDOR", "FAVORECIDO", "DESTINATARIO", "BENEFICIARIO")
        for index, normalized_line in enumerate(normalized_lines):
            if any(term in normalized_line for term in receiver_terms):
                same_line = self._value_after_label(lines[index])
                if same_line:
                    return same_line

                candidate = self._next_relevant_line(lines, index)
                if candidate:
                    return candidate

        return ""

    def _extract_id_transacao(self, text: str) -> str:
        lines = self._clean_lines(text)
        normalized_lines = [self._normalize_text(line) for line in lines]
        terms = ("ID DA TRANSACAO", "CODIGO DE AUTENTICACAO", "AUTENTICACAO")

        for index, normalized_line in enumerate(normalized_lines):
            if any(term in normalized_line for term in terms):
                same_line = self._value_after_label(lines[index])
                if self._looks_like_identifier(same_line):
                    return same_line

                for candidate in lines[index + 1 : index + 4]:
                    if self._looks_like_identifier(candidate):
                        return candidate

        match = re.search(r"\b[A-Z]\d{10,}[A-Z0-9a-z]{8,}\b", text)
        if match:
            return match.group(0)

        return ""

    def _extract_comentario(self, text: str) -> str:
        lines = self._clean_lines(text)
        normalized_lines = [self._normalize_text(line) for line in lines]

        for index, normalized_line in enumerate(normalized_lines):
            if "COMENTARIO" in normalized_line:
                same_line = self._value_after_label(lines[index])
                if same_line:
                    return same_line

                candidate = self._next_relevant_line(lines, index)
                if candidate:
                    return candidate

        return ""

    def _extract_conta_origem(self, text: str) -> str:
        lines = self._clean_lines(text)
        normalized_lines = [self._normalize_text(line) for line in lines]

        for index, normalized_line in enumerate(normalized_lines):
            if "CONTA DE ORIGEM" in normalized_line:
                relevant_lines = []
                same_line = self._value_after_label(lines[index])
                if same_line:
                    relevant_lines.append(same_line)

                for candidate in lines[index + 1 : index + 4]:
                    if self._is_section_break(candidate):
                        break
                    relevant_lines.append(candidate)

                return " - ".join(relevant_lines[:3]).strip()

        return ""

    def _default_data(self) -> dict:
        return {
            "document_kind": "desconhecido",
            "valor_total": None,
            "data_documento": "",
            "hora_documento": "",
            "favorecido": "",
            "id_transacao": "",
            "comentario": "",
            "conta_origem": "",
            "texto_extraido": "",
            "needs_review": True,
        }

    def _has_primary_data(self, data: dict) -> bool:
        return bool(data.get("valor_total") or data.get("data_documento") or data.get("hora_documento"))

    def _to_json(self, data: dict) -> str:
        return json.dumps(data, ensure_ascii=False)

    def _normalize_text(self, text: str) -> str:
        normalized = normalize("NFKD", text or "")
        return normalized.encode("ascii", "ignore").decode("ascii").upper()

    def _clean_lines(self, text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _next_relevant_line(self, lines: list[str], index: int) -> str:
        for candidate in lines[index + 1 : index + 5]:
            if not self._is_section_break(candidate):
                return candidate.strip()
        return ""

    def _is_section_break(self, line: str) -> bool:
        normalized_line = self._normalize_text(line)
        return any(
            term in normalized_line
            for term in (
                "VALOR",
                "DATA",
                "HORARIO",
                "ID DA TRANSACAO",
                "COMENTARIO",
                "CONTA DE ORIGEM",
            )
        )

    def _value_after_label(self, line: str) -> str:
        parts = re.split(r":|-", line, maxsplit=1)
        if len(parts) == 2:
            return parts[1].strip()
        return ""

    def _looks_like_identifier(self, value: str) -> bool:
        value = (value or "").strip()
        if len(value) < 10:
            return False
        return bool(re.search(r"[A-Za-z]", value) and re.search(r"\d", value))

    def _normalize_date(self, value: str) -> str:
        for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, date_format).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return value

    def _to_float(self, value: str) -> float | None:
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None
