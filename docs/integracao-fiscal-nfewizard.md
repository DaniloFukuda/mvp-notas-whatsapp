# Integracao fiscal com NFeWizard

## Objetivo

Evoluir o `mvp-notas-whatsapp` de um organizador de comprovantes para um modulo com dados fiscais estruturados, com foco inicial em consulta, validacao e armazenamento do XML oficial de documentos fiscais.

A primeira fase **nao deve emitir notas fiscais**. O objetivo e reduzir risco operacional e fiscal, mantendo a emissao real para uma etapa posterior, validada em homologacao e com apoio contabil.

## Contexto do projeto atual

O projeto ja recebe documentos pela web e pelo WhatsApp, tenta extrair dados por QR Code/OCR, classifica nota fiscal, recibo ou comprovante, registra resultados em SQLite e exporta dados para revisao/relatorio.

O modulo Ciclus Agro - RDV por WhatsApp ja registra despesas manuais e comprovantes por colaborador, mostra lancamentos em `/ciclus/rdv`, gera relatorio semanal em `/ciclus/rdv/relatorio-semanal` e exporta Excel em `/ciclus/rdv/relatorio-semanal.xlsx`.

A evolucao fiscal deve aproveitar esse fluxo existente e acrescentar uma camada de enriquecimento fiscal, sem quebrar o fluxo atual de recebimento de comprovantes.

## Estrategia recomendada

Criar uma camada fiscal isolada, preferencialmente como servico separado em Node.js, usando NFeWizard para comunicacao com webservices fiscais quando houver certificado e configuracao valida.

Arquitetura sugerida:

```text
WhatsApp / Upload Web / Painel RDV
        ↓
Backend Python atual
        ↓
Cliente fiscal interno
        ↓
Servico fiscal Node.js
        ↓
NFeWizard
        ↓
SEFAZ / Webservices fiscais
```

Essa separacao evita misturar regras fiscais, certificado digital e dependencias Node.js dentro do backend Python principal.

## Fase 1 - Organizador fiscal com XML oficial

### Escopo

1. Detectar chave de acesso de NF-e/NFC-e quando o colaborador enviar comprovante, imagem, PDF, texto ou QR Code.
2. Registrar campos fiscais estruturados no banco.
3. Consultar/baixar XML oficial quando houver chave e credenciais/certificado disponiveis.
4. Comparar dados extraidos por OCR com dados oficiais do XML.
5. Exibir status fiscal no painel RDV.
6. Incluir informacoes fiscais no Excel semanal.
7. Manter fallback manual quando nao houver chave, XML ou leitura confiavel.

### Fora do escopo inicial

- Emissao de NF-e.
- Emissao de NFC-e.
- Emissao de NFS-e.
- Cancelamento, carta de correcao, inutilizacao ou manifestacao automatica.
- Qualquer envio real para ambiente de producao sem homologacao previa.

## Campos fiscais sugeridos

Adicionar os campos abaixo ao lancamento/documento processado, seja na tabela atual ou em tabela relacionada:

```text
fiscal_chave_acesso
fiscal_modelo
fiscal_numero
fiscal_serie
fiscal_data_emissao
fiscal_cnpj_emitente
fiscal_nome_emitente
fiscal_cnpj_destinatario
fiscal_valor_total
fiscal_status
fiscal_origem
fiscal_xml_path
fiscal_xml_sha256
fiscal_consultado_em
fiscal_erro
```

Sugestoes de valores para `fiscal_status`:

```text
sem_chave
chave_detectada
xml_obtido
xml_validado
valor_divergente
emitente_divergente
consulta_falhou
pendente_certificado
pendente_revisao
```

Sugestoes de valores para `fiscal_origem`:

```text
ocr
qr_code
texto_usuario
xml_oficial
manual
```

## Fluxo operacional esperado

