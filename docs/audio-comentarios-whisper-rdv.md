# Comentarios por audio no RDV com Whisper

## Objetivo

Esta feature permite testar comentarios de RDV enviados por audio no WhatsApp e transcritos pelo proprio sistema com Whisper local. A integracao fica atras de feature flag e nao usa Blip/ViraTexto.

O primeiro uso previsto e apos concluir um comprovante de RDV: o colaborador pode digitar um comentario ou enviar audio. Quando o audio e transcrito, o sistema pede confirmacao antes de salvar no campo `observacao` do lancamento RDV.

## Dependencias

As dependencias de transcricao ficam separadas para nao pesar a instalacao principal:

```powershell
python -m pip install -r requirements-transcription.txt
```

O Whisper tambem precisa do `ffmpeg` instalado no ambiente.

## Instalar ffmpeg no Windows

```powershell
winget install Gyan.FFmpeg
python -m pip install -r requirements-transcription.txt
python scripts/test_whisper_transcricao.py --audio "C:\caminho\audio.ogg"
```

Reabra o terminal depois de instalar o ffmpeg se o comando nao aparecer no PATH.

## Instalar ffmpeg no Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
.venv/bin/python -m pip install -r requirements-transcription.txt
.venv/bin/python scripts/test_whisper_transcricao.py --audio "/caminho/audio.ogg"
```

## Variaveis de ambiente

```env
AUDIO_TRANSCRIPTION_ENABLED=false
AUDIO_TRANSCRIPTION_PROVIDER=whisper_local
WHISPER_MODEL=tiny
WHISPER_LANGUAGE=pt
WHISPER_MAX_AUDIO_MB=50
WHISPER_MAX_AUDIO_SECONDS=1800
WHISPER_CHUNK_SECONDS=60
WHISPER_KEEP_AUDIO=false
WHISPER_TMP_DIR=tmp/audio_transcriptions
TRANSCRIPTION_REVIEW_ENABLED=true
TRANSCRIPTION_REVIEW_PROVIDER=local
TRANSCRIPTION_REVIEW_MODE_DEFAULT=revisada
VISITA_DESCRICAO_MAX_CHARS=5000
VISITA_OBSERVACAO_MAX_CHARS=20000
VISITA_OBSERVACAO_TOTAL_MAX_CHARS=80000
FOTO_COMENTARIO_MAX_CHARS=2000
```

Comportamento:

- `AUDIO_TRANSCRIPTION_ENABLED=false`: audio recebido nao tenta transcrever.
- `AUDIO_TRANSCRIPTION_PROVIDER=whisper_local`: usa Whisper local.
- `WHISPER_MODEL=tiny`: modelo carregado sob demanda e reutilizado.
- `WHISPER_LANGUAGE=pt`: idioma padrao da transcricao.
- `WHISPER_MAX_AUDIO_MB=50`: limite de tamanho do arquivo.
- `WHISPER_MAX_AUDIO_SECONDS=1800`: limite de duracao (30 minutos).
- `WHISPER_CHUNK_SECONDS=60`: divide audios longos em partes temporarias.
- `WHISPER_KEEP_AUDIO=false`: remove audio temporario depois da transcricao.
- `WHISPER_TMP_DIR`: diretorio usado para baixar audio temporario da Meta.
- `TRANSCRIPTION_REVIEW_ENABLED=true`: aplica revisão local antes de responder ou salvar. Quando `false`, usa somente a transcrição bruta.
- `TRANSCRIPTION_REVIEW_PROVIDER=local`: seleciona a camada local. Valores futuros
  como `openai` e `gemini` só funcionam quando um provider for configurado e
  injetado explicitamente; não há chamada externa nesta versão.
- `TRANSCRIPTION_REVIEW_MODE_DEFAULT=revisada`: modo usado em sessões antigas ou
  sem seleção válida.
- `VISITA_DESCRICAO_MAX_CHARS=5000`: limite da descrição principal da visita.
- `VISITA_OBSERVACAO_MAX_CHARS=20000`: limite de cada observação geral.
- `VISITA_OBSERVACAO_TOTAL_MAX_CHARS=80000`: teto de segurança de uma transcrição enviada para observações.
- `FOTO_COMENTARIO_MAX_CHARS=2000`: limite do comentário individual de foto.

Áudios longos podem produzir texto maior que uma única observação. Nesse caso, a
transcrição é dividida em observações de até `VISITA_OBSERVACAO_MAX_CHARS`,
preservando a ordem. O fluxo informa quantas observações foram salvas. O teto
total continua finito; acima dele, o usuário deve dividir o áudio em partes menores.

## Transcrição avulsa pelo menu

O menu principal também oferece `🎙️ Transcrever áudio`. Essa opção é diferente
do áudio enviado durante uma visita técnica:

- na visita, a transcrição segue o estado atual e pode ser salva como descrição
  ou observação do relatório;
- no modo avulso, a transcrição é apenas devolvida como texto no WhatsApp e não
  cria visita, RDV, comprovante ou PDF.

Também é possível iniciar com o comando `transcrever áudio`. Depois disso, o
usuário pode enviar vários áudios. Os comandos `cancelar`, `sair`, `menu`,
`início` e `voltar` encerram o modo e abrem novamente o menu principal.
Quando a resposta ultrapassa o tamanho seguro de uma mensagem, ela é enviada em
partes, na ordem, sem alterar ou persistir o conteúdo.

Os limites de tamanho, duração e divisão em chunks do Whisper são os mesmos nos
dois modos.

## Teste local isolado

Sem WhatsApp:

```powershell
python scripts/test_whisper_transcricao.py --audio "C:\caminho\audio.ogg"
```

Com opcoes:

```powershell
python scripts/test_whisper_transcricao.py --audio "C:\caminho\audio.ogg" --model base --language pt --output transcricao.txt
```

O script mostra modelo, idioma, tempo gasto e texto transcrito. Ele nao remove o arquivo original informado pelo usuario.

## Scripts auxiliares de teste local

Os scripts auxiliares ajudam a preparar o ambiente e testar audios ficticios sem WhatsApp, sem Meta API, sem servidor e sem alterar `.env`.

Windows setup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_whisper_local_setup.ps1
```

