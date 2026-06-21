# Deploy controlado da POC ViraTexto no servidor

## Objetivo

Subir temporariamente a branch `test/viratexto-whatsapp-api` no servidor de producao do Ciclus/RDV para testar a POC do ViraTexto com o webhook real ja configurado na Meta.

A meta do teste e confirmar que respostas vindas do numero ViraTexto `553172280540` chegam ao webhook real e sao gravadas em:

```text
logs/viratexto_test_log.jsonl
```

Nao fazer merge na `main` durante este teste. Nao enviar audio real. Nao usar dados reais ou sensiveis.

## Ambiente documentado

Conforme `docs/deploy-ciclus-vps.md`:

- dominio: `https://ciclus.fukudasistemas.com.br`;
- webhook: `https://ciclus.fukudasistemas.com.br/webhook/whatsapp`;
- aplicacao: `/home/deploy/apps/ciclus-rdv`;
- servico systemd: `ciclus-rdv`;
- processo interno: `127.0.0.1:8001`;
- banco SQLite: `/home/deploy/apps/ciclus-rdv/data/app.db`.

## Riscos

- Durante o teste, o webhook de producao recebera eventos reais da Meta.
- Se `VIRATEXTO_TEST_MODE` ou `VIRATEXTO_PHONE` estiverem errados, respostas do ViraTexto podem cair no fluxo normal de RDV.
- Se qualquer fluxo RDV normal for afetado, restaure a versao anterior imediatamente pelo roteiro de rollback.
- O log da POC pode conter texto recebido do ViraTexto; nao use audio, mensagens ou dados sensiveis.
- Nao imprimir tokens, `.env`, payloads completos ou cabecalhos `Authorization`.

## Preparacao local

No PC local, antes de orientar a VPS:

```bash
git status
git branch --show-current
git push origin test/viratexto-whatsapp-api
```

Confirme que a branch enviada e `test/viratexto-whatsapp-api`.

## Deploy no servidor

### 1. Entrar no servidor

```bash
ssh deploy@SEU_SERVIDOR
```

### 2. Ir para a aplicacao

```bash
cd /home/deploy/apps/ciclus-rdv
```

### 3. Registrar estado atual para rollback

```bash
git rev-parse HEAD
git branch --show-current

echo "BRANCH_ATUAL=$(git branch --show-current)" > rollback_viratexto.txt
echo "COMMIT_ATUAL=$(git rev-parse HEAD)" >> rollback_viratexto.txt
date >> rollback_viratexto.txt
cat rollback_viratexto.txt
```

Guarde esses valores tambem fora do servidor, no registro do teste.

### 4. Backup do banco antes do deploy

O banco documentado e `data/app.db`. Faca backup consistente com SQLite:

```bash
mkdir -p backups/manuais
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
sqlite3 data/app.db ".backup 'backups/manuais/app_pre_viratexto_${TIMESTAMP}.db'"
sqlite3 "backups/manuais/app_pre_viratexto_${TIMESTAMP}.db" "PRAGMA integrity_check;"
ls -lh "backups/manuais/app_pre_viratexto_${TIMESTAMP}.db"
```

Se `sqlite3` nao estiver disponivel, pare e instale/valide a ferramenta antes do deploy. Evite `cp` simples com a aplicacao recebendo eventos.

### 5. Atualizar codigo para a branch da POC

```bash
git fetch origin
git checkout test/viratexto-whatsapp-api
git pull origin test/viratexto-whatsapp-api
```

### 6. Instalar dependencias, se necessario

Use o ambiente virtual documentado no servico:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Se o servidor usa outro Python/venv, use o mesmo caminho configurado no `systemd`.

### 7. Ajustar `.env` sem imprimir tokens

Edite o `.env` com ferramenta segura:

```bash
nano .env
```

Garanta:

```env
VIRATEXTO_TEST_MODE=true
VIRATEXTO_PHONE=553172280540
```

