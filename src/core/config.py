"""Configurações persistentes do app (arquivo JSON)."""
import json
import os
import sys
from dataclasses import asdict, dataclass, fields


def is_android() -> bool:
    return hasattr(sys, "getandroidapilevel") or "ANDROID_ARGUMENT" in os.environ or "ANDROID_ROOT" in os.environ


def _config_dir() -> str:
    # O "flet build" define FLET_APP_STORAGE_DATA em todas as plataformas empacotadas.
    base = os.environ.get("FLET_APP_STORAGE_DATA")
    if not base:
        if sys.platform == "win32":
            base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MediaGet")
        else:
            base = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "mediaget")
    os.makedirs(base, exist_ok=True)
    return base


def archive_file(mode: str) -> str:
    """Histórico de itens já baixados ("pular já baixados"). Fica na pasta privada do app:
    no Android a pasta Download pode ter arquivos de uma instalação anterior que o app
    não consegue mais abrir."""
    return os.path.join(_config_dir(), f"baixados-{mode}.txt")


def dir_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, ".mediaget-teste")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return True
    except OSError:
        return False


def default_download_dir() -> str:
    if is_android():
        candidates = ["/storage/emulated/0/Download/MediaGet", "/sdcard/Download/MediaGet"]
    else:
        candidates = [os.path.join(os.path.expanduser("~"), "Downloads", "MediaGet")]
    for c in candidates:
        try:
            os.makedirs(c, exist_ok=True)
            return c
        except OSError:
            continue
    fallback = os.path.join(_config_dir(), "downloads")
    os.makedirs(fallback, exist_ok=True)
    return fallback


@dataclass
class Settings:
    download_dir: str = ""
    ffmpeg_path: str = ""
    cookies_file: str = ""
    max_parallel: int = 2
    theme: str = "system"  # system | light | dark
    use_archive: bool = True
    # últimas escolhas da tela de download
    mode: str = "video"
    video_format: str = "mp4"
    video_quality: str = "1080"
    audio_format: str = "mp3"
    audio_quality: str = "best"
    folder_preset: str = "canal_playlist"
    folder_custom: str = "%(uploader)s/%(playlist_title|Avulsos)s/"
    file_preset: str = "titulo"
    file_custom: str = "%(title)s.%(ext)s"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    write_info_json: bool = False
    write_thumbnail: bool = False
    write_description: bool = False
    subtitles: bool = False
    sub_langs: str = "pt.*,en.*"
    metadata_subfolder: bool = True
    music_mode: bool = False

    @property
    def path(self) -> str:
        return os.path.join(_config_dir(), "config.json")

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            with open(s.path, encoding="utf-8") as f:
                data = json.load(f)
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names:
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        if not s.download_dir:
            s.download_dir = default_download_dir()
        return s

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass
