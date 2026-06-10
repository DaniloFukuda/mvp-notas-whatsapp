import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


WINDOWS_TESSERACT_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


@dataclass
class RDVReceiptAnalysisResult:
    valor_detectado: float | None = None
    data_detectada: str = ""
    fornecedor_detectado: str = ""
    qr_code_text: str = ""
    qr_code_url: str = ""
    chave_acesso: str = ""
    origem_valor: str = ""
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class RDVReceiptAnalysisService:
    def analyze_file(self, file_path: str | Path) -> RDVReceiptAnalysisResult:
        path = Path(file_path)
        reasons: list[str] = []
        qr_text = self._read_qr_code(path, reasons)
        ocr_text = self._read_ocr_text(path, reasons)

        qr_result = self.analyze_text(qr_text, source="qr_code") if qr_text else None
        ocr_result = self.analyze_text(ocr_text, source="ocr") if ocr_text else None
        result = self._merge_results(qr_result, ocr_result)
        result.qr_code_text = qr_text
        result.qr_code_url = _extract_url(qr_text)
        result.chave_acesso = result.chave_acesso or _extract_access_key(qr_text)
        result.reasons = reasons + result.reasons

        if not path.exists():
            result.reasons.append("arquivo_nao_encontrado")
        if result.valor_detectado is None:
            result.reasons.append("valor_nao_detectado")
        return result

    def analyze_text(
        self,
        text: str,
        source: str = "ocr",
    ) -> RDVReceiptAnalysisResult:
        content = unquote(str(text or "")).strip()
        value = _extract_value(content)
        detected_date = _extract_date(content)
        supplier = _extract_supplier(content)
        url = _extract_url(content)
        access_key = _extract_access_key(content)
        reasons = []

        if value is not None:
            reasons.append(f"valor_encontrado_{source}")
        if detected_date:
            reasons.append("data_encontrada")
        if supplier:
            reasons.append("fornecedor_encontrado")
        if url:
            reasons.append("url_fiscal_encontrada")
        if access_key:
            reasons.append("chave_acesso_encontrada")

        confidence = 0.0
        if value is not None:
            confidence = 0.95 if source == "qr_code" else 0.85
        elif any((detected_date, supplier, url, access_key)):
            confidence = 0.5

        return RDVReceiptAnalysisResult(
            valor_detectado=value,
            data_detectada=detected_date,
            fornecedor_detectado=supplier,
            qr_code_text=content if source == "qr_code" else "",
            qr_code_url=url if source == "qr_code" else "",
            chave_acesso=access_key,
            origem_valor=source if value is not None else "",
            confidence=confidence,
            reasons=reasons,
        )

    def _read_qr_code(self, path: Path, reasons: list[str]) -> str:
        if not path.exists() or not path.is_file():
            return ""
        try:
            import cv2
        except ImportError:
            reasons.append("opencv_nao_disponivel")
            return ""

        image = cv2.imread(str(path))
        if image is None:
            reasons.append("arquivo_nao_e_imagem_para_qr")
            return ""

        detector = cv2.QRCodeDetector()
        candidates = [image]
        try:
            grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(
                grayscale,
                None,
                fx=2.0,
                fy=2.0,
                interpolation=cv2.INTER_CUBIC,
            )
            contrast = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            ).apply(grayscale)
            threshold = cv2.adaptiveThreshold(
                grayscale,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                7,
            )
            candidates.extend(
                [
                    grayscale,
                    resized,
                    contrast,
                    threshold,
                ]
            )
            candidates.extend(
                cv2.rotate(grayscale, rotation)
                for rotation in (
                    cv2.ROTATE_90_CLOCKWISE,
                    cv2.ROTATE_180,
                    cv2.ROTATE_90_COUNTERCLOCKWISE,
                )
            )
        except cv2.error:
            pass

        for candidate in candidates:
            try:
                decoded, _, _ = detector.detectAndDecode(candidate)
                if decoded:
                    reasons.append("qr_code_detectado")
                    return decoded.strip()
            except cv2.error:
                continue
        reasons.append("qr_code_nao_detectado")
        return ""

    def _read_ocr_text(self, path: Path, reasons: list[str]) -> str:
        if not path.exists() or not path.is_file():
            return ""
        try:
            import cv2
            import pytesseract
        except ImportError:
            reasons.append("ocr_nao_disponivel")
            return ""

        if WINDOWS_TESSERACT_PATH.exists():
            pytesseract.pytesseract.tesseract_cmd = str(WINDOWS_TESSERACT_PATH)
        try:
            pytesseract.get_tesseract_version()
        except (pytesseract.TesseractNotFoundError, OSError):
            reasons.append("tesseract_nao_configurado")
            return ""

        image = cv2.imread(str(path))
        if image is None:
            reasons.append("arquivo_nao_e_imagem_para_ocr")
            return ""

        texts = []
        try:
            grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            height, width = grayscale.shape[:2]
            receipt = grayscale[
                int(height * 0.03) : int(height * 0.88),
                int(width * 0.08) : int(width * 0.92),
            ]
            payment_area = grayscale[
                int(height * 0.25) : int(height * 0.88),
                int(width * 0.08) : int(width * 0.92),
            ]
            resized = cv2.resize(
                receipt,
                None,
                fx=3.0,
                fy=3.0,
                interpolation=cv2.INTER_CUBIC,
            )
            contrast = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            ).apply(resized)
            threshold = cv2.threshold(
                resized,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU,
            )[1]
            images = [
                image,
                grayscale,
                cv2.resize(
                    grayscale,
                    None,
                    fx=2.0,
                    fy=2.0,
                    interpolation=cv2.INTER_CUBIC,
                ),
                resized,
                contrast,
                threshold,
                cv2.resize(
                    payment_area,
                    None,
                    fx=3.0,
                    fy=3.0,
                    interpolation=cv2.INTER_CUBIC,
                ),
            ]
        except cv2.error:
            images = [image]

        for candidate in images:
            text = self._run_ocr(pytesseract, candidate)
            if text:
                texts.append(text)
                if _has_precise_context_value(text):
                    break
        if texts:
            reasons.append("texto_ocr_detectado")
        else:
            reasons.append("texto_ocr_nao_detectado")
        return "\n".join(texts)

    @staticmethod
    def _run_ocr(pytesseract, image) -> str:
        candidates = []
        for language in (None, "por"):
            for page_mode in (6, 11):
                try:
                    kwargs = {"config": f"--psm {page_mode}"}
                    if language:
                        kwargs["lang"] = language
                    text = pytesseract.image_to_string(image, **kwargs).strip()
                    if text:
                        candidates.append(text)
                except pytesseract.TesseractError as exc:
                    message = str(exc).lower()
                    if language and ("language" in message or language in message):
                        break
                except (OSError, RuntimeError):
                    return ""
        return max(candidates, key=_ocr_text_score, default="")

    @staticmethod
    def _merge_results(
        qr_result: RDVReceiptAnalysisResult | None,
        ocr_result: RDVReceiptAnalysisResult | None,
    ) -> RDVReceiptAnalysisResult:
        qr_result = qr_result or RDVReceiptAnalysisResult()
        ocr_result = ocr_result or RDVReceiptAnalysisResult()
        value_result = qr_result if qr_result.valor_detectado is not None else ocr_result
        return RDVReceiptAnalysisResult(
            valor_detectado=value_result.valor_detectado,
            data_detectada=qr_result.data_detectada or ocr_result.data_detectada,
            fornecedor_detectado=(
                qr_result.fornecedor_detectado or ocr_result.fornecedor_detectado
            ),
            chave_acesso=qr_result.chave_acesso or ocr_result.chave_acesso,
            origem_valor=value_result.origem_valor,
            confidence=max(qr_result.confidence, ocr_result.confidence),
            reasons=qr_result.reasons + ocr_result.reasons,
        )