1. Colaborador envia foto/documento pelo WhatsApp.
2. Sistema salva o arquivo como ja faz hoje.
3. OCR/QR Code tenta detectar valor, data, fornecedor e chave de acesso.
4. Se detectar chave de acesso, grava `fiscal_status=chave_detectada`.
5. Backend Python chama o servico fiscal Node.js.
6. Servico fiscal consulta/baixa XML quando configurado.
7. Python grava caminho/hash do XML e dados oficiais extraidos.
8. Painel mostra se o documento tem XML oficial, esta pendente ou teve divergencia.
9. Excel semanal ganha colunas fiscais.

## Endpoints internos sugeridos para o servico fiscal

### `GET /health`

Retorna status basico do servico fiscal.

Resposta esperada:

```json
{
  "ok": true,
  "service": "fiscal-service",
  "provider": "nfewizard"
}
```

### `POST /nfce/consultar-chave`

Entrada:

```json
{
  "chave_acesso": "00000000000000000000000000000000000000000000",
  "ambiente": "homologacao"
}
```

Saida sugerida:

```json
{
  "ok": true,
  "chave_acesso": "00000000000000000000000000000000000000000000",
  "status": "xml_obtido",
  "modelo": "65",
  "numero": "123",
  "serie": "1",
  "data_emissao": "2026-06-18T10:00:00-03:00",
  "cnpj_emitente": "00000000000000",
  "nome_emitente": "Fornecedor Exemplo",
  "valor_total": 64.0,
  "xml_sha256": "...",
  "xml_path": "..."
}
```

## Variaveis de ambiente futuras

Nunca commitar certificados, senhas ou XMLs reais.

```env
FISCAL_SERVICE_URL=http://127.0.0.1:3333
FISCAL_SERVICE_TIMEOUT_SECONDS=20
FISCAL_AMBIENTE=homologacao
FISCAL_CERT_A1_PATH=
FISCAL_CERT_A1_PASSWORD=
FISCAL_UF=GO
FISCAL_CNPJ=
```

## Seguranca

- Certificado A1 deve ficar fora do Git.
- Senha do certificado deve ficar somente no ambiente seguro.
- XML fiscal real deve ser tratado como dado sensivel.
- Logs nao devem imprimir XML completo, certificado, senha, token ou dados pessoais completos.
- Banco e backups com XML/dados fiscais devem ser protegidos.

## Primeiro incremento tecnico seguro

1. Criar migracao/tabela para campos fiscais.
2. Adicionar parser local de chave de acesso com testes.
3. Salvar chave detectada no lancamento RDV.
4. Exibir coluna fiscal simples no painel: `sem chave`, `chave detectada`, `pendente certificado`.
5. Exportar a chave no Excel semanal.
6. So depois conectar o servico Node.js/NFeWizard.

### Status em 2026-06-18

O item 2 foi implementado no modulo `services/fiscal_access_key.py`, com testes em `tests/test_fiscal_access_key.py`.

O parser atual:

- aceita NF-e modelo 55 e NFC-e modelo 65 por padrao;
- valida codigo da UF, mes, CNPJ do emitente e digito verificador modulo 11;
- extrai chaves de textos, QR Codes, URLs e OCR com separadores;
- retorna string vazia quando a chave e invalida, evitando gravar lixo fiscal como chave.

O proximo passo e usar esse parser no fluxo RDV para normalizar `analysis["chave_acesso"]` antes de salvar no banco.

## Criterios de aceite da fase 1

- Um comprovante com chave de acesso detectavel deve gravar a chave no banco.
- Um comprovante sem chave deve continuar seguindo o fluxo manual atual.
- O fluxo RDV existente nao pode quebrar.
- Os testes existentes de RDV e WhatsApp devem continuar passando.
- XMLs e certificados reais nao devem ser versionados.
- O painel deve deixar claro quando um documento tem apenas OCR/manual e quando possui dado fiscal oficial.

## Riscos e cuidados

- Emissao fiscal envolve responsabilidade tributaria e deve ser feita apenas em etapa posterior.
- A primeira entrega deve consultar/organizar documentos, nao autorizar venda ou servico.
- Divergencia entre OCR e XML deve ser tratada como revisao, nao como erro fatal.
- Cada tipo de documento tem regras proprias: NF-e, NFC-e, NFS-e e CT-e nao devem ser misturados como se fossem iguais.
