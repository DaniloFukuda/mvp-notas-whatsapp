# Operacao do Ciclus/RDV

Guia de rotina para a instalacao em
`/home/deploy/apps/ciclus-rdv`. Execute comandos administrativos com uma conta
autorizada e nunca cole tokens em terminais compartilhados ou chamados de
suporte.

## Verificacoes do dia a dia

Servico e proxy:

```bash
systemctl status ciclus-rdv --no-pager
systemctl status nginx --no-pager
nginx -t
```

Logs:

```bash
journalctl -u ciclus-rdv -n 100 --no-pager
journalctl -u ciclus-rdv -f
```

Health e dominio:

```bash
curl -s http://127.0.0.1:8001/health
curl -I https://ciclus.fukudasistemas.com.br/
curl -I https://ciclus.fukudasistemas.com.br/webhook/whatsapp
```

Espaco em disco:

```bash
df -h
du -sh /home/deploy/apps/ciclus-rdv/data
du -sh /home/deploy/backups
```

Certificado:

```bash
certbot certificates
certbot renew --dry-run
```

Backup:

```bash
bash /usr/local/bin/backup-ciclus-rdv.sh
ls -lh /home/deploy/backups/automaticos
sqlite3 /home/deploy/backups/automaticos/ciclus_app_auto_YYYYMMDD_HHMMSS.db \
  "PRAGMA integrity_check;"
```

## Diagnostico por sintoma

### Site nao abre

1. Conferir DNS e conectividade externa.
2. Executar `systemctl status nginx --no-pager` e `nginx -t`.
3. Testar `curl -s http://127.0.0.1:8001/health`.
4. Conferir `systemctl status ciclus-rdv --no-pager`.
5. Consultar logs do Nginx e do servico.

Um `401` no painel sem credenciais e esperado. Um `403` em `/health` a partir
da internet tambem e esperado.

### WhatsApp nao responde

1. Testar o health interno.
2. Conferir os logs ao enviar uma mensagem real.
3. Verificar se o POST chegou a `/webhook/whatsapp`.
4. Confirmar no painel da Meta se o webhook esta ativo e `messages` continua
   assinado.
5. Verificar expiracao/permissao do access token sem imprimir o token.
6. Confirmar que o numero remetente e o fluxo testado sao aceitos pela
   configuracao da aplicacao.

### Chega POST, mas nao responde

- procurar excecoes logo depois do POST em `journalctl`;
- verificar falha de download da midia ou resposta da Graph API;
- confirmar permissao do token e o `PHONE_NUMBER_ID`;
- conferir espaco e permissoes em `data/`;
- testar um comando simples, como `menu`, antes de testar midia.

Nao registrar payload completo, telefone ou cabecalho `Authorization`.

### Nao chega POST no log

- confirmar a URL exata do webhook na Meta;
- verificar se `messages` esta assinado;
- testar o dominio e o certificado externamente;
- conferir acesso do Nginx para `/webhook/whatsapp`;
- confirmar que essa rota nao herdou Basic Auth;
- consultar logs de acesso e erro do Nginx.

### Erro 401 ou 403 de token Meta

- diferenciar a verificacao GET do envio POST;
- confirmar que o verify token da Meta corresponde ao `.env`, sem exibir os
  valores;
- verificar validade e permissoes do access token usado nas chamadas de saida;
- nao rotacionar tokens por tentativa e erro;
- depois de qualquer ajuste autorizado, repetir a verificacao controlada.

### Erro 500

```bash
journalctl -u ciclus-rdv -n 100 --no-pager
df -h
ls -ld /home/deploy/apps/ciclus-rdv/data
```

Identificar a primeira excecao relacionada ao horario do erro. Nao apagar banco
ou uploads e nao reiniciar repetidamente antes de entender a causa.

### Disco cheio

1. Executar `df -h`.
2. Medir `data` e backups com `du -sh`.
3. Conferir se a retencao automatica esta funcionando.
4. Mover uma copia validada para armazenamento seguro antes de remover backups
   antigos fora da politica.
5. Nao apagar banco, uploads ou backup mais recente sem plano de recuperacao.

### Certificado vencido ou perto do vencimento

```bash
certbot certificates
certbot renew --dry-run
systemctl status certbot.timer --no-pager
nginx -t
```

Conferir DNS, portas 80/443 e logs do Certbot. Depois de uma renovacao manual,
validar o certificado publicamente.

## Backup automatico

- script: `/usr/local/bin/backup-ciclus-rdv.sh`;
- destino: `/home/deploy/backups/automaticos`;
- agendamento: `03:30 UTC` diariamente, equivalente a `00:30` em Brasilia;
- retencao: 14 dias;
- banco: copia consistente criada com o comando `.backup` do SQLite;
- uploads: arquivo `tar.gz`;
- integridade: arquivo SHA256 para banco e uploads.

O backup nao inclui `.env`, tokens ou credenciais.

### Restauracao cuidadosa

Nunca restaurar sem criar e validar um backup pre-restore do estado atual.
Planejar janela de manutencao, pois a restauracao do banco exige impedir
gravacoes concorrentes.

Roteiro:

1. identificar o conjunto de banco, uploads e SHA256 do mesmo timestamp;
2. executar `sha256sum -c` no arquivo de hashes;
3. copiar os artefatos para uma area temporaria;
4. validar o banco com `PRAGMA integrity_check;`;
5. criar backup pre-restore do banco e dos uploads atuais;
6. registrar proprietario e permissoes atuais;
7. parar somente o servico `ciclus-rdv` durante a troca planejada;
8. restaurar banco e uploads nos caminhos persistentes;
9. corrigir dono para `deploy:deploy` e preservar permissoes restritas;
10. iniciar o servico e validar health, painel, RDV e WhatsApp;
11. manter o backup pre-restore ate a validacao completa.

Nao extrair um `tar.gz` diretamente sobre dados ativos sem antes revisar seu
conteudo em um diretorio temporario.

## Antes de mexer na Meta

- confirmar health, Nginx, HTTPS e webhook pela VPS;
- validar o verify token sem imprimir o valor;
- confirmar a URL completa e o ambiente correto;
- registrar configuracao atual para rollback sem armazenar segredos;
- manter a URL anterior disponivel durante a migracao;
- confirmar que existe backup recente e valido;
- evitar alterar simultaneamente URL, token e permissoes.

## Depois de mexer na Meta

- confirmar que a verificacao do webhook foi aceita;
- confirmar que `messages` esta assinado;
- enviar `menu` ou `resumo` por um numero autorizado;
- acompanhar logs sem exibir payloads ou tokens;
- testar envio de comprovante em um fluxo controlado;
- conferir persistencia no painel e no RDV;
- documentar horario e resultado;
- executar rollback se os eventos deixarem de chegar.
