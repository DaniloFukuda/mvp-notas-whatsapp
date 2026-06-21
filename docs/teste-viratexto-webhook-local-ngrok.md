# Teste local do webhook ViraTexto com ngrok

## Objetivo

Este roteiro serve para receber no PC local a resposta do ViraTexto enviada pela Meta no webhook `/webhook/whatsapp`, sem deploy e sem merge.

## Por que o envio funcionou e o log ficou vazio

O envio pela WhatsApp Cloud API pode funcionar mesmo quando o webhook local nao recebe nada. O script de envio chama diretamente a API da Meta, mas a resposta do ViraTexto volta para a URL de webhook configurada no painel da Meta. Se essa URL aponta para producao, VPS ou outro ambiente, o arquivo local `logs/viratexto_test_log.jsonl` no PC fica vazio.

Para capturar a resposta no PC, exponha o servidor local com ngrok e configure temporariamente essa URL na Meta.

## Roteiro guiado

Voce pode usar o script auxiliar para conduzir a POC local com validacoes e travas:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_viratexto_local_poc.ps1 -CheckOnly
```

Para rodar o roteiro completo sem envio automatico:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_viratexto_local_poc.ps1
```

Para rodar o roteiro e, depois de confirmar `PRONTO`, chamar o envio real de texto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_viratexto_local_poc.ps1 -SendText
```

Mesmo com `-SendText`, o script de envio ainda pede a confirmacao digitada `ENVIAR`.

## Servidor local

O projeto usa FastAPI. O app principal local esta em `web_upload.py` e inclui o router de `api_whatsapp.py`, onde ficam as rotas `/webhook/whatsapp`.

Comando local:

```powershell
python -m uvicorn web_upload:app --reload --host 127.0.0.1 --port 8000
```

Porta local usada neste roteiro: `8000`.

Em outro terminal, confira se a rota responde:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_local_webhook.ps1 -Port 8000
```

Se o endpoint responder `403` por falta de parametros `hub.*`, isso e um bom sinal: o servidor local esta de pe e a rota existe.

## Log local

Abra um terminal separado para acompanhar o log:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_viratexto_log.ps1
```

O script cria `logs/viratexto_test_log.jsonl` se ele ainda nao existir.

## ngrok

Com o servidor local rodando na porta 8000, abra outro terminal:

```powershell
ngrok http 8000
```

Copie a URL HTTPS gerada pelo ngrok. A URL temporaria do webhook sera:

```text
https://SEU-NGROK/webhook/whatsapp
```

## Configurar temporariamente na Meta

No painel da Meta para o app WhatsApp:

1. Abra o app no Meta for Developers.
2. Entre em WhatsApp > Configuration ou Webhooks, conforme a tela disponivel.
3. Edite a Callback URL do webhook.
4. Informe a URL do ngrok com `/webhook/whatsapp`.
5. Use o mesmo verify token configurado em `WHATSAPP_VERIFY_TOKEN`.
6. Salve e confirme a verificacao.

Cuidado principal: durante esse teste, mensagens reais recebidas pelo numero WhatsApp podem ir para o ambiente local exposto pelo ngrok.

## Teste de texto

Depois de confirmar que o webhook da Meta esta apontando para o ngrok e que o watcher esta aberto, envie o texto real com:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_viratexto_text_test.ps1 -SendReal
```

O script ainda pedira confirmacao digitada `ENVIAR`.

Nao envie audio ainda. Primeiro confirme que a resposta de texto do ViraTexto aparece em `logs/viratexto_test_log.jsonl`.

## Restaurar webhook original

Ao terminar:

1. Volte ao painel da Meta.
2. Restaure a Callback URL original do webhook, por exemplo a URL de producao usada antes do teste.
3. Confirme que a verificacao passou.
4. Encerre o ngrok.
5. Encerre o servidor local se nao for mais usar.

Nao deixe o webhook apontado para ngrok depois do teste.