def _extract_value(text: str) -> float | None:
    patterns = (
        r"\bVALOR\s+TOTAL\b[^\d\r\n]{0,40}(\d{1,9}(?:\.\d{3})*(?:,\d{2})|\d{1,9}(?:\.\d{2}))",
        r"\bVALOR\s+PAGO\b[^\d\r\n]{0,40}(\d{1,9}(?:\.\d{3})*(?:,\d{2})|\d{1,9}(?:\.\d{2}))",
        r"\bV?ALOR\s+INFOR?MADO\b[^\d\r\n]{0,60}(\d{1,9}(?:\.\d{3})*(?:,\d{2})|\d{1,9}(?:\.\d{2}))",
        r"\bTOTAL\s+(?:A\s+PAGAR\s+)?R?\$?\b[^\d\r\n]{0,40}(\d{1,9}(?:\.\d{3})*(?:,\d{2})|\d{1,9}(?:\.\d{2}))",
        r"(?:[?&](?:valor|vNF|total)=)(\d{1,9}(?:[.,]\d{2}))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _to_float(match.group(1))

    url = _extract_url(text)
    if url:
        query = parse_qs(urlparse(url).query)
        for key in ("valor", "vNF", "vnf", "total"):
            if query.get(key):
                return _to_float(query[key][0])

    integer_patterns = (
        r"\bV?ALOR\s+INFOR?MADO\b[^\d\r\n]{0,60}(\d{1,6})\b",
        r"\bVALOR\s+PAGO\b[^\d\r\n]{0,40}(\d{1,6})\b",
        r"\bVALOR\s+TOTAL\b[^\d\r\n]{0,40}(\d{2,6})\b",
    )
    integer_values = []
    for pattern in integer_patterns:
        integer_values.extend(
            int(match)
            for match in re.findall(pattern, text, flags=re.IGNORECASE)
        )
    if integer_values:
        return float(max(integer_values))
    return None


def _has_precise_context_value(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:VALOR\s+TOTAL|VALOR\s+PAGO|V?ALOR\s+INFOR?MADO)\b"
            r"[^\d\r\n]{0,60}\d{1,9}(?:\.\d{3})*[.,]\d{2}\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _ocr_text_score(text: str) -> int:
    normalized = str(text or "").upper()
    score = len(text) // 100
    score += sum(
        10
        for marker in (
            "VALOR TOTAL",
            "VALOR PAGO",
            "VALOR INFORMADO",
            "CARTAO",
            "DEBITO",
            "NFC-E",
        )
        if marker in normalized
    )
    score += 30 * len(
        re.findall(r"\b\d{1,9}(?:\.\d{3})*[.,]\d{2}\b", normalized)
    )
    return score


def _extract_date(text: str) -> str:
    match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2})\b", text)
    if not match:
        return ""
    value = match.group(1)
    for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    return ""


