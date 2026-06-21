# Teste ViraTexto via WhatsApp Cloud API

## Objetivo

Esta prova de conceito testa o envio isolado de texto ou audio para o numero WhatsApp do ViraTexto usando a WhatsApp Cloud API. A resposta recebida no webhook e registrada em log local para avaliar se a transcricao ou resumo poderia virar comentario de RDV no futuro.

Este teste nao integra o ViraTexto ao fluxo oficial de RDV e nao deve ser usado em producao.

## Aviso de privacidade

Nao envie dados reais, sensiveis, comprovantes, nomes de clientes, valores reais ou audios de colaboradores. Use somente mensagens e audios artificiais de teste.

## Variaveis de ambiente

Para envio pela Cloud API:

```env
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_API_VERSION=v21.0
```

Tambem sao aceitas as variaveis ja usadas pelo projeto:

```env
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_GRAPH_API_VERSION=v21.0
```

Para registrar respostas do ViraTexto no webhook:

```env
VIRATEXTO_TEST_MODE=true
VIRATEXTO_PHONE=55DDDNUMERO
```

`VIRATEXTO_PHONE` deve ser o numero normalizado que chega no campo `from` do webhook da Meta.

## Enviar texto de teste

Use `--dry-run` primeiro:

```powershell
python scripts/test_viratexto_whatsapp.py --to "55DDDNUMERO" --text "Ola, teste de integracao" --dry-run
```

Depois, com autorizacao para enviar:

```powershell
python scripts/test_viratexto_whatsapp.py --to "55DDDNUMERO" --text "Ola, teste de integracao"
```

## Enviar audio de teste

Formatos aceitos pelo script: `.ogg`, `.opus`, `.mp3`, `.m4a`.

Use `--dry-run` primeiro:

```powershell
python scripts/test_viratexto_whatsapp.py --to "55DDDNUMERO" --audio "caminho/do/audio.ogg" --dry-run
```

Depois, com autorizacao para enviar:

```powershell
python scripts/test_viratexto_whatsapp.py --to "55DDDNUMERO" --audio "caminho/do/audio.ogg"
```

O script mostra apenas informacoes seguras, como status HTTP, id mascarado de midia ou mensagem e erro resumido.

## Acompanhar respostas

Com `VIRATEXTO_TEST_MODE=true`, mensagens recebidas de `VIRATEXTO_PHONE` nao entram no fluxo RDV. Elas sao gravadas em:

```text
logs/viratexto_test_log.jsonl
```

Cada linha contem timestamp, numero remetente, tipo da mensagem, texto recebido quando existir, ids relevantes e payload bruto sanitizado.

No PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_viratexto_log.ps1
```

Esse auxiliar cria `logs/viratexto_test_log.jsonl` vazio se o webhook ainda nao tiver recebido nenhuma resposta.

## Webhook local

O envio pela API pode retornar `status_http: 200` mesmo sem aparecer nada no log local. Isso acontece quando a URL de webhook configurada na Meta nao aponta para este PC.

Para capturar a resposta localmente, exponha o FastAPI com ngrok e configure temporariamente o webhook da Meta para o ambiente local. Veja o roteiro:

```text
docs/teste-viratexto-webhook-local-ngrok.md
```

## Observacao

Esta POC serve apenas para observar o comportamento do ViraTexto e validar a viabilidade tecnica. Qualquer uso no RDV deve virar uma integracao separada, com desenho de seguranca, consentimento, retencao de dados e tratamento de erros.
