# Runbook de Migracao para VPS

Este documento prepara a migracao do Ciclus/RDV e do Lucre Agro. Todos os
dominios, repositorios e credenciais abaixo sao placeholders. Revise cada
comando antes de executar. Este runbook nao autoriza contratar VPS, alterar a
Meta ou copiar dados reais.

## Arquitetura

- Uma VPS Ubuntu com usuario operacional `deploy`.
- Ciclus/RDV em `127.0.0.1:8001`.
- Lucre Agro em `127.0.0.1:8002`.
- Nginx como proxy reverso e HTTPS via Certbot.
- `/webhook/whatsapp` publico em cada subdominio.
- Paineis protegidos por Basic Auth, VPN ou allowlist.
- `/health` restrito ao host ou a uma allowlist de monitoramento.
- Um worker por app enquanto a persistencia for SQLite.
- Backup diario do banco e dos uploads, com copia externa futura.

Subdominios e webhooks:

- `rdv.DOMINIO.com.br`
- `lucreagro.DOMINIO.com.br`
- `https://rdv.DOMINIO.com.br/webhook/whatsapp`
- `https://lucreagro.DOMINIO.com.br/webhook/whatsapp`

Diretorios:

- `/home/deploy/apps/ciclus-rdv`
- `/home/deploy/apps/lucre-agro`
- `/home/deploy/backups`
- `/home/deploy/releases`

## Configuracao

Somente nomes; nunca grave valores neste arquivo.

Ciclus/RDV:

- `BASE_PUBLIC_URL`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_BUSINESS_ACCOUNT_ID`
- `WHATSAPP_GRAPH_API_VERSION`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_TEST_RECIPIENT_PHONE`
- `WHATSAPP_VERIFY_TOKEN`

Lucre Agro:

- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_GRAPH_API_VERSION`
- `WHATSAPP_BUSINESS_ACCOUNT_ID` (opcional/diagnostico)
- `WHATSAPP_PUBLIC_WEBHOOK_URL` (opcional/testes)

Dados a preservar:

- Ciclus: `data/app.db` e `data/documentos/uploads/`.
- Lucre: `data/app.db` e `uploads/`.

Nunca enviar ao Git:

- `.env`, `data/`, `uploads/`, `backups/` e `test_docs_local/`.
- Tokens, bancos, documentos reais e arquivos de clientes.

## Backup Final Local

Pare os dois servidores e confirme uma janela sem mensagens. Em cada projeto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/backup_pre_migracao.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/pre_migration_check.ps1
```

Os scripts nao copiam `.env`, nao removem dados e nao fazem upload remoto.
Guarde os caminhos, tamanhos, contagens e SHA-256 exibidos. Copie os artefatos
para armazenamento externo por um canal seguro.

## Comandos para VPS Ubuntu

### Sistema e pacotes

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip nginx ufw apache2-utils certbot python3-certbot-nginx unzip
```

### Usuario e diretorios

```bash
sudo adduser deploy
sudo mkdir -p /home/deploy/apps/ciclus-rdv /home/deploy/apps/lucre-agro /home/deploy/backups /home/deploy/releases
sudo chown -R deploy:deploy /home/deploy/apps /home/deploy/backups /home/deploy/releases
```

Configure SSH por chave antes de desabilitar qualquer metodo de acesso.

### Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

### Clones e branches

Execute os clones como `deploy`:

```bash
cd /home/deploy/apps
git clone REPO_CICLUS_URL ciclus-rdv
git clone REPO_LUCRE_URL lucre-agro

cd /home/deploy/apps/ciclus-rdv
git checkout feature/leitura-qrcode-rdv-ciclus

cd /home/deploy/apps/lucre-agro
git checkout feature/whatsapp-fluxo-operacional-simples
```

### Ambientes Python

```bash
cd /home/deploy/apps/ciclus-rdv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
deactivate

cd /home/deploy/apps/lucre-agro
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

### Diretorios persistentes

```bash
mkdir -p /home/deploy/apps/ciclus-rdv/data/documentos/uploads
mkdir -p /home/deploy/apps/ciclus-rdv/backups
mkdir -p /home/deploy/apps/lucre-agro/data
mkdir -p /home/deploy/apps/lucre-agro/uploads
mkdir -p /home/deploy/apps/lucre-agro/backups
```

### Restauracao

Substitua os placeholders pelos artefatos transferidos por canal seguro:

```bash
cp /CAMINHO_SEGURO/CICLUS_APP_BACKUP.db /home/deploy/apps/ciclus-rdv/data/app.db
unzip /CAMINHO_SEGURO/CICLUS_UPLOADS_BACKUP.zip -d /CAMINHO_TEMPORARIO/ciclus
# Revise a arvore extraida e copie o conteudo para:
# /home/deploy/apps/ciclus-rdv/data/documentos/uploads/

cp /CAMINHO_SEGURO/LUCRE_APP_BACKUP.db /home/deploy/apps/lucre-agro/data/app.db
unzip /CAMINHO_SEGURO/LUCRE_UPLOADS_BACKUP.zip -d /CAMINHO_TEMPORARIO/lucre
# Revise a arvore extraida e copie o conteudo para:
# /home/deploy/apps/lucre-agro/uploads/

sudo chown -R deploy:deploy /home/deploy/apps/ciclus-rdv /home/deploy/apps/lucre-agro
```

Compare SHA-256 e contagem dos arquivos antes de iniciar os apps.

### Arquivos de ambiente

