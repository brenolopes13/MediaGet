"""Catálogo de músicas/vídeos: lê tags e capas dos arquivos baixados (com cache) e agrupa por álbum e artista."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from core.config import _config_dir
from core.library import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, sanitize, unique_path

try:  # opcional: reduz as capas para carregar a grade mais rápido
    from PIL import Image as _PIL
except Exception:  # pragma: no cover
    _PIL = None

CACHE_VERSION = 3
COVER_SIZE = 400

# trechos comuns em títulos do YouTube que poluem o catálogo (só na exibição; o arquivo não muda)
_NOISE = re.compile(
    r"\s*[\(\[【][^\)\]】]*?(official|oficial|music video|lyric|letra|tradu[cç][aã]o|legendad|audio|áudio|"
    r"video ?clipe|videoclipe|clipe|visualizer|hd|4k|remaster|ao vivo oficial)[^\)\]】]*[\)\]】]",
    re.IGNORECASE,
)


def clean_title(title: str) -> str:
    t = _NOISE.sub("", title).strip(" -–|")
    return t or title


@dataclass
class Track:
    path: str
    title: str
    artist: str
    album: str
    track_no: int = 0
    year: str = ""
    duration: float = 0.0
    kind: str = "audio"
    cover: str = ""  # caminho da imagem da capa (cache ou arquivo ao lado)
    mtime: float = 0.0
    size: int = 0
    folder: str = ""  # nome da pasta onde está (normalmente a playlist)

    @property
    def display_title(self) -> str:
        return clean_title(self.title)


@dataclass
class Group:
    key: str
    name: str
    subtitle: str
    tracks: list[Track] = field(default_factory=list)

    @property
    def cover(self) -> str:
        return next((t.cover for t in self.tracks if t.cover), "")

    @property
    def duration(self) -> float:
        return sum(t.duration for t in self.tracks)


def _covers_dir() -> str:
    d = os.path.join(_config_dir(), "covers")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path() -> str:
    return os.path.join(_config_dir(), "catalog.json")


# ------------------------------------------------------------------ leitura de tags
def _first(tags, *keys) -> str:
    for k in keys:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        if v:
            v = v[0] if isinstance(v, (list, tuple)) else v
            v = str(v).strip()
            if v:
                return v
    return ""


def _embedded_picture(path: str) -> Optional[bytes]:
    import mutagen

    try:
        m = mutagen.File(path)
    except Exception:
        return None
    if m is None:
        return None
    pics = getattr(m, "pictures", None)  # FLAC
    if pics:
        return pics[0].data
    tags = m.tags
    if not tags:
        return None
    try:  # ID3 (MP3)
        for k in tags.keys():
            if str(k).startswith("APIC"):
                return tags[k].data
    except Exception:
        pass
    try:  # MP4/M4A
        covr = tags.get("covr")
        if covr:
            return bytes(covr[0])
    except Exception:
        pass
    try:  # Ogg/Opus
        b64 = tags.get("metadata_block_picture")
        if b64:
            from mutagen.flac import Picture

            return Picture(base64.b64decode(b64[0])).data
    except Exception:
        pass
    return None


def _sidecar_image(path: str) -> str:
    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    for d in (folder, os.path.join(folder, "metadados")):
        for ext in IMAGE_EXT:
            p = os.path.join(d, stem + ext)
            if os.path.isfile(p):
                return p
    return ""


def _save_cover(data: bytes, key: str) -> str:
    out = os.path.join(_covers_dir(), key + ".jpg")
    if os.path.isfile(out):
        return out
    try:
        if _PIL is not None:
            import io

            im = _PIL.open(io.BytesIO(data))
            im = im.convert("RGB")
            # miniaturas do YouTube costumam ser 16:9 com faixas: recorta o centro em quadrado
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
            im.thumbnail((COVER_SIZE, COVER_SIZE))
            im.save(out, "JPEG", quality=85)
        else:
            with open(out, "wb") as f:
                f.write(data)
        return out
    except Exception:
        return ""


def read_track(path: str, root: str) -> Track:
    st = os.stat(path)
    ext = os.path.splitext(path)[1].lower()
    kind = "video" if ext in VIDEO_EXT else "audio"
    folder = os.path.dirname(path)
    rel_parts = os.path.relpath(folder, root).split(os.sep)
    rel_parts = [p for p in rel_parts if p not in (".", "metadados")]
    title = artist = album = year = ""
    track_no, duration = 0, 0.0
    try:
        import mutagen

        m = mutagen.File(path, easy=True)
        if m is not None:
            duration = float(getattr(m.info, "length", 0) or 0)
            tags = m.tags or {}
            title = _first(tags, "title")
            artist = _first(tags, "artist", "albumartist", "performer")
            album = _first(tags, "album")
            year = _first(tags, "date", "year")[:4]
            tn = _first(tags, "tracknumber")
            if tn:
                try:
                    track_no = int(tn.split("/")[0])
                except ValueError:
                    pass
    except Exception:
        pass
    stem = os.path.splitext(os.path.basename(path))[0]
    if not title:
        title = stem
        if not artist and " - " in stem:  # "Artista - Música"
            artist, title = [s.strip() for s in stem.split(" - ", 1)]
    if not artist:
        artist = rel_parts[0] if len(rel_parts) >= 2 else "Artista desconhecido"
    if not album:
        album = rel_parts[-1] if rel_parts else "Avulsos"
    key = hashlib.sha1(f"{path}|{st.st_mtime}|{st.st_size}".encode("utf-8", "ignore")).hexdigest()[:20]
    cover = ""
    data = _embedded_picture(path)
    if data:
        cover = _save_cover(data, key)
    if not cover:
        side = _sidecar_image(path)
        if side:
            if _PIL is not None:
                try:
                    with open(side, "rb") as f:
                        cover = _save_cover(f.read(), key)
                except OSError:
                    cover = side
            else:
                cover = side
    return Track(path, title, artist, album, track_no, year, duration, kind, cover, st.st_mtime, st.st_size,
                 rel_parts[-1] if rel_parts else "Downloads")


# ------------------------------------------------------------------ varredura com cache
def _load_index() -> dict:
    try:
        with open(_index_path(), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("v") == CACHE_VERSION:
            return data.get("tracks", {})
    except (OSError, ValueError):
        pass
    return {}


def _save_index(tracks: list[Track]) -> None:
    try:
        with open(_index_path(), "w", encoding="utf-8") as f:
            json.dump({"v": CACHE_VERSION, "tracks": {t.path: asdict(t) for t in tracks}}, f, ensure_ascii=False)
    except OSError:
        pass


def list_media_files(root: str, include_video: bool = True) -> list[str]:
    exts = AUDIO_EXT | (VIDEO_EXT if include_video else set())
    out = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "metadados"]
        for f in files:
            if os.path.splitext(f)[1].lower() in exts and not f.startswith("."):
                out.append(os.path.join(r, f))
    return out


def scan(root: str, include_video: bool = True, progress: Optional[Callable[[int, int], None]] = None) -> list[Track]:
    files = list_media_files(root, include_video)
    index = _load_index()
    result: list[Optional[Track]] = [None] * len(files)
    todo = []
    for i, p in enumerate(files):
        c = index.get(p)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if c and c.get("mtime") == st.st_mtime and c.get("size") == st.st_size and \
                (not c.get("cover") or os.path.exists(c["cover"])):
            result[i] = Track(**c)
        else:
            todo.append(i)
    done = len(files) - len(todo)
    if progress:
        progress(done, len(files))

    def work(i):
        try:
            return i, read_track(files[i], root)
        except Exception:
            return i, None

    if todo:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for n, (i, t) in enumerate(ex.map(work, todo), 1):
                result[i] = t
                if progress and (n % 10 == 0 or n == len(todo)):
                    progress(done + n, len(files))
    tracks = [t for t in result if t]
    _save_index(tracks)
    return tracks


# ------------------------------------------------------------------ agrupamento
def _album_artist(tracks: list[Track]) -> str:
    c = Counter(t.artist for t in tracks)
    if len(c) > 3 and c.most_common(1)[0][1] < len(tracks) * 0.6:
        return "Vários artistas"
    return c.most_common(1)[0][0]


def _sort_tracks(tracks: list[Track]) -> list[Track]:
    return sorted(tracks, key=lambda t: (t.track_no or 10 ** 6, t.display_title.lower()))


def albums(tracks: list[Track]) -> list[Group]:
    groups: dict[str, list[Track]] = {}
    for t in tracks:
        groups.setdefault(t.album, []).append(t)
    out = []
    for name, ts in groups.items():
        out.append(Group("album:" + name, name, f"{_album_artist(ts)} · {len(ts)} faixa(s)", _sort_tracks(ts)))
    out.sort(key=lambda g: g.name.lower())
    return out


def playlists(tracks: list[Track]) -> list[Group]:
    """Agrupa pela pasta onde o arquivo está (as playlists baixadas viram uma pasta cada)."""
    groups: dict[str, list[Track]] = {}
    for t in tracks:
        groups.setdefault(t.folder, []).append(t)
    out = []
    for name, ts in groups.items():
        ts = sorted(ts, key=lambda t: (t.mtime, t.display_title.lower()))
        out.append(Group("folder:" + name, name, f"{_album_artist(ts)} · {len(ts)} faixa(s)", ts))
    out.sort(key=lambda g: (-len(g.tracks), g.name.lower()))
    return out


def artists(tracks: list[Track]) -> list[Group]:
    groups: dict[str, list[Track]] = {}
    for t in tracks:
        groups.setdefault(t.artist, []).append(t)
    out = []
    for name, ts in groups.items():
        n_alb = len({t.album for t in ts})
        out.append(Group("artist:" + name, name, f"{len(ts)} faixa(s) · {n_alb} álbum(ns)",
                         sorted(ts, key=lambda t: (t.album.lower(), t.track_no or 10 ** 6, t.display_title.lower()))))
    out.sort(key=lambda g: g.name.lower())
    return out


def search(tracks: list[Track], q: str) -> list[Track]:
    q = q.strip().lower()
    if not q:
        return tracks
    return [t for t in tracks if q in t.title.lower() or q in t.artist.lower() or q in t.album.lower()]


# ------------------------------------------------------------------ reorganizar pastas pelos metadados
REORG_LAYOUTS = {
    "playlist": ("Uma pasta por playlist (tira a pasta do canal)", "{folder}"),
    "album": ("Álbum", "{album}"),
    "artista": ("Artista", "{artist}"),
    "artista_album": ("Artista / Álbum", "{artist}/{album}"),
    "plano": ("Tudo numa pasta só", ""),
}


def reorganize_plan(tracks: list[Track], root: str, layout: str) -> list[tuple[str, str]]:
    pattern = REORG_LAYOUTS.get(layout, REORG_LAYOUTS["playlist"])[1]
    plan = []
    for t in tracks:
        sub = pattern.format(artist=sanitize(t.artist), album=sanitize(t.album), folder=sanitize(t.folder))
        dest_dir = os.path.join(root, *[p for p in sub.split("/") if p])
        dest = os.path.join(dest_dir, os.path.basename(t.path))
        if os.path.normcase(os.path.abspath(dest)) != os.path.normcase(os.path.abspath(t.path)):
            plan.append((t.path, dest))
    return plan


def _remove_empty_dirs(root: str) -> int:
    n = 0
    for r, dirs, files in os.walk(root, topdown=False):
        if os.path.normcase(r) == os.path.normcase(root):
            continue
        try:
            if not os.listdir(r):
                os.rmdir(r)
                n += 1
        except OSError:
            pass
    return n


def reorganize(plan: list[tuple[str, str]], root: str, progress: Optional[Callable[[int, int], None]] = None) \
        -> tuple[int, list[str]]:
    from core.library import sidecars

    ok, errs = 0, []
    for i, (src, dest) in enumerate(plan, 1):
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            # leva junto .info.json, capa e legendas de mesmo nome (inclusive da subpasta metadados/)
            for sc in sidecars(src):
                rel = os.path.relpath(sc, os.path.dirname(src))
                sc_dest = os.path.join(os.path.dirname(dest), rel)
                os.makedirs(os.path.dirname(sc_dest), exist_ok=True)
                shutil.move(sc, unique_path(sc_dest))
            shutil.move(src, unique_path(dest))
            ok += 1
        except Exception as ex:
            errs.append(f"{os.path.basename(src)}: {ex}")
        if progress and (i % 10 == 0 or i == len(plan)):
            progress(i, len(plan))
    _remove_empty_dirs(root)
    return ok, errs
