# mvp-notas-whatsapp

Sistema MVP para receber, processar, organizar e revisar documentos de custo, como notas fiscais, recibos, comprovantes, documentos enviados por upload web e documentos enviados pelo WhatsApp.

O projeto nasceu como um experimento simples para leitura de nota fiscal por imagem, mas evoluiu para um fluxo local mais completo de captura, processamento, conferencia manual, armazenamento e exportacao.

## Objetivo

O objetivo do `mvp-notas-whatsapp` e apoiar a organizacao de documentos de custo em um fluxo pratico:

- receber documentos pela interface web;
- receber imagens e documentos pelo WhatsApp Cloud API;
- tentar extrair dados por QR Code e OCR;
- classificar o documento como nota fiscal, recibo ou comprovante;
- registrar os resultados em SQLite;
- manter apoio/exportacao em CSV;
- permitir revisao manual, filtros, correcao e exclusao de registros.

Este ainda e um MVP local. Ele foi pensado para aprendizado, validacao de fluxo e apoio operacional, nao como sistema final de producao.

## Arquitetura

A arquitetura atual combina componentes simples:

- **FastAPI**: expoe a aplicacao web, as telas de upload/revisao e rotas auxiliares de API.
- **Nucleo**: coordena o processamento, escolhe o agente correto e salva os resultados.
- **Agentes**: encapsulam a logica de leitura de documentos. Ha agente para nota fiscal e agente para recibo/comprovante.
- **SQLite**: banco local usado para registrar documentos processados, estados de conferencia, metadados e controle de duplicidade.
- **CSV**: usado como apoio historico/exportacao, especialmente para consumo em planilhas.
- **WhatsApp Cloud API**: canal de entrada para mensagens, imagens e documentos enviados pelo WhatsApp.
- **n8n/ngrok**: podem ser usados em testes e integracoes para expor webhook local, automatizar chamadas ou simular fluxos externos.

## Funcionalidades atuais

- Upload manual de documentos pela web.
- Processamento de nota fiscal por QR Code e OCR complementar.
- Processamento de recibo/comprovante por OCR.
- Registro dos documentos em SQLite.
- Registro e apoio em CSV.
- Tela `/documentos` para listar documentos validos/processados.
- Tela `/documentos/erros` para revisar registros incompletos, invalidos ou com falha.
- Edicao e conferencia manual dos dados extraidos.
- Exclusao/apagar registros pela interface.
- Filtros por data, mes/ano, hora, tipo, categoria e responsavel/origem.
- Exportacao CSV dos documentos filtrados.
- Integracao com WhatsApp Cloud API.
- Webhook de verificacao do WhatsApp.
- Recebimento de imagens/documentos pelo WhatsApp.
- Classificacao por legenda/caption enviada junto com a midia.
- Deduplicacao por `whatsapp_message_id` e `whatsapp_image_sha256`.
- Tratamento de erro quando nao for possivel baixar midia do WhatsApp.
- Resposta automatica pelo WhatsApp quando possivel.
- Mascaramento/cuidado com token, telefone, IDs e logs sensiveis.

## Como rodar localmente

Crie e ative um ambiente virtual:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instale as dependencias:

```powershell
pip install -r requirements.txt
```

Rode a aplicacao web principal:

```powershell
python -m uvicorn web_upload:app --reload
```

Depois acesse a aplicacao local no navegador, normalmente em:

```text
http://127.0.0.1:8000
```

Arquivos auxiliares:

- `web_upload.py`: aplicacao web principal, com upload, listagem, filtros, edicao, erros, exportacao CSV e rotas do webhook.
- `api.py`: API auxiliar para processamento por chamadas HTTP.
- `api_whatsapp.py`: rotas e funcoes de integracao com WhatsApp Cloud API, incluindo verificacao de webhook, recebimento de mensagens e download de midia.

## Variaveis de ambiente

Crie um arquivo `.env` local com os valores necessarios para o WhatsApp e integracoes. Nunca commite esse arquivo.

Variaveis usadas pelo projeto:

```env
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_GRAPH_API_VERSION=
WHATSAPP_TEST_RECIPIENT_PHONE=
BASE_PUBLIC_URL=
```

Observacoes:

