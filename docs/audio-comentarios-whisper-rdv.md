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
WHISPER_MODEL=base
WHISPER_LANGUAGE=pt
WHISPER_KEEP_AUDIO=false
WHISPER_TMP_DIR=tmp/audio_transcriptions
```

Comportamento:

- `AUDIO_TRANSCRIPTION_ENABLED=false`: audio recebido nao tenta transcrever.
- `AUDIO_TRANSCRIPTION_PROVIDER=whisper_local`: usa Whisper local.
- `WHISPER_MODEL=base`: modelo carregado sob demanda.
- `WHISPER_LANGUAGE=pt`: idioma padrao da transcricao.
- `WHISPER_KEEP_AUDIO=false`: remove audio temporario depois da transcricao.
- `WHISPER_TMP_DIR`: diretorio usado para baixar audio temporario da Meta.

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