```bash
cd /home/deploy/apps/ciclus-rdv
nano .env
chmod 600 .env

cd /home/deploy/apps/lucre-agro
nano .env
chmod 600 .env
```

Nao cole valores em historico de shell, Git ou logs.

### systemd

Os exemplos estao em `deploy_examples/*.service.example`. Copie e edite as
copias para usar `User=deploy`, `Group=deploy` e os diretorios deste runbook:

```bash
sudo cp /home/deploy/apps/ciclus-rdv/deploy_examples/ciclus-rdv.service.example /etc/systemd/system/ciclus-rdv.service
sudo cp /home/deploy/apps/lucre-agro/deploy_examples/lucre-agro.service.example /etc/systemd/system/lucre-agro.service
sudoedit /etc/systemd/system/ciclus-rdv.service
sudoedit /etc/systemd/system/lucre-agro.service
sudo systemctl daemon-reload
sudo systemctl enable ciclus-rdv.service lucre-agro.service
sudo systemctl start ciclus-rdv.service lucre-agro.service
sudo systemctl status ciclus-rdv.service lucre-agro.service
```

Confirme `--workers 1`, porta `8001` para Ciclus e `8002` para Lucre.

### Basic Auth e Nginx

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-app USUARIO_ADMIN
```

A senha deve ser `SENHA_GERADA_FORA_DO_GIT`. Exemplo a revisar:

```nginx
server {
    listen 80;
    server_name rdv.DOMINIO.com.br;
    client_max_body_size 50m;

    location = /webhook/whatsapp {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /health {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8001;
    }

    location ~ /\.(?!well-known) { deny all; }
    location ~* ^/(data|backups)/ { deny all; }
    location ~* \.(db|sqlite)$ { deny all; }

    location / {
        auth_basic "Acesso restrito";
        auth_basic_user_file /etc/nginx/.htpasswd-app;
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name lucreagro.DOMINIO.com.br;
    client_max_body_size 50m;

    location = /webhook/whatsapp {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /health {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8002;
    }

    location ~ /\.(?!well-known) { deny all; }
    location ~* ^/(data|backups)/ { deny all; }
    location ~* \.(db|sqlite)$ { deny all; }

    location / {
        auth_basic "Acesso restrito";
        auth_basic_user_file /etc/nginx/.htpasswd-app;
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Salve em `/etc/nginx/sites-available/apps-whatsapp`, habilite e teste:

```bash
sudo ln -s /etc/nginx/sites-available/apps-whatsapp /etc/nginx/sites-enabled/apps-whatsapp
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d rdv.DOMINIO.com.br -d lucreagro.DOMINIO.com.br
sudo certbot renew --dry-run
```

Nginx nao lista diretorios por padrao; nao habilite `autoindex`.

## Testes Antes da Meta

- [ ] `curl http://127.0.0.1:8001/health`
- [ ] `curl http://127.0.0.1:8002/health`
- [ ] Confirmar que os `/health` externos retornam `403`, salvo allowlist.
- [ ] Testar POST simulado em cada `/webhook/whatsapp`.
- [ ] Confirmar que os webhooks nao pedem Basic Auth.
- [ ] Confirmar Basic Auth nos paineis e downloads.
- [ ] Confirmar `404` em `/webhook/whatsapp/lucreagro` no Lucre.
- [ ] Confirmar `404` em `/webhook/whatsapp/test` no Lucre.
- [ ] Conferir logs sem tokens e sem payloads sensiveis completos.

## Virada da Meta

Somente depois dos testes:

- [ ] Confirmar janela sem uso e backup final.
- [ ] Validar GET de verificacao no painel da Meta.
- [ ] Atualizar cada numero para seu webhook correto.
- [ ] Enviar mensagem e midia reais.
- [ ] Ciclus: `resumo`, `meu resumo`, `nova viagem`, `status km`, `fim km`,
      `planilha`, `limpar km` e `confirmar limpar km`.
- [ ] Lucre: `ajuda`, `documentos`, envio de documento, curadoria, pendencias
      e respostas `approved`, `rejected` e `needs_review`.

## Rollback

- Manter local/ngrok pronto por 24 a 48 horas.
- Se a VPS falhar, voltar a Meta para a URL anterior.
- Parar os servicos com `sudo systemctl stop ciclus-rdv lucre-agro`.
- Conferir `journalctl` sem divulgar segredos.
- Restaurar `app.db` e uploads somente a partir de backup validado.
- Nunca remover a ultima copia local ou externa durante o rollback.

## Decisoes Pendentes sobre Dados

Ciclus/RDV:

- [ ] Decidir se o `data/app.db` atual vai para producao.
- [ ] Decidir se os 23 uploads atuais vao.
- [ ] Decidir se KM de teste sera limpo antes do backup final.
- [ ] Confirmar se os dados do tio ja sao reais.

Lucre Agro:

- [ ] Decidir se o banco atual vai para producao.
- [ ] Decidir se os 58 uploads atuais vao.
- [ ] Manter `test_docs_local/` fora da VPS.
- [ ] Escolher migracao vazia ou limpeza seletiva dos dados simulados.

## Riscos

- Painel sem autenticacao ou downloads expostos.
- SQLite com mais de um worker ou gravacoes durante o backup.
- Uploads e logs contendo dados sensiveis.
- Meta configurada com subdominio ou rota errados.
- Uso de fallback ou token conhecido; isso e proibido em producao.
- Rollback local indisponivel cedo demais.
