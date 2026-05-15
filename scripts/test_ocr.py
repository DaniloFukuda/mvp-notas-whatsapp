import argparse
import re
import sys
from pathlib import Path

import cv2


WINDOWS_TESSERACT_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Teste isolado de OCR para imagens de recibos/comprovantes."
    )
    parser.add_argument("image_path", help="Caminho da imagem que deve ser analisada.")
    args = parser.parse_args()

    image_path = Path(args.image_path)
    if not image_path.exists() or not image_path.is_file():
        print(f"Arquivo não encontrado: {image_path}")
        return 1

    image = cv2.imread(str(image_path))
    if image is None:
        print(f"Não foi possível abrir a imagem com OpenCV: {image_path}")
        return 1

    pytesseract = load_pytesseract()
    if pytesseract is None:
        return 1

    processed_images = generate_preprocessed_images(image)
    extracted_texts: list[str] = []

    for name, processed_image in processed_images:
        print_separator(name)
        text = run_ocr(pytesseract, processed_image)
        print(text or "(nenhum texto extraído)")
        extracted_texts.append(text)

    combined_text = "\n".join(extracted_texts)
    summary = extract_summary(combined_text)

    print_separator("Resumo")
    print(f"Valor encontrado: {summary['valor_total'] or 'não encontrado'}")
    print(f"Data encontrada: {summary['data_documento'] or 'não encontrado'}")
    print(f"Hora encontrada: {summary['hora_documento'] or 'não encontrado'}")

    return 0


def load_pytesseract():
    try:
        import pytesseract
    except ImportError:
        print("pytesseract não está instalado. Rode: py -m pip install pytesseract pillow")
        return None

    # Caminho comum no Windows. Ajuste se o Tesseract OCR estiver em outro local.
    # Exemplo: C:\Program Files\Tesseract-OCR\tesseract.exe
    if WINDOWS_TESSERACT_PATH.exists():
        pytesseract.pytesseract.tesseract_cmd = str(WINDOWS_TESSERACT_PATH)

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        print("O executável do Tesseract OCR não foi encontrado.")
        print("Instale o programa Tesseract OCR e, se necessário, configure o caminho:")
        print(r'C:\Program Files\Tesseract-OCR\tesseract.exe')
        return None

    return pytesseract


def generate_preprocessed_images(image) -> list[tuple[str, object]]:
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


def run_ocr(pytesseract, image) -> str:
    config = "--psm 6"

    for lang in ("por", "eng", None):
        try:
            if lang is None:
                return pytesseract.image_to_string(image, config=config).strip()

            return pytesseract.image_to_string(image, lang=lang, config=config).strip()
        except pytesseract.TesseractError as exc:
            message = str(exc).lower()
            if lang == "por" and ("language" in message or "por" in message):
                print("Idioma português do Tesseract não disponível. Tentando fallback...")
                continue
            if lang == "eng" and ("language" in message or "eng" in message):
                continue
            print(f"Erro ao executar OCR: {exc}")
            return ""
        except RuntimeError as exc:
            print(f"Erro ao executar OCR: {exc}")
            return ""

    return ""


def extract_summary(text: str) -> dict[str, str]:
    return {
        "valor_total": extract_value(text),
        "data_documento": extract_date(text),
        "hora_documento": extract_time(text),
    }


def extract_value(text: str) -> str:
    value_patterns = [
        r"R\$\s*(\d{1,6}(?:[.,]\d{2})?)",
        r"\b(?:VALOR|TOTAL|PAGO|PAGAMENTO)\b[^\d]{0,20}(\d{1,6}(?:[.,]\d{2})?)",
    ]

    for pattern in value_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_decimal(match.group(1))

    return ""


def extract_date(text: str) -> str:
    patterns = [
        r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    return ""


def extract_time(text: str) -> str:
    patterns = [
        r"\b(\d{1,2}:\d{2})\b",
        r"\b(\d{1,2}h\d{2})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def normalize_decimal(value: str) -> str:
    return value.replace(",", ".")


def print_separator(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


if __name__ == "__main__":
    sys.exit(main())
