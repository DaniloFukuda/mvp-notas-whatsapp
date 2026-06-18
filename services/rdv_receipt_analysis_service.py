import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from services.fiscal_access_key import extract_access_keys


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
        if path.suffix.lower() == ".pdf":
            return self._read_pdf_ocr_text(path, reasons)

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
        return _join_unique_texts(texts)

    def _read_pdf_ocr_text(self, path: Path, reasons: list[str]) -> str:
        texts = []
        direct_text = self._extract_pdf_text(path, reasons)
        if direct_text:
            texts.append(direct_text)
            if len(direct_text.strip()) >= 80 and _extract_value(direct_text):
                reasons.append("texto_pdf_detectado")
                return _join_unique_texts(texts)

        try:
            import cv2
            import fitz
            import numpy as np
            import pytesseract
        except ImportError:
            reasons.append("ocr_pdf_render_nao_disponivel")
            return _join_unique_texts(texts)

        if WINDOWS_TESSERACT_PATH.exists():
            pytesseract.pytesseract.tesseract_cmd = str(WINDOWS_TESSERACT_PATH)
        try:
            pytesseract.get_tesseract_version()
        except (pytesseract.TesseractNotFoundError, OSError):
            reasons.append("tesseract_nao_configurado")
            return _join_unique_texts(texts)

        try:
            document = fitz.open(str(path))
            for page in document[:2]:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    pixmap.n,
                )
                if pixmap.n == 3:
                    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                text = self._read_image_ocr_text(cv2, pytesseract, image)
                if text:
                    texts.append(text)
            document.close()
        except Exception:
            reasons.append("pdf_render_ocr_falhou")

        if len(texts) > 1:
            reasons.append("texto_ocr_pdf_detectado")
        elif texts:
            reasons.append("texto_pdf_detectado")
        else:
            reasons.append("texto_ocr_pdf_nao_detectado")
        return _join_unique_texts(texts)

    def _extract_pdf_text(self, path: Path, reasons: list[str]) -> str:
        extractors = (
            self._extract_pdf_text_with_pdfplumber,
            self._extract_pdf_text_with_pypdf,
            self._extract_pdf_text_with_fitz,
        )
        for extractor in extractors:
            text = extractor(path, reasons)
            if text:
                return text
        reasons.append("texto_pdf_direto_nao_detectado")
        return ""

    @staticmethod
    def _extract_pdf_text_with_pdfplumber(path: Path, reasons: list[str]) -> str:
        try:
            import pdfplumber
        except ImportError:
            return ""
        try:
            with pdfplumber.open(str(path)) as pdf:
                return "\n".join(
                    page.extract_text() or "" for page in pdf.pages[:3]
                ).strip()
        except Exception:
            reasons.append("pdfplumber_falhou")
            return ""

    @staticmethod
    def _extract_pdf_text_with_pypdf(path: Path, reasons: list[str]) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        try:
            reader = PdfReader(str(path))
            return "\n".join(
                page.extract_text() or "" for page in reader.pages[:3]
            ).strip()
        except Exception:
            reasons.append("pypdf_falhou")
            return ""

    @staticmethod
    def _extract_pdf_text_with_fitz(path: Path, reasons: list[str]) -> str:
        try:
            import fitz
        except ImportError:
            return ""
        try:
            document = fitz.open(str(path))
            text = "\n".join(page.get_text("text") or "" for page in document[:3])
            document.close()
            return text.strip()
        except Exception:
            reasons.append("pymupdf_texto_falhou")
            return ""

    def _read_image_ocr_text(self, cv2, pytesseract, image) -> str:
        texts = []
        try:
            grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(
                grayscale,
                None,
                fx=2.5,
                fy=2.5,
                interpolation=cv2.INTER_CUBIC,
            )
            contrast = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            ).apply(resized)
            threshold = cv2.threshold(
                contrast,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU,
            )[1]
            images = [image, grayscale, resized, contrast, threshold]
        except cv2.error:
            images = [image]
        for candidate in images:
            text = self._run_ocr(pytesseract, candidate)
            if text:
                texts.append(text)
        return _join_unique_texts(texts)

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
    url = _extract_url(text)
    if url:
        query = parse_qs(urlparse(url).query)
        for key in ("valor", "vNF", "vnf", "total"):
            if query.get(key):
                return _to_float(query[key][0])

    candidates: list[tuple[int, int, float]] = []
    value_pattern = re.compile(
        r"(?P<currency>R\s*\$)?\s*"
        r"(?P<value>\d{1,9}(?:\.\d{3})*(?:,\d{1,2})?|\d{1,9}(?:\.\d{2})?)",
        flags=re.IGNORECASE,
    )
    for match in value_pattern.finditer(text):
        raw_value = match.group("value")
        value = _to_float(raw_value)
        if value is None or value <= 0:
            continue
        if _looks_like_false_value(text, match.start("value"), match.end("value"), raw_value):
            continue

        before = text[max(0, match.start() - 80) : match.start()]
        after = text[match.end() : match.end() + 80]
        context = f"{before} {after}"
        score = 0
        if match.group("currency"):
            score += 100
        if re.search(
            r"\b(valor|total|pago|pix|pagamento|comprovante|informado|pagar)\b",
            context,
            flags=re.IGNORECASE,
        ):
            score += 45
        if "," in raw_value or re.search(r"\.\d{2}$", raw_value):
            score += 20
        if value >= 1:
            score += 5
        candidates.append((score, -match.start("value"), value))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


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
    textual = re.search(
        r"\b(\d{1,2})\s*(?:/|\s+de\s+)\s*"
        r"(janeiro|fevereiro|mar(?:c|\u00e7)o|abril|maio|junho|julho|agosto|setembro|"
        r"outubro|novembro|dezembro)\s*(?:/|\s+de\s+)\s*(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if textual:
        month = _month_number(textual.group(2))
        if month:
            parsed = _valid_date(int(textual.group(3)), month, int(textual.group(1)))
            if parsed:
                return parsed

    for match in re.finditer(
        r"\b(\d{1,2}[/. -]\d{1,2}[/. -]\d{4}|\d{4}-\d{1,2}-\d{1,2})\b",
        text,
    ):
        value = match.group(1)
        for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, date_format).date()
            except ValueError:
                continue
            if parsed <= date.today():
                return parsed.isoformat()
    return ""