def _extract_supplier(text: str) -> str:
    label_match = re.search(
        r"(?:FORNECEDOR|EMITENTE|RAZAO\s+SOCIAL)\s*[:\-]\s*([^\r\n|&]{3,120})",
        text,
        flags=re.IGNORECASE,
    )
    if label_match:
        return label_match.group(1).strip()

    ignored = ("NFC-E", "NFCE", "CNPJ", "VALOR", "TOTAL", "CHAVE", "HTTP")
    for line in (item.strip() for item in text.splitlines() if item.strip()):
        normalized = line.upper()
        if any(marker in normalized for marker in ignored):
            continue
        if len(line) >= 3 and re.search(r"[A-Za-z]", line):
            return line[:120]
    return ""


def _extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s\"'<>]+", text, flags=re.IGNORECASE)
    return match.group(0).rstrip(".,);") if match else ""


def _extract_access_key(text: str) -> str:
    compact_groups = re.findall(r"(?:\d[\s.-]?){44}", text)
    for group in compact_groups:
        digits = re.sub(r"\D", "", group)
        if len(digits) == 44:
            return digits

    url = _extract_url(text)
    if url:
        query = parse_qs(urlparse(url).query)
        for key in ("chNFe", "chave", "accessKey"):
            for value in query.get(key, []):
                digits = re.sub(r"\D", "", value)
                if len(digits) == 44:
                    return digits
        match = re.search(r"\bp=(\d{44})(?:\||&|$)", url)
        if match:
            return match.group(1)
    return ""


def _to_float(value: str) -> float | None:
    normalized = str(value or "").strip()
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except (TypeError, ValueError):
        return None