Nao imprima `WHATSAPP_TOKEN`, `WHATSAPP_ACCESS_TOKEN` ou qualquer segredo no terminal.

### 8. Preparar log da POC

```bash
mkdir -p logs
touch logs/viratexto_test_log.jsonl
```

### 9. Rodar testes seguros no servidor

```bash
.venv/bin/python -m pytest tests/test_viratexto_whatsapp.py
.venv/bin/python -m compileall api_whatsapp.py scripts
```

Se `pytest` nao estiver instalado no servidor, instale dependencias de dev apenas se isso fizer parte da rotina segura do ambiente. Caso contrario, rode pelo menos o `compileall`.

### 10. Reiniciar servico da aplicacao

Servico documentado: `ciclus-rdv`.

```bash
sudo systemctl restart ciclus-rdv
```

### 11. Verificar status

```bash
sudo systemctl status ciclus-rdv --no-pager
curl -s http://127.0.0.1:8001/health
curl -I https://ciclus.fukudasistemas.com.br/
curl -I https://ciclus.fukudasistemas.com.br/webhook/whatsapp
```

Uma chamada GET ao webhook sem parametros pode retornar `403`; isso e esperado se nao for `500` e se o endpoint estiver acessivel.

### 12. Acompanhar log da POC

Em um terminal separado no servidor:

```bash
tail -f logs/viratexto_test_log.jsonl
```

### 13. Teste real somente de texto

Depois de confirmar que o servico subiu e o log esta sendo acompanhado, envie apenas texto:

```bash
.venv/bin/python scripts/test_viratexto_whatsapp.py --to "553172280540" --text "Ola, teste de integracao"
```

Nao envie audio ainda.

Se a resposta aparecer em `logs/viratexto_test_log.jsonl`, registre:

- horario;
- `message_id` enviado, se mostrado pelo script;
- tipo de resposta recebido;
- texto recebido;
- se houve qualquer impacto no RDV normal.

## Rollback

Use rollback imediatamente se o RDV normal for afetado, se o servico falhar, ou se a resposta do ViraTexto cair fora do modo de teste.

### 1. Entrar no servidor

```bash
ssh deploy@SEU_SERVIDOR
```

### 2. Ir para a aplicacao

```bash
cd /home/deploy/apps/ciclus-rdv
```

### 3. Ver rollback salvo

```bash
cat rollback_viratexto.txt
```

Anote `BRANCH_ATUAL` e `COMMIT_ATUAL`.

### 4. Voltar para branch/commit anterior

Substitua os placeholders pelos valores do arquivo:

```bash
git checkout BRANCH_ANTERIOR
git reset --hard COMMIT_ANTERIOR
```

Exemplo, se o arquivo indicar `BRANCH_ATUAL=main` e `COMMIT_ATUAL=abc123`:

```bash
git checkout main
git reset --hard abc123
```

### 5. Desativar modo teste no `.env`

Edite:

```bash
nano .env
```

Remova as variaveis ou deixe:

```env
VIRATEXTO_TEST_MODE=false
```

Remova `VIRATEXTO_PHONE` se ele so foi usado para esta POC.

### 6. Reiniciar servico

```bash
sudo systemctl restart ciclus-rdv
```

### 7. Conferir status

```bash
sudo systemctl status ciclus-rdv --no-pager
curl -s http://127.0.0.1:8001/health
curl -I https://ciclus.fukudasistemas.com.br/
```

### 8. Confirmar RDV normal

Envie um comando simples de producao ja conhecido, como `menu`, a partir de um numero cadastrado e confira se o fluxo RDV responde normalmente.

## Encerramento do teste

Ao terminar, mesmo com sucesso:

- registre o resultado do teste;
- mantenha o backup `backups/manuais/app_pre_viratexto_*.db`;
- mantenha `VIRATEXTO_TEST_MODE=true` somente se outro teste imediato for autorizado;
- nao envie audio ate haver uma decisao explicita sobre privacidade, consentimento e retencao de dados.