def _valid_date(year: int, month: int, day: int) -> str:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return ""
    return parsed.isoformat() if parsed <= date.today() else ""


def _month_number(value: str) -> int:
    normalized = _strip_accents(value).lower()
    months = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    return months.get(normalized, 0)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def _extract_supplier(text: str) -> str:
    known_suppliers = (
        "Mercado Pago",
        "Nu Pagamentos S.A. - Instituicao De Pagamento",
        "Nu Pagamentos S.A.",
    )
    normalized_text = _strip_accents(text).lower()
    for supplier in known_suppliers:
        if _strip_accents(supplier).lower() in normalized_text:
            return supplier

    label_match = re.search(
        r"(?:FORNECEDOR|EMITENTE|RAZAO\s+SOCIAL)\s*[:\-]\s*([^\r\n|&]{3,120})",
        text,
        flags=re.IGNORECASE,
    )
    if label_match:
        return label_match.group(1).strip()

    ignored = ("NFC-E", "NFCE", "CNPJ", "CPF", "VALOR", "TOTAL", "CHAVE", "HTTP")
    for line in (item.strip() for item in text.splitlines() if item.strip()):
        normalized = line.upper()
        if any(marker in normalized for marker in ignored):
            continue
        if len(line) >= 3 and re.search(r"[A-Za-z]", line):
            return line[:120]
    return ""


def _join_unique_texts(texts: list[str]) -> str:
    unique = []
    seen = set()
    for text in texts:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        key = compact.lower()
        if compact and key not in seen:
            unique.append(str(text).strip())
            seen.add(key)
    return "\n".join(unique)


def _looks_like_false_value(text: str, start: int, end: int, raw_value: str) -> bool:
    digits = re.sub(r"\D", "", raw_value)
    if len(digits) > 8:
        return True
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    normalized_line = _strip_accents(line).lower()
    if re.search(r"\d{1,2}[/. -]\d{1,2}[/. -]\d{2,4}", line):
        return True
    if re.search(r"\d{4}-\d{1,2}-\d{1,2}", line):
        return True
    if any(
        marker in normalized_line
        for marker in (
            "cpf",
            "cnpj",
            "telefone",
            "atendimento",
            "transacao",
            "id de transacao",
            "chave",
            "agencia",
            "conta",
        )
    ):
        return True
    if len(re.sub(r"\D", "", line)) >= 9 and "r$" not in normalized_line:
        return True
    return False


def _to_float(value: str) -> float | None:
    normalized = str(value or "").strip().replace("R$", "").replace("R $", "")
    normalized = re.sub(r"\s+", "", normalized)
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except (TypeError, ValueError):
        return None


def _extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s\"'<>]+", text, flags=re.IGNORECASE)
    return match.group(0).rstrip(".,);") if match else ""


def _extract_access_key(text: str) -> str:
    keys = extract_access_keys(text)
    return keys[0] if keys else ""
