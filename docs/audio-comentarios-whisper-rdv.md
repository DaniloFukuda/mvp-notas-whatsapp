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
- `VISITA_DESCRICAO_MAX_CHARS=5000`: limite da descrição principal da visita.
- `VISITA_OBSERVACAO_MAX_CHARS=20000`: limite de cada observação geral.
- `VISITA_OBSERVACAO_TOTAL_MAX_CHARS=80000`: teto de segurança de uma transcrição enviada para observações.
- `FOTO_COMENTARIO_MAX_CHARS=2000`: limite do comentário individual de foto.

Áudios longos podem produzir texto maior que uma única observação. Nesse caso, a
transcrição é dividida em observações de até `VISITA_OBSERVACAO_MAX_CHARS`,
preservando a ordem. O fluxo informa quantas observações foram salvas. O teto
total continua finito; acima dele, o usuário deve dividir o áudio em partes menores.

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
