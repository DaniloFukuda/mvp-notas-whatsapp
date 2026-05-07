# mvp-notas-whatsapp

MVP em Python para organizar documentos de custo enviados pelo WhatsApp.

Nesta primeira versão, o sistema usa uma arquitetura simples com Núcleo e Agentes:

- `Nucleus`: recebe o tipo do documento e escolhe qual agente deve processar a imagem.
- `InvoiceAgent`: tenta ler o QR Code de uma nota fiscal usando OpenCV.
- `ReceiptAgent`: registra recibos/comprovantes para processamento futuro.

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

## CSV de saída

Os resultados são salvos em `output/documentos_processados.csv`.

O CSV mantém campos técnicos do processamento e campos de negócio que serão preenchidos futuramente pelos agentes:

- `data_processamento`
- `tipo_documento`
- `caminho_imagem`
- `sucesso`
- `mensagem`
- `dados_extraidos`
- `data_documento`
- `fornecedor`
- `valor`
- `categoria`
- `responsavel`
- `observacao`

Durante o MVP, se as colunas do CSV mudarem, o arquivo `output/documentos_processados.csv` pode ser apagado e recriado na próxima execução.
