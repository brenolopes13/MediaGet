# MediaGet

Baixador de áudio e vídeo com interface gráfica, feito em Python com **[Flet](https://flet.dev)** (interface Flutter) e **[yt-dlp](https://github.com/yt-dlp/yt-dlp)**.
Roda em **Windows, Linux e Android** com o mesmo código.

## Download

Baixe a versão mais recente na página de [Releases](../../releases/latest):

| Sistema | Arquivo | Como usar |
|---|---|---|
| Windows 10/11 (64 bits) | `MediaGet-Windows-x64.zip` | Extraia e abra `mediaget.exe`. Já vem com ffmpeg. |
| Linux (64 bits) | `MediaGet-Linux-x64.tar.gz` | `tar -xzf MediaGet-Linux-x64.tar.gz` e rode `MediaGet/mediaget`. O player usa GStreamer (`sudo apt install gstreamer1.0-plugins-good gstreamer1.0-libav`). |
| Android 7+ | `MediaGet-Android.apk` | Copie para o celular e instale (permita "instalar apps desconhecidos"). |

As três versões são geradas automaticamente pelo GitHub Actions (`.github/workflows/build.yml`) a cada tag `v*`.

## Recursos

| Tela | O que faz |
|---|---|
| **Baixar** | Cola um ou mais links (ou usa o botão colar), analisa vídeo/playlist e mostra capa, título e duração. Em playlists você marca/desmarca os itens (todos, nenhum, inverter). |
| | Escolhe **Vídeo** (MP4, MKV, WebM · 240p a 4K) ou **Somente áudio** (MP3, M4A, Opus, FLAC, WAV ou original · 96 a 320 kbps). |
| | **Organização automática em pastas**: Canal/Playlist, Tipo/Canal, Artista/Álbum, Site/Canal, Canal/Ano/Mês, só Playlist, sem pastas ou template personalizado, com prévia do caminho final. |
| | **Nome do arquivo**: Título, "01 - Título", "Artista - Título", "Data - Título", "Título [ID]" ou personalizado. |
| | **Metadados**: embute título/artista/data/capítulos e a capa no arquivo, "modo música" (separa "Artista - Música", álbum = playlist, faixa = posição), salva `.info.json`, miniatura, descrição e legendas, opcionalmente numa subpasta `metadados/`. |
| **Fila** | Downloads simultâneos (1 a 5) com progresso, velocidade, tempo restante, item X de Y da playlist, cancelar, tentar de novo, abrir a pasta e ver na biblioteca. |
| **Biblioteca · Catálogo** | Mostra o que foi baixado como num app de streaming: grade de capas por **Playlists**, **Álbuns** e **Artistas**, lista de **Músicas**, busca, página de cada álbum/playlist com "Tocar" e "Aleatório" e **player embutido** (anterior/próxima, aleatório, barra de progresso). Também **reorganiza as pastas** pelos metadados (uma pasta por playlist, por álbum, por artista ou artista/álbum). |
| **Biblioteca · Pastas e arquivos** | Navega pelas pastas baixadas, busca em todas as subpastas, **renomeia** (mantém a extensão e renomeia junto os arquivos de metadados), **renomeia em lote** (procurar/substituir, regex, prefixo/sufixo, numeração, maiúsculas/minúsculas) com prévia, **copia/move** para outra pasta (pendrive, celular, etc.), duplica, copia caminho/nome, mostra metadados e exclui. |
| **Ajustes** | Pasta de downloads, ffmpeg, cookies (para vídeos com restrição), downloads simultâneos, pular itens já baixados (bom para atualizar playlists), tema claro/escuro e atualização do yt-dlp. |

## Rodar no computador (Windows / Linux)

Requer Python 3.10 ou mais novo.

```bash
pip install -r requirements.txt
```

```bash
python src/main.py
```

Para usar no navegador (útil para testes): `python src/main.py --web` e abra http://localhost:8550.

### ffmpeg (recomendado)

O ffmpeg é usado para juntar vídeo + áudio em alta qualidade, converter para MP3/FLAC etc. e embutir metadados e capa.
O app procura nesta ordem: caminho configurado em Ajustes → `ffmpeg` no PATH → pacote `imageio-ffmpeg`.
O jeito mais fácil é o pacote Python (já está no `requirements.txt`). Outras opções:

* Windows: `winget install ffmpeg`
* Linux: `sudo apt install ffmpeg` (ou o equivalente da sua distribuição)

Sem ffmpeg o app continua funcionando, mas baixa arquivos únicos no formato original.

## Gerar instaladores / executáveis

O Flet compila o app com Flutter. Na primeira vez ele baixa o Flutter SDK sozinho.

```bash
pip install "flet[all]"
```

| Plataforma | Comando | Onde gerar |
|---|---|---|
| Windows | `flet build windows` | numa máquina Windows (precisa do Visual Studio 2022 com "Desenvolvimento para desktop com C++") |
| Linux | `flet build linux` | numa máquina Linux (precisa de `clang cmake ninja-build libgtk-3-dev`) |
| Android | `flet build apk` (ou `flet build aab` para a Play Store) | Windows, Linux ou macOS (o Flet instala o Android SDK e o JDK) |

O resultado fica em `build/<plataforma>/`. As permissões do Android já estão no `pyproject.toml`.

### Dicas para o build no Windows

* Compile a partir de uma pasta com **caminho curto** (ex.: `C:\mgb`); caminhos longos estouram o limite de 260 caracteres do Windows.
* O Flutter precisa criar links simbólicos: ative o **Modo de Desenvolvedor** (`start ms-settings:developers`) ou rode o build num **PowerShell como administrador**.
* No Visual Studio Build Tools, além de "Desenvolvimento para desktop com C++", instale o componente **C++ CMake tools for Windows**:
  `& "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\setup.exe" modify --installPath "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools" --add Microsoft.VisualStudio.Component.VC.CMake.Project --passive`
* A versão Windows já leva o ffmpeg embutido (`imageio-ffmpeg`), então converte formatos e embute capas sem instalar nada.

### Observações sobre o Android

* Os arquivos vão para `Download/MediaGet` no armazenamento interno. Se o Android bloquear a gravação, abra
  *Configurações → Apps → MediaGet → Permissões* e permita o acesso aos arquivos.
* Não existe ffmpeg no Android dentro do app, então ele baixa no formato nativo do site
  (normalmente MP4 para vídeo e M4A/Opus para áudio), sem converter. Metadados podem ser salvos como `.info.json`.
* O yt-dlp fica embutido no APK. Para atualizá-lo, gere um APK novo com a versão mais recente.

## Estrutura do projeto

```
pyproject.toml        configuração do projeto e do "flet build"
requirements.txt      dependências para rodar no computador
src/
  main.py             janela, navegação (barra lateral no PC, barra inferior no celular)
  core/
    config.py         configurações salvas em JSON
    presets.py        formatos, qualidades, templates de pastas e nomes
    downloader.py     análise de links, opções do yt-dlp, fila de downloads
    library.py        renomear, lote, copiar, mover, excluir, ler metadados
    catalog.py        catálogo: tags, capas (com cache), álbuns/artistas/playlists, reorganizar
  ui/
    download_view.py  tela Baixar
    queue_view.py     tela Fila
    library_view.py   tela Biblioteca (Catálogo + Pastas e arquivos)
    catalog_view.py   catálogo com capas
    player.py         player de música (barra inferior)
    settings_view.py  tela Ajustes
    common.py         diálogos, avisos, seletor de pastas, área de transferência
```

## Aviso

Use apenas para baixar conteúdo que você tem direito de baixar, respeitando os termos de uso dos sites e os direitos autorais.