- `WHATSAPP_VERIFY_TOKEN` deve bater com o token configurado no painel do webhook da Meta.
- `WHATSAPP_TOKEN` e um token sensivel e deve ficar somente no ambiente local/seguro.
- `WHATSAPP_PHONE_NUMBER_ID` identifica o numero usado pela Cloud API.
- `WHATSAPP_GRAPH_API_VERSION` define a versao da Graph API usada nas chamadas.
- `WHATSAPP_TEST_RECIPIENT_PHONE` pode ser usado por scripts de teste de envio.
- `BASE_PUBLIC_URL` ajuda a montar links publicos quando o webhook estiver exposto via ngrok ou ambiente similar.

## Seguranca e privacidade

Este projeto lida com documentos que podem conter dados pessoais, fiscais, financeiros e de clientes. Trate todos os arquivos locais como sensiveis.

Nao subir para o Git:

- `.env`;
- banco SQLite local, como `data/app.db`;
- uploads;
- imagens de notas reais;
- recibos, comprovantes ou PDFs de clientes;
- CSV com dados reais;
- arquivos dentro de `output/` com dados processados;
- qualquer token, telefone real, ID de midia ou payload sensivel.

Mantenha fora do Git:

- `data/app.db`;
- `uploads/`;
- `data/documentos/uploads/`;
- `output/`;
- imagens, PDFs e documentos locais sensiveis.

Antes de qualquer push, revise sempre:

```powershell
git status --ignored
git ls-files
```

## Estrutura resumida

- `agents/`: agentes de processamento, como nota fiscal e recibo/comprovante.
- `core/`: nucleo, persistencia SQLite e apoio de armazenamento/exportacao.
- `services/`: servicos de orquestracao para processar arquivos e normalizar entradas.
- `scripts/`: scripts auxiliares de diagnostico, teste e limpeza local.
- `api.py`: API auxiliar para processar documentos por HTTP.
- `api_whatsapp.py`: integracao com WhatsApp Cloud API e webhook.
- `web_upload.py`: aplicacao web principal em FastAPI.
- `requirements.txt`: dependencias Python do projeto.
- `.env.example`: exemplo de variaveis de ambiente, sem valores reais.
- `output/`: saidas locais, como CSVs gerados. Deve permanecer fora do Git quando contiver dados reais.
- `data/`: banco local, arquivos auxiliares e uploads. Deve ser tratado como area sensivel.

## Fluxo de uso

1. O usuario envia um arquivo pelo upload web ou pelo WhatsApp.
2. O sistema identifica o tipo do documento, usando formulario, legenda ou fluxo de API.
3. O nucleo direciona o arquivo ao agente adequado.
4. O agente tenta extrair dados por QR Code e/ou OCR.
5. O resultado e salvo no SQLite e pode ser apoiado por CSV.
6. O usuario revisa documentos validos em `/documentos`.
7. O usuario revisa falhas ou registros incompletos em `/documentos/erros`.
8. Os registros podem ser filtrados, editados, apagados e exportados em CSV.

## Historico de evolucao

- MVP inicial para processar nota fiscal a partir de imagem.
- Suporte a recibos e comprovantes.
- Inclusao de SQLite e painel web.
- Leitura complementar por OCR.
- Separacao de documentos com erro ou pendentes de conferencia.
- Integracao com WhatsApp Cloud API.
- Filtros por data, mes/ano, hora, tipo, categoria e origem/responsavel.
- Exportacao CSV dos documentos filtrados.
- Limpeza e protecao de arquivos sensiveis no Git.

## Relacao com o projeto lucreagro-ficha-unica

Este projeto serviu como base pratica para aprendizados reutilizados no projeto `lucreagro-ficha-unica`, especialmente em:

- upload de arquivos;
- organizacao documental;
- uso de SQLite;
- painel web simples;
- integracao com WhatsApp;
- seguranca com arquivos locais e dados sensiveis.

## Aviso

O `mvp-notas-whatsapp` e um projeto de MVP e estudo aplicado. Para uso em producao, ainda seria necessario reforcar autenticacao, autorizacao, auditoria, backups, tratamento de dados pessoais, armazenamento seguro de arquivos e politicas formais de retencao.