Para apenas checar Python e ffmpeg, sem instalar dependencias:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_whisper_local_setup.ps1 -SkipInstall
```

Windows teste:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_whisper_local_audio_test.ps1 -Audio "C:\caminho\audio-ficticio.ogg"
```

Ubuntu teste:

```bash
bash scripts/run_whisper_local_audio_test.sh --audio "/caminho/audio-ficticio.ogg"
```

Esses testes locais nao enviam nada para WhatsApp, nao chamam Meta API, nao alteram RDV e nao ativam feature flag. Eles servem apenas para medir qualidade e velocidade da transcricao local com Whisper.

Para producao, ainda e necessario homologar o fluxo WhatsApp completo, validar privacidade/LGPD, definir retencao de audio e manter plano de rollback com `AUDIO_TRANSCRIPTION_ENABLED=false`.

## Transcrição bruta e transcrição revisada

O Whisper continua produzindo a **transcrição bruta**. Em seguida,
`AudioTranscriptionReviewService` cria uma **transcrição revisada**, preservando
ambas no retorno estruturado (`raw_text` e `reviewed_text`). O texto revisado é o
que aparece no modo avulso e o que segue para descrição, observação de visita ou
comentário de RDV.

A revisão atual é local e baseada em regras. Ela:

- normaliza espaços e pontuação básica;
- remove repetições consecutivas óbvias;
- corrige variantes conhecidas, como `cadax` → `Codex`, `botes` → `botões` e
  `contitor` → `contentor`;
- usa contexto (`standalone`, `visita_observacao`, `visita_descricao`,
  `codex_prompt` ou `relatorio_campo`) para limitar correções ambíguas;
- preserva comandos do fluxo, números, datas, telefones e valores monetários.

O glossário inicial inclui Codex, WhatsApp, botões, listas, Sim, Não, contentor,
contentores, entrega, recolha, operador, alugado, disponível, indisponível,
relatório, visita técnica, fazenda, aplicação, serviço, PDF, RDV e comprovante.
O serviço também aceita glossário opcional por chamada.

