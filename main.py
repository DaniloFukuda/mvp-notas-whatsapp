from core.nucleus import Nucleus


def main() -> None:
    print("Sistema de Organização de Documentos de Custo")
    print("1 - Nota fiscal")
    print("2 - Recibo/comprovante")

    document_type = input("Informe o tipo do documento: ").strip()
    image_path = input("Informe o caminho da imagem: ").strip()

    nucleus = Nucleus()
    result = nucleus.process_document(document_type, image_path)

    print(result.message)
    if result.data:
        print("Dados encontrados:")
        print(result.data)


if __name__ == "__main__":
    main()
