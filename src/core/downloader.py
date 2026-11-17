"""Motor de download: análise de links e execução de downloads com yt-dlp."""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import yt_dlp
from yt_dlp.postprocessor.metadataparser import MetadataParserPP
from yt_dlp.utils import DownloadCancelled

from .config import is_android
from .presets import FILE_PRESETS, FOLDER_PRESETS, SAMPLE_INFO


# --------------------------------------------------------------------------- ffmpeg
_android_ff: Optional[str] = None


def _android_ffmpeg() -> Optional[str]:
    """No Android o ffmpeg vem dentro do APK como lib/<abi>/libffmpeg.so.

    O Android extrai as libs nativas para uma pasta de onde é permitido executar
    programas; ela é a mesma das libs já carregadas pelo app (vista em /proc/self/maps).
    """
    global _android_ff
    if _android_ff is not None:
        return _android_ff or None
    _android_ff = ""
    try:
        with open("/proc/self/maps", encoding="utf-8", errors="ignore") as f:
            dirs = {os.path.dirname(line.split()[-1]) for line in f
                    if line.rstrip().endswith(".so") and "/lib/" in line}
        for d in dirs:
            p = os.path.join(d, "libffmpeg.so")
            if os.path.isfile(p) and os.access(p, os.X_OK):
                _android_ff = p
                break
    except OSError:
        pass
    return _android_ff or None


def find_ffmpeg(custom: str = "") -> Optional[str]:
    """Procura o ffmpeg: caminho configurado > embutido no APK > PATH > pacote imageio-ffmpeg."""
    if is_android():
        ff = _android_ffmpeg()
        if ff:
            return ff
    if custom:
        if os.path.isdir(custom):
            for name in ("ffmpeg.exe", "ffmpeg"):
                p = os.path.join(custom, name)
                if os.path.isfile(p):
                    return p
        elif os.path.isfile(custom):
            return custom
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # opcional, traz um ffmpeg pronto para Windows/Linux

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


# --------------------------------------------------------------------------- análise
class _QuietLogger:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.warnings.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg).replace("ERROR: ", ""))


