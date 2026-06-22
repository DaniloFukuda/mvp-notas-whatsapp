# Exemplos de audio ficticio

Esta pasta existe apenas para instrucoes. Nao coloque aqui audio real, audio de cliente, dados pessoais, dados de fazenda/obra reais ou qualquer arquivo sensivel.

Arquivos de audio nao devem ser versionados. O `.gitignore` bloqueia formatos comuns como `.ogg`, `.opus`, `.mp3`, `.m4a`, `.wav`, `.webm` e `.aac`.

## Frases ficticias para gravar

- Esse combustivel foi usado para uma viagem ficticia de Formosa ate a Fazenda Modelo para reuniao de teste. Valor e cliente sao apenas exemplos.
- Almoco ficticio durante visita de treinamento, sem cliente real e sem valor sensivel.
- Pedagio de exemplo para deslocamento simulado entre escritorio e area de testes.

## Exportar audio do WhatsApp manualmente

Use somente conversas e audios ficticios criados para teste. Salve o arquivo fora do repositorio, por exemplo em `C:\temp\audio-ficticio.ogg` ou `/tmp/audio-ficticio.ogg`.

Nao envie esse audio para o sistema real, nao chame webhook, nao chame Meta API e nao coloque o arquivo dentro desta pasta.

## Formatos aceitos

- `.ogg`
- `.opus`
- `.mp3`
- `.m4a`
- `.wav`

## Comando de teste

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_whisper_local_audio_test.ps1 -Audio "C:\temp\audio-ficticio.ogg"
```

Ubuntu:

```bash
bash scripts/run_whisper_local_audio_test.sh --audio "/tmp/audio-ficticio.ogg"
```
