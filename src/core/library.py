"""Operações de arquivos da biblioteca: listar, renomear (individual/lote), copiar, mover, excluir."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

AUDIO_EXT = {".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".aac", ".wma", ".webm_audio"}
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v", ".3gp"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
META_EXT = {".json", ".description", ".srt", ".vtt", ".ass", ".lrc", ".txt", ".nfo"}
TEMP_EXT = {".part", ".ytdl", ".temp", ".tmp"}
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Entry:
    path: str
    name: str
    is_dir: bool
    size: int
    mtime: float

    @property
    def ext(self) -> str:
        return os.path.splitext(self.name)[1].lower()

    @property
    def kind(self) -> str:
        if self.is_dir:
            return "pasta"
        e = self.ext
        if e in AUDIO_EXT:
            return "audio"
        if e in VIDEO_EXT:
            return "video"
        if e in IMAGE_EXT:
            return "imagem"
        if e in META_EXT or self.name.endswith(".info.json"):
            return "meta"
        return "outro"


def sanitize(name: str) -> str:
    name = _INVALID.sub("_", name).strip().rstrip(".")
    return name or "sem_nome"


def list_dir(path: str, show_hidden: bool = False, show_temp: bool = False) -> list[Entry]:
    out: list[Entry] = []
    try:
        with os.scandir(path) as it:
            for d in it:
                if not show_hidden and d.name.startswith("."):
                    continue
                if not show_temp and os.path.splitext(d.name)[1].lower() in TEMP_EXT:
                    continue
                try:
                    st = d.stat()
                    out.append(Entry(d.path, d.name, d.is_dir(), 0 if d.is_dir() else st.st_size, st.st_mtime))
                except OSError:
                    continue
    except OSError:
        return []
    out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return out


def walk_media(path: str) -> list[Entry]:
    """Todos os arquivos de mídia abaixo de path (para busca)."""
    res = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            e = Entry(p, f, False, st.st_size, st.st_mtime)
            if e.kind in ("audio", "video"):
                res.append(e)
    return res


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def _stem(name: str) -> str:
    return os.path.splitext(name)[0]


def sidecars(path: str) -> list[str]:
    """Arquivos de metadados com o mesmo nome base (mesma pasta e subpasta 'metadados')."""
    folder = os.path.dirname(path)
    stem = _stem(os.path.basename(path))
    found = []
    for d in (folder, os.path.join(folder, "metadados")):
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if p == path or not os.path.isfile(p):
                continue
            if f.startswith(stem + "."):
                rest = f[len(stem):]
                if rest.lower().endswith(tuple(IMAGE_EXT | META_EXT)) or rest.endswith(".info.json"):
                    found.append(p)
    return found


def rename(path: str, new_name: str, with_sidecars: bool = True) -> str:
    """Renomeia arquivo/pasta. A extensão original é mantida se não for digitada."""
    new_name = sanitize(new_name)
    folder = os.path.dirname(path)
    old_name = os.path.basename(path)
    if not os.path.isdir(path):
        old_ext = os.path.splitext(old_name)[1]
        if old_ext and not new_name.lower().endswith(old_ext.lower()):
            new_name += old_ext
    target = os.path.join(folder, new_name)
    if os.path.normcase(target) == os.path.normcase(path):
        if target != path:  # apenas troca de maiúsculas/minúsculas
            tmp = path + ".~ren"
            os.rename(path, tmp)
            os.rename(tmp, target)
        return target
    if os.path.exists(target):
        raise FileExistsError(f"Já existe '{new_name}' nesta pasta.")
    side = sidecars(path) if with_sidecars and os.path.isfile(path) else []
    os.rename(path, target)
    old_stem, new_stem = _stem(old_name), _stem(new_name)
    for s in side:
        sname = os.path.basename(s)
        dest = os.path.join(os.path.dirname(s), new_stem + sname[len(old_stem):])
        if not os.path.exists(dest):
            try:
                os.rename(s, dest)
            except OSError:
                pass
    return target


def batch_plan(paths: list[str], find: str = "", replace: str = "", prefix: str = "", suffix: str = "",
               numbering: bool = False, start: int = 1, digits: int = 2, case: str = "",
               use_regex: bool = False) -> list[tuple[str, str]]:
    """Calcula (caminho_antigo, novo_nome) sem alterar nada — usado para pré-visualizar."""
    plan = []
    n = start
    for p in paths:
        name = os.path.basename(p)
        stem, ext = (name, "") if os.path.isdir(p) else os.path.splitext(name)
        if find:
            if use_regex:
                try:
                    stem = re.sub(find, replace, stem)
                except re.error:
                    pass
            else:
                stem = stem.replace(find, replace)
        if case == "upper":
            stem = stem.upper()
        elif case == "lower":
            stem = stem.lower()
        elif case == "title":
            stem = stem.title()
        num = f"{n:0{digits}d} - " if numbering else ""
        n += 1
        plan.append((p, sanitize(f"{num}{prefix}{stem}{suffix}") + ext))
    return plan


def batch_rename(plan: list[tuple[str, str]], with_sidecars: bool = True) -> tuple[int, list[str]]:
    ok, errs = 0, []
    for p, new in plan:
        if os.path.basename(p) == new:
            continue
        try:
            rename(p, new, with_sidecars)
            ok += 1
        except Exception as ex:
            errs.append(f"{os.path.basename(p)}: {ex}")
    return ok, errs


def copy_to(paths: list[str], dest: str, move: bool = False, with_sidecars: bool = False) -> tuple[int, list[str]]:
    os.makedirs(dest, exist_ok=True)
    ok, errs = 0, []
    for p in paths:
        items = [p] + (sidecars(p) if with_sidecars and os.path.isfile(p) else [])
        for it in items:
            try:
                target = unique_path(os.path.join(dest, os.path.basename(it)))
                if move:
                    shutil.move(it, target)
                elif os.path.isdir(it):
                    shutil.copytree(it, target)
                else:
                    shutil.copy2(it, target)
                if it == p:
                    ok += 1
            except Exception as ex:
                errs.append(f"{os.path.basename(it)}: {ex}")
    return ok, errs


def duplicate(path: str) -> str:
    target = unique_path(path)
    if os.path.isdir(path):
        shutil.copytree(path, target)
    else:
        shutil.copy2(path, target)
    return target


def delete(paths: list[str], with_sidecars: bool = True) -> tuple[int, list[str]]:
    ok, errs = 0, []
    for p in paths:
        try:
            side = sidecars(p) if with_sidecars and os.path.isfile(p) else []
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            for s in side:
                try:
                    os.remove(s)
                except OSError:
                    pass
            ok += 1
        except Exception as ex:
            errs.append(f"{os.path.basename(p)}: {ex}")
    return ok, errs


def make_folder(parent: str, name: str) -> str:
    p = os.path.join(parent, sanitize(name))
    os.makedirs(p, exist_ok=False)
    return p


def read_metadata(path: str) -> dict:
    """Lê o .info.json correspondente (se existir) ou as tags do arquivo via mutagen."""
    for s in sidecars(path):
        if s.endswith(".info.json"):
            try:
                with open(s, encoding="utf-8") as f:
                    d = json.load(f)
                keys = ["title", "uploader", "channel", "artist", "album", "track", "upload_date",
                        "duration_string", "view_count", "like_count", "webpage_url", "playlist_title",
                        "resolution", "ext", "description"]
                return {k: d[k] for k in keys if d.get(k) not in (None, "")}
            except (OSError, ValueError):
                break
    try:
        import mutagen

        m = mutagen.File(path, easy=True)
        if m is not None:
            out = {k: ", ".join(map(str, v)) if isinstance(v, list) else str(v) for k, v in (m.tags or {}).items()}
            if getattr(m, "info", None) and getattr(m.info, "length", None):
                out["duração (s)"] = f"{m.info.length:.0f}"
            return out
    except Exception:
        pass
    return {}


def can_open_externally() -> bool:
    return sys.platform in ("win32", "darwin") or (sys.platform.startswith("linux") and shutil.which("xdg-open") is not None)


def open_external(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
