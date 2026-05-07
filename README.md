# mvp-notas-whatsapp

MVP em Python para organizar documentos de custo enviados pelo WhatsApp.

Nesta primeira versão, o sistema usa uma arquitetura simples com Núcleo e Agentes:

- `Nucleus`: recebe o tipo do documento e escolhe qual agente deve processar a imagem.
- `InvoiceAgent`: tenta ler o QR Code de uma nota fiscal usando OpenCV.
- `ReceiptAgent`: placeholder para futuro processamento de recibos e comprovantes.

## Instalação

```bash
pip install -r requirements.txt
```

## Como usar

```bash
python main.py
```

Depois, informe:

1. O tipo do documento.
2. O caminho da imagem.
