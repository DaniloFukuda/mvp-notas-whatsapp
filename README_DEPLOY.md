# Deploy do Ciclus/RDV

Este guia prepara uma futura instalacao em VPS Ubuntu. Ele nao substitui backup,
controle de acesso, HTTPS nem revisao das credenciais.

## Aplicacao

- Entrada FastAPI: `web_upload.py`
- Desenvolvimento local:

```powershell
python -m uvicorn web_upload:app --reload --port 8000
```

- Producao, atras de Nginx:

```bash
python -m uvicorn web_upload:app --host 127.0.0.1 --port 8001 --workers 1
```

Use inicialmente um worker porque a aplicacao grava em SQLite. O exemplo de
`systemd` esta em `deploy_examples/ciclus-rdv.service.example`.

## Configuracao

Variaveis esperadas, sem valores:

- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_BUSINESS_ACCOUNT_ID`
- `WHATSAPP_GRAPH_API_VERSION`
- `WHATSAPP_TEST_RECIPIENT_PHONE`
- `BASE_PUBLIC_URL`

O nome legado `WHATSAPP_TOKEN` nao deve ser usado em uma instalacao nova.

## Dados persistentes

- Banco SQLite: `data/app.db`
- Uploads: `data/documentos/uploads/`
- Backups locais: `backups/`

Nunca envie ao Git `.env`, bancos SQLite, uploads, backups, documentos, imagens,
PDFs, CSVs com dados reais ou tokens.

## Webhook

Exemplo de URL final:

```text
https://ciclus.seudominio.com.br/webhook/whatsapp
```

`/webhook/whatsapp` precisa ficar publico para verificacao e entrega da Meta.
As telas administrativas devem ser protegidas por Basic Auth, VPN, allowlist ou
outro controle de acesso antes de a aplicacao ser exposta.

## Backup antes da migracao

1. Interromper temporariamente gravacoes para obter uma copia consistente.
2. Executar `powershell -File scripts/backup_local.ps1`.
3. Confirmar a copia do banco e dos uploads em `backups/`.
4. Guardar uma copia fora do computador e fora da VPS.
5. Registrar tamanho e hash dos arquivos.
6. Testar a restauracao em uma pasta temporaria.
7. Copiar o `.env` por canal seguro, separadamente e sem versiona-lo.

## Testes depois do deploy

1. Confirmar `GET /health`.
2. Validar a verificacao `GET /webhook/whatsapp`.
3. Enviar um POST controlado ao webhook.
4. Testar mensagem e midia reais.
5. Testar `resumo`, `meu resumo`, `nova viagem`, `status km` e `fim km`.
6. Testar `planilha`, `limpar km` e `confirmar limpar km` em ambiente seguro.
7. Conferir banco, uploads, logs e reinicio automatico do servico.
8. Confirmar que o painel nao esta aberto sem autenticacao.

Antes de trocar a URL na Meta, mantenha o ambiente local disponivel para
rollback.
