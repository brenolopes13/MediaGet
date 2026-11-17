"""Predefinições de formato, qualidade, organização de pastas e nomes de arquivo."""

VIDEO_FORMATS = {
    "mp4": "MP4 (mais compatível)",
    "mkv": "MKV (aceita tudo, legendas embutidas)",
    "webm": "WebM",
}

AUDIO_FORMATS = {
    "mp3": "MP3",
    "m4a": "M4A / AAC",
    "opus": "Opus",
    "flac": "FLAC (sem perdas)",
    "wav": "WAV (sem compressão)",
    "best": "Original (sem converter)",
}

VIDEO_QUALITIES = {
    "best": "Melhor disponível",
    "2160": "4K (2160p)",
    "1440": "1440p",
    "1080": "Full HD (1080p)",
    "720": "HD (720p)",
    "480": "480p",
    "360": "360p",
    "240": "240p (economia de dados)",
}

AUDIO_QUALITIES = {
    "best": "Melhor disponível",
    "320": "320 kbps",
    "256": "256 kbps",
    "192": "192 kbps",
    "128": "128 kbps",
    "96": "96 kbps",
}

# Estruturas de pastas (sintaxe de template do yt-dlp). Terminam em "/".
FOLDER_PRESETS = {
    "canal_playlist": ("Canal / Playlist", "%(uploader,channel|Desconhecido)s/%(playlist_title|Avulsos)s/"),
    "tipo_canal": ("Tipo (Áudio|Vídeo) / Canal", "{tipo}/%(uploader,channel|Desconhecido)s/"),
    "artista_album": ("Música: Artista / Álbum", "%(artist,creator,uploader|Desconhecido)s/%(album,playlist_title|Singles)s/"),
    "site_canal": ("Site / Canal", "%(extractor_key|Web)s/%(uploader,channel|Desconhecido)s/"),
    "canal_ano_mes": ("Canal / Ano / Mês", "%(uploader,channel|Desconhecido)s/%(upload_date>%Y|Sem data)s/%(upload_date>%m|00)s/"),
    "playlist": ("Somente Playlist", "%(playlist_title|Avulsos)s/"),
    "nenhuma": ("Sem subpastas", ""),
    "custom": ("Personalizado…", ""),
}

FILE_PRESETS = {
    "titulo": ("Título", "%(title)s.%(ext)s"),
    "num_titulo": ("Nº na playlist - Título", "%(playlist_index&{:02d} - |)s%(title)s.%(ext)s"),
    "artista_titulo": ("Artista - Título", "%(artist,creator,uploader)s - %(track,title)s.%(ext)s"),
    "data_titulo": ("Data - Título", "%(upload_date>%Y-%m-%d|0000-00-00)s - %(title)s.%(ext)s"),
    "titulo_id": ("Título [ID]", "%(title)s [%(id)s].%(ext)s"),
    "custom": ("Personalizado…", "%(title)s.%(ext)s"),
}

TEMPLATE_HELP = (
    "Campos úteis: %(title)s, %(uploader)s, %(channel)s, %(playlist_title)s, "
    "%(playlist_index)s, %(artist)s, %(album)s, %(track)s, %(upload_date>%Y)s, "
    "%(id)s, %(ext)s. Use '/' para criar subpastas e 'a,b|padrão' para alternativas."
)

SAMPLE_INFO = {
    "id": "dQw4w9WgXcQ",
    "title": "Título do Vídeo",
    "uploader": "Nome do Canal",
    "channel": "Nome do Canal",
    "playlist_title": "Minha Playlist",
    "playlist_index": 1,
    "upload_date": "20240315",
    "extractor_key": "Youtube",
    "ext": "mp4",
}
