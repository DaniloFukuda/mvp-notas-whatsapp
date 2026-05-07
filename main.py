from core.nucleus import Nucleus


def main() -> None:
    print("=== Sistema de Organização de Documentos de Custo ===")
    print("1 - Nota fiscal")
    print("2 - Recibo/comprovante")

    document_type = input("Informe o tipo do documento (1 ou 2): ").strip()

    if document_type not in ("1", "2"):
        print("Tipo de documento inválido. Informe 1 para nota fiscal ou 2 para recibo/comprovante.")
        return

    image_path = input("Informe o caminho da imagem do documento: ").strip()

    if not image_path:
        print("Caminho da imagem não informado. Encerrando o programa.")
        return

    nucleus = Nucleus()
    result = nucleus.process_document(document_type, image_path)

    print("Resultado:")
    print(result.message)

    if result.data:
        print("Dados encontrados:")
        print(result.data)


if __name__ == "__main__":
    main()
