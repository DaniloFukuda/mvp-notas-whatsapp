import csv
import os
from datetime import datetime


CSV_PATH = "output/documentos_processados.csv"
CSV_COLUMNS = [
    "data_processamento",
    "tipo_documento",
    "caminho_imagem",
    "sucesso",
    "mensagem",
    "dados_extraidos",
    "data_documento",
    "fornecedor",
    "valor",
    "categoria",
    "responsavel",
    "observacao",
]


def save_processing_result(
    tipo_documento: str,
    caminho_imagem: str,
    sucesso: bool,
    mensagem: str,
    dados_extraidos: str = "",
    data_documento: str = "",
    fornecedor: str = "",
    valor: str = "",
    categoria: str = "",
    responsavel: str = "",
    observacao: str = "",
) -> None:
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    file_exists = os.path.exists(CSV_PATH)

    with open(CSV_PATH, mode="a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "data_processamento": datetime.now().isoformat(timespec="seconds"),
                "tipo_documento": tipo_documento,
                "caminho_imagem": caminho_imagem,
                "sucesso": sucesso,
                "mensagem": mensagem,
                "dados_extraidos": dados_extraidos,
                "data_documento": data_documento,
                "fornecedor": fornecedor,
                "valor": valor,
                "categoria": categoria,
                "responsavel": responsavel,
                "observacao": observacao,
            }
        )
