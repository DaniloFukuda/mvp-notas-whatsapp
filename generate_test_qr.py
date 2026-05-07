from pathlib import Path

import qrcode


QR_CODE_TEXT = "https://exemplo.com/teste-nota-fiscal"
OUTPUT_PATH = Path("data/documentos/qrcode_teste.png")


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    image = qrcode.make(QR_CODE_TEXT)
    image.save(OUTPUT_PATH)

    print(f"QR Code salvo em: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
