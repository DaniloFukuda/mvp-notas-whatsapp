# Deploy do Ciclus/RDV na VPS

Este documento descreve a arquitetura e o processo de deploy do Ciclus/RDV em
producao. Credenciais, tokens, banco, uploads e certificados devem ser
transferidos e armazenados fora do Git.

## Arquitetura

Fluxo principal:

```text
WhatsApp/Meta
    -> DNS (ciclus.fukudasistemas.com.br)
    -> HTTPS (Let's Encrypt/Certbot)
    -> Nginx
    -> FastAPI gerenciado pelo systemd
    -> SQLite e uploads persistentes
```

Componentes em producao:

- dominio: `https://ciclus.fukudasistemas.com.br`;
- webhook: `https://ciclus.fukudasistemas.com.br/webhook/whatsapp`;
- aplicacao: `/home/deploy/apps/ciclus-rdv`;
- servico systemd: `ciclus-rdv`;
- processo interno: `127.0.0.1:8001`;
- banco: `/home/deploy/apps/ciclus-rdv/data/app.db`;
- uploads: `/home/deploy/apps/ciclus-rdv/data/documentos/uploads`;
- proxy reverso: Nginx;
- HTTPS: Certbot com Let's Encrypt.

O FastAPI nao deve escutar diretamente em uma interface publica. O Nginx
recebe as conexoes HTTP/HTTPS e encaminha as rotas permitidas para
`127.0.0.1:8001`.

## Regras do Nginx

A configuracao deve manter estas regras:

- `location /`: painel protegido por Basic Auth;
- `location = /webhook/whatsapp`: publico e sem Basic Auth, pois a Meta precisa
  validar e entregar eventos;
- `location = /health`: permitido somente a partir de `127.0.0.1`;
- `.env`, `.git`, `data`, `backups` e `uploads`: bloqueados externamente;
- cabecalhos `Host`, `X-Real-IP`, `X-Forwarded-For` e
  `X-Forwarded-Proto`: encaminhados ao FastAPI.

O exemplo versionado esta em
`deploy/examples/ciclus-rdv.nginx.example`. A senha do Basic Auth e os blocos
SSL reais nao pertencem ao repositorio.

## Deploy resumido

1. Criar uma VPS Ubuntu e aplicar atualizacoes de seguranca.
2. Criar o usuario `deploy` e restringir o acesso SSH.
3. Clonar o repositorio em `/home/deploy/apps/ciclus-rdv`.
4. Criar o ambiente virtual e instalar as dependencias:

   ```bash
   cd /home/deploy/apps/ciclus-rdv
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

5. Copiar o `.env` por canal seguro, definir dono `deploy:deploy` e permissao
   `600`. Nunca imprimir ou versionar o arquivo.
6. Restaurar banco e uploads por canal seguro, quando for uma migracao.
7. Instalar o servico systemd a partir do exemplo:

   ```bash
   sudo install -o root -g root -m 0644 \
     deploy/examples/ciclus-rdv.service.example \
     /etc/systemd/system/ciclus-rdv.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now ciclus-rdv
   ```

8. Configurar o Nginx a partir do exemplo, criar o arquivo de Basic Auth fora
   do repositorio, executar `sudo nginx -t` e recarregar o Nginx.
9. Criar o registro DNS `A` de `ciclus.fukudasistemas.com.br` para o IP da VPS
   e aguardar a propagacao.
10. Emitir HTTPS depois de confirmar o HTTP pelo dominio:

    ```bash
    sudo certbot --nginx -d ciclus.fukudasistemas.com.br
    ```

11. Validar localmente a verificacao do webhook usando o verify token carregado
    do `.env`, sem imprimir o valor.
12. Somente depois dos testes, alterar a URL do webhook na Meta para
    `https://ciclus.fukudasistemas.com.br/webhook/whatsapp`, confirmar a
    verificacao e assinar o campo `messages`.

## Checklist de validacao

Na VPS:

```bash
systemctl status ciclus-rdv --no-pager
systemctl status nginx --no-pager
curl -s http://127.0.0.1:8001/health
nginx -t
```

De uma maquina externa:

```bash
curl -I https://ciclus.fukudasistemas.com.br/
curl -I https://ciclus.fukudasistemas.com.br/webhook/whatsapp
```

Resultados esperados:

- o health interno retorna `{"status":"ok","app":"ciclus-rdv"}`;
- o painel retorna `401` sem credenciais e abre depois do Basic Auth;
- o webhook nao envia desafio de Basic Auth;
- uma chamada sem parametros de verificacao pode retornar `400` ou `403`, mas
  nao deve retornar `500`;
- o certificado HTTPS e valido;
- uma mensagem real no WhatsApp, como `menu` ou `resumo`, recebe resposta;
- banco, RDV e uploads restaurados aparecem corretamente no painel.

## O que nunca versionar

- `.env` ou qualquer copia dele;
- access token, verify token, senha de Basic Auth ou credencial SSH;
- banco `app.db`, arquivos `*.db` ou `*.sqlite`;
- uploads, comprovantes, imagens, PDFs e dados pessoais;
- backups e arquivos de hash associados a dados reais;
- chaves privadas ou certificados de `/etc/letsencrypt`;
- configuracoes exportadas da Meta que contenham identificadores sensiveis;
- logs ou payloads com telefone, token, mensagem ou documento real.

Antes de publicar:

```bash
git status --ignored
git diff --check
git diff --cached
git ls-files
```

## Rollback

Durante uma migracao, manter o ambiente anterior disponivel por alguns dias e
nao apagar seus dados ate a producao nova estar validada.

Se o webhook novo falhar:

1. registrar horario, sintomas e logs sem segredos;
2. manter os tokens existentes, salvo evidencia de comprometimento;
3. se necessario, subir temporariamente o ambiente local/ngrok conhecido;
4. voltar a URL do webhook na Meta para a URL anterior;
5. validar novamente o verify token e a assinatura de `messages`;
6. corrigir a VPS sem destruir o banco ou os uploads;
7. repetir o checklist antes de uma nova troca.

Para rollback de codigo na VPS, identificar primeiro uma revisao conhecida,
fazer backup do banco e dos uploads, atualizar o checkout de forma controlada,
reinstalar dependencias se necessario e reiniciar apenas o servico
`ciclus-rdv`. Nao usar comandos destrutivos de Git sobre dados persistentes.