def analyze(url: str, cookies_file: str = "") -> dict:
    """Busca informações do link sem baixar. Playlists são listadas de forma rápida (flat)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "logger": _QuietLogger(),
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    info = ydl.sanitize_info(info)

    entries = []
    if info.get("_type") in ("playlist", "multi_video") or info.get("entries"):
        for i, e in enumerate(info.get("entries") or [], start=1):
            if not e:
                continue
            entries.append({
                "index": i,
                "title": e.get("title") or e.get("id") or f"Item {i}",
                "duration": e.get("duration"),
                "uploader": e.get("uploader") or e.get("channel"),
                "url": e.get("url") or e.get("webpage_url"),
            })

    thumb = info.get("thumbnail")
    if not thumb and info.get("thumbnails"):
        thumb = info["thumbnails"][-1].get("url")

    heights = sorted({f.get("height") for f in info.get("formats") or [] if f.get("height")}, reverse=True)
    return {
        "url": url,
        "title": info.get("title") or info.get("id") or url,
        "uploader": info.get("uploader") or info.get("channel") or info.get("extractor_key"),
        "duration": info.get("duration"),
        "thumbnail": thumb,
        "is_playlist": bool(entries),
        "entries": entries,
        "heights": heights,
        "extractor": info.get("extractor_key"),
        "raw": {k: info.get(k) for k in ("title", "uploader", "channel", "playlist_title", "upload_date",
                                         "extractor_key", "id", "artist", "album", "track")},
    }


def fmt_duration(sec) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# --------------------------------------------------------------------------- opções
@dataclass
class DownloadOptions:
    url: str
    base_dir: str
    mode: str = "video"  # video | audio
    video_format: str = "mp4"
    video_quality: str = "1080"
    audio_format: str = "mp3"
    audio_quality: str = "best"
    folder_template: str = ""
    file_template: str = "%(title)s.%(ext)s"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    write_info_json: bool = False
    write_thumbnail: bool = False
    write_description: bool = False
    subtitles: bool = False
    sub_langs: str = "pt.*,en.*"
    metadata_subfolder: bool = True
    music_mode: bool = False
    playlist_items: str = ""  # ex.: "1,3,5-8"
    is_playlist: bool = False
    ffmpeg: Optional[str] = None
    cookies_file: str = ""
    archive_file: str = ""


# Em playlists, "Canal" passa a ser o dono da playlist (e não o canal de cada vídeo): assim uma playlist
# com músicas de vários canais fica numa pasta só. Mixes/rádios do YouTube não têm dono -> "Playlists".
PLAYLIST_FOLDER_OVERRIDES = {
    "canal_playlist": "%(playlist_uploader,playlist_channel|Playlists)s/%(playlist_title|Playlist)s/",
    "tipo_canal": "{tipo}/%(playlist_uploader,playlist_channel|Playlists)s/%(playlist_title|Playlist)s/",
    "site_canal": "%(extractor_key|Web)s/%(playlist_uploader,playlist_channel|Playlists)s/%(playlist_title|Playlist)s/",
}


def resolve_templates(folder_key: str, folder_custom: str, file_key: str, file_custom: str, mode: str,
                      is_playlist: bool = False):
    folder = folder_custom if folder_key == "custom" else FOLDER_PRESETS.get(folder_key, ("", ""))[1]
    if is_playlist and folder_key in PLAYLIST_FOLDER_OVERRIDES:
        folder = PLAYLIST_FOLDER_OVERRIDES[folder_key]
    folder = folder.replace("{tipo}", "Áudio" if mode == "audio" else "Vídeo")
    if folder and not folder.endswith("/"):
        folder += "/"
    file_t = file_custom if file_key == "custom" else FILE_PRESETS.get(file_key, ("", "%(title)s.%(ext)s"))[1]
    if "%(ext)s" not in file_t:
        file_t += ".%(ext)s"
    return folder, file_t


def preview_path(folder_t: str, file_t: str, info: Optional[dict] = None, ext: str = "mp4") -> str:
    sample = dict(SAMPLE_INFO)
    if info:
        sample.update({k: v for k, v in info.items() if v})
    sample["ext"] = ext
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "logger": _QuietLogger()}) as ydl:
            return ydl.prepare_filename(sample, outtmpl=folder_t + file_t)
    except Exception as ex:  # template inválido
        return f"Template inválido: {ex}"


def build_ydl_opts(o: DownloadOptions) -> tuple[dict, list[str]]:
    """Monta o dicionário de opções do yt-dlp. Retorna (opções, avisos)."""
    notes: list[str] = []
    has_ff = bool(o.ffmpeg)
    pp: list[dict] = []
    outtmpl_main = o.folder_template + o.file_template
    meta_dir = o.folder_template + ("metadados/" if o.metadata_subfolder else "")

    opts: dict = {
        "paths": {"home": o.base_dir},
        "outtmpl": {
            "default": outtmpl_main,
            "infojson": meta_dir + o.file_template,
            "description": meta_dir + o.file_template,
            "thumbnail": (meta_dir if o.write_thumbnail else o.folder_template) + o.file_template,
            "pl_infojson": o.folder_template + ("metadados/" if o.metadata_subfolder else "") + "%(playlist_title|playlist)s.%(ext)s",
            "pl_thumbnail": o.folder_template + ("metadados/" if o.metadata_subfolder else "") + "%(playlist_title|playlist)s.%(ext)s",
            "pl_description": o.folder_template + ("metadados/" if o.metadata_subfolder else "") + "%(playlist_title|playlist)s.%(ext)s",
        },
        "noplaylist": not o.is_playlist,
        "ignoreerrors": "only_download" if o.is_playlist else False,
        "windowsfilenames": True,
        "trim_file_name": 180,
        "continuedl": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "overwrites": False,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
    }
    if has_ff:
        opts["ffmpeg_location"] = o.ffmpeg
    if o.cookies_file:
        opts["cookiefile"] = o.cookies_file
    if o.archive_file:
        opts["download_archive"] = o.archive_file
    if o.playlist_items:
        opts["playlist_items"] = o.playlist_items

    # ---------------- formato / qualidade
    if o.mode == "video":
        # resolução sempre tem prioridade; depois codec/contêiner mais compatível
        sort = ["res" if o.video_quality == "best" else f"res:{o.video_quality}"]
        if o.video_format == "mp4":
            sort += ["vcodec:h264", "acodec:aac"]
        elif o.video_format == "webm":
            sort.append("ext:webm:webm")
        opts["format_sort"] = sort
        if has_ff:
            opts["format"] = "bv*+ba/b"
            opts["merge_output_format"] = o.video_format
        else:
            opts["format"] = "b/bv*+ba"
            notes.append("ffmpeg não encontrado: baixando arquivo único (qualidade pode ser limitada, sem conversão).")
    else:
        if has_ff:
            opts["format"] = "ba/b"
            pp.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": o.audio_format,
                "preferredquality": "0" if o.audio_quality == "best" else o.audio_quality,
                "nopostoverwrites": False,
            })
        else:
            opts["format"] = "ba[ext=m4a]/ba/b"
            notes.append("ffmpeg não encontrado: áudio salvo no formato original (sem conversão).")

    # ---------------- metadados
    if o.music_mode:
        actions = [
            (MetadataParserPP.Actions.INTERPRET, "title", r"(?P<artist>.+?)\s+[-–]\s+(?P<track>.+)"),
            (MetadataParserPP.Actions.INTERPRET, "%(artist,uploader)s", "%(artist)s"),
        ]
        if o.is_playlist:  # álbum = nome da playlist, faixa = posição na playlist
            actions += [
                (MetadataParserPP.Actions.INTERPRET, "%(album,playlist_title)s", "%(album)s"),
                (MetadataParserPP.Actions.INTERPRET, "%(track_number,playlist_index)s", "%(track_number)s"),
            ]
        pp.append({"key": "MetadataParser", "when": "pre_process", "actions": actions})
    if o.write_info_json:
        opts["writeinfojson"] = True
    if o.write_description:
        opts["writedescription"] = True
    if o.write_thumbnail or (o.embed_thumbnail and has_ff):
        opts["writethumbnail"] = True
    if o.subtitles:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = [s.strip() for s in o.sub_langs.split(",") if s.strip()]
        opts["outtmpl"]["subtitle"] = outtmpl_main
        if has_ff:
            pp.append({"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"})

    if has_ff:
        if o.embed_thumbnail:
            pp.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
        if o.embed_metadata:
            pp.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True, "add_infojson": "if_exists"})
        if o.subtitles and o.mode == "video":
            pp.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True})
        if o.embed_thumbnail and not (o.mode == "audio" and o.audio_format == "wav"):
            pp.append({"key": "EmbedThumbnail", "already_have_thumbnail": o.write_thumbnail})
    elif o.embed_metadata or o.embed_thumbnail:
        notes.append("Sem ffmpeg os metadados não são embutidos; ative 'Salvar metadados (.json)' para guardá-los.")

    # arquivos da playlist (capa/descrição/json da playlist) só quando o usuário pediu para salvar extras
    opts["allow_playlist_files"] = o.write_info_json or o.write_thumbnail or o.write_description
    opts["postprocessors"] = pp
    return opts, notes


# --------------------------------------------------------------------------- jobs
class _JobLogger(_QuietLogger):
    def __init__(self, job: "DownloadJob"):
        super().__init__()
        self.job = job

    def error(self, msg):
        super().error(msg)
        self.job.errors.append(str(msg).replace("ERROR: ", ""))
        self.job._emit(force=True)


@dataclass
class DownloadJob:
    options: DownloadOptions
    title: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = "na fila"  # na fila | baixando | processando | concluído | erro | cancelado
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    detail: str = ""
    item_index: int = 0
    item_count: int = 0
    files: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    on_update: Optional[Callable[["DownloadJob"], None]] = None
    _cancel: threading.Event = field(default_factory=threading.Event)
    _last_emit: float = 0.0

    @property
    def finished(self) -> bool:
        return self.status in ("concluído", "erro", "cancelado")

    def cancel(self):
        self._cancel.set()
        if self.status == "na fila":
            self.status = "cancelado"
            self._emit(force=True)

    def _emit(self, force=False):
        now = time.monotonic()
        if force or now - self._last_emit > 0.25:
            self._last_emit = now
            if self.on_update:
                try:
                    self.on_update(self)
                except Exception:
                    pass

    # hooks do yt-dlp ------------------------------------------------------
    def _progress_hook(self, d):
        if self._cancel.is_set():
            raise DownloadCancelled("Cancelado pelo usuário")
        info = d.get("info_dict") or {}
        self.item_index = info.get("playlist_index") or self.item_index
        self.item_count = info.get("n_entries") or info.get("playlist_count") or self.item_count
        name = info.get("title") or os.path.basename(d.get("filename") or "")
        if self.title.startswith("http"):  # baixado sem analisar: usa o título real
            self.title = info.get("playlist_title") or info.get("title") or self.title
        if d["status"] == "downloading":
            self.status = "baixando"
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            self.progress = (done / total) if total else 0.0
            self.speed = f"{fmt_size(d.get('speed'))}/s" if d.get("speed") else ""
            self.eta = fmt_duration(d.get("eta")) if d.get("eta") else ""
            self.detail = name
            self._emit()
        elif d["status"] == "finished":
            self.progress = 1.0
            self.detail = name
            self._emit(force=True)

    def _pp_hook(self, d):
        if self._cancel.is_set():
            raise DownloadCancelled("Cancelado pelo usuário")
        if d["status"] == "started":
            self.status = "processando"
            names = {
                "ExtractAudio": "Convertendo áudio", "Merger": "Juntando áudio e vídeo",
                "Metadata": "Gravando metadados", "EmbedThumbnail": "Embutindo capa",
                "EmbedSubtitle": "Embutindo legendas", "ThumbnailsConvertor": "Convertendo capa",
            }
            key = d.get("postprocessor", "")
            self.speed = ""
            self.eta = ""
            self.detail = next((v for k, v in names.items() if k in key), f"Processando ({key})")
            self._emit(force=True)

    def _post_hook(self, filename):
        self.files.append(filename)

    # execução -------------------------------------------------------------
    def run(self):
        if self._cancel.is_set():
            self.status = "cancelado"
            self._emit(force=True)
            return
        o = self.options
        opts, self.notes = build_ydl_opts(o)
        opts["logger"] = _JobLogger(self)
        opts["progress_hooks"] = [self._progress_hook]
        opts["postprocessor_hooks"] = [self._pp_hook]
        opts["post_hooks"] = [self._post_hook]
        self.status = "baixando"
        self.detail = "Iniciando…"
        self._emit(force=True)
        try:
            os.makedirs(o.base_dir, exist_ok=True)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ret = ydl.download([o.url])
            if self._cancel.is_set():
                self.status = "cancelado"
            elif ret and not self.files:
                self.status = "erro"
            elif not self.files and not self.errors:
                self.status = "concluído"
                self.detail = "Nada novo para baixar (já baixado anteriormente)."
            else:
                self.status = "concluído"
                n = len(self.files)
                self.detail = f"{n} arquivo(s) salvo(s)" + (f" · {len(self.errors)} erro(s)" if self.errors else "")
            self.progress = 1.0 if self.status == "concluído" else self.progress
        except DownloadCancelled:
            self.status = "cancelado"
            self.detail = "Cancelado pelo usuário"
        except Exception as ex:
            self.status = "erro"
            msg = str(ex).replace("ERROR: ", "")
            if msg not in self.errors:
                self.errors.append(msg)
            self.detail = msg[:300]
        self.speed = self.eta = ""
        self._emit(force=True)


class DownloadManager:
    """Fila com limite de downloads simultâneos."""

    def __init__(self, max_parallel: int = 2):
        self.jobs: list[DownloadJob] = []
        self._sem = threading.Semaphore(max(1, max_parallel))
        self.max_parallel = max(1, max_parallel)
        self.on_change: Optional[Callable[[], None]] = None

    def set_parallel(self, n: int):
        n = max(1, int(n))
        diff = n - self.max_parallel
        if diff > 0:
            for _ in range(diff):
                self._sem.release()
        self.max_parallel = n if diff > 0 else self.max_parallel  # reduzir vale para a próxima sessão

    def add(self, job: DownloadJob):
        self.jobs.insert(0, job)
        threading.Thread(target=self._worker, args=(job,), daemon=True).start()
        if self.on_change:
            self.on_change()

    def _worker(self, job: DownloadJob):
        with self._sem:
            job.run()

    def retry(self, job: DownloadJob) -> DownloadJob:
        new = DownloadJob(options=job.options, title=job.title, on_update=job.on_update)
        self.remove(job)
        self.add(new)
        return new

    def remove(self, job: DownloadJob):
        if job in self.jobs:
            self.jobs.remove(job)
        if self.on_change:
            self.on_change()

    def clear_finished(self):
        self.jobs = [j for j in self.jobs if not j.finished]
        if self.on_change:
            self.on_change()

    @property
    def active_count(self) -> int:
        return sum(1 for j in self.jobs if not j.finished)