Se a revisão lançar erro ou produzir texto vazio, o fluxo usa a transcrição
bruta. No comentário de RDV, o estado interno mantém também `raw_text`. No modo
avulso, a resposta começa com `🎙️ Transcrição revisada do áudio:` e textos com
alteração substancial recebem um aviso curto. Respostas continuam divididas em
mensagens de até 4.000 caracteres.

### Riscos e evolução

As heurísticas não entendem intenção como um revisor semântico: podem deixar
passar nomes próprios, regionalismos e erros fonéticos não cadastrados. Por
serem conservadoras, preferem manter um trecho duvidoso a inventar conteúdo.
Uma futura implementação poderá trocar o mecanismo interno por LLM
(Gemini/OpenAI ou outro), mantendo o mesmo contrato e fallback, desde que haja
validação de privacidade, custo, latência e uma instrução explícita para não
inventar fatos.

## Modos da transcrição avulsa

Ao escolher `🎙️ Transcrever áudio`, o usuário seleciona como quer receber o
resultado:

```text
Como você quer receber a transcrição?

1. Literal
2. Revisada
3. Organizar para Codex
4. Relatório

Digite o número da opção.
```

- **Literal**: mantém o texto próximo da fala, aplicando somente a revisão local
  conservadora. Responde com `🎙️ Transcrição do áudio:`.
- **Revisada**: corrige português, pontuação e termos do glossário sem resumir o
  conteúdo. Responde com `📝 Transcrição revisada:`.
- **Codex**: organiza o conteúdo em ajustes, comportamentos de erro e critérios
  de aceite, preservando números, limites, ferramentas e entidades citadas.
  Responde com `🤖 Prompt organizado para Codex:`.
- **Relatório**: prepara texto corrido revisado para uso em relatório de campo.
  Responde com `📄 Texto organizado para relatório:`.

O serviço `AudioTranscriptionIntelligenceService` mantém um contrato estruturado
com modo, provider, erro e indicação de fallback. O provider `local` é o único
ativo nesta versão e não transmite texto para terceiros. A interface aceita
providers externos injetados no futuro; se estiverem ausentes, falharem ou
retornarem texto vazio, o processamento cai automaticamente para a revisão
local e o fluxo continua.

Enviar áudio ou transcrição a um LLM externo pode expor dados pessoais,
informações comerciais e conteúdo de visitas. Antes de habilitar qualquer
provider externo, é necessário revisar LGPD, base legal, retenção, região de
processamento, termos do fornecedor, custo, latência e política de logs. Chaves
jamais devem ser versionadas ou incluídas em prompts.

## Fluxo no WhatsApp

Com `AUDIO_TRANSCRIPTION_ENABLED=true`, apos completar a categoria de um comprovante RDV, o assistente pergunta se deseja adicionar comentario.

O colaborador pode:

- digitar o comentario;
- enviar audio;
- enviar `3` para deixar sem comentario.

Se enviar audio, o sistema:

1. baixa a midia da Meta para `WHISPER_TMP_DIR`;
2. transcreve com Whisper;
3. remove o audio temporario se `WHISPER_KEEP_AUDIO=false`;
4. envia a transcricao para confirmacao;
5. salva no campo `observacao` somente apos confirmacao.

Mensagem de confirmacao:

```text
Transcrevi seu audio assim:

"texto transcrito..."

1 - Confirmar comentario
2 - Corrigir digitando
3 - Remover comentario
```

## Planilha RDV

O campo `observacao` ja existe no RDV e ja e exportado nas planilhas semanal e mensal. Por isso esta primeira versao nao cria migracao nova.

## Privacidade e LGPD

- Nao envie audio com dados sensiveis em testes.
- Prefira `WHISPER_KEEP_AUDIO=false`.
- Nao versionar audios, transcricoes reais, banco ou logs com dados pessoais.
- Nao imprimir tokens nem payloads completos do WhatsApp.
- Antes de producao, definir consentimento, retencao, auditoria e criterio de descarte dos audios.

## Teste local vs producao

Teste local valida instalacao, modelo e transcricao de arquivo. Producao envolve webhook da Meta, download de midia, permissao de token, processamento em background e impacto no fluxo RDV.

Ative em producao somente depois de validar com audios ficticios e plano de rollback.
