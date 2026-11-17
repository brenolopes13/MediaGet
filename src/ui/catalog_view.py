"""Catálogo estilo streaming: grade de capas por playlist, álbum e artista, lista de faixas e player."""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

import flet as ft

from core import catalog as cat
from core import library as lib
from core.catalog import Group, Track
from core.downloader import fmt_duration
from ui.common import AppContext, mounted, safe_update
from ui.player import Player, cover_image

TABS = [("playlists", "Playlists", ft.Icons.QUEUE_MUSIC), ("albums", "Álbuns", ft.Icons.ALBUM),
        ("artists", "Artistas", ft.Icons.PERSON), ("tracks", "Músicas", ft.Icons.MUSIC_NOTE)]
KIND_LABEL = {"playlists": "PLAYLIST", "albums": "ÁLBUM", "artists": "ARTISTA"}


def _total(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


class CatalogView:
    def __init__(self, ctx: AppContext, player: Player, on_files_changed: Callable[[], None] = lambda: None):
        self.ctx = ctx
        self.player = player
        self.on_files_changed = on_files_changed
        self.tracks: list[Track] = []
        self.tab = "playlists"
        self.group: Optional[Group] = None  # página de detalhe aberta
        self.scanning = False
        self.title_refs: dict[str, ft.Text] = {}
        player.listeners.append(self._on_track_change)

        self.tabs = ft.SegmentedButton(
            selected=["playlists"], allow_multiple_selection=False, show_selected_icon=False,
            segments=[ft.Segment(value=k, label=ft.Text(l), icon=ft.Icon(i)) for k, l, i in TABS],
            on_change=self.on_tab,
        )
        self.search = ft.TextField(hint_text="Buscar música, artista ou álbum…", prefix_icon=ft.Icons.SEARCH,
                                   dense=True, expand=True, on_change=lambda e: self.render())
        self.status = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.progress = ft.ProgressBar(visible=False)
        self.body = ft.Container(expand=True)
        self.view = ft.Column([
            ft.Row([self.tabs], scroll=ft.ScrollMode.AUTO),
            ft.Row([
                self.search,
                ft.IconButton(ft.Icons.REFRESH, tooltip="Atualizar catálogo", on_click=lambda e: self.load(force=True)),
                ft.IconButton(ft.Icons.AUTO_FIX_HIGH, tooltip="Reorganizar pastas pelos metadados",
                              on_click=self.reorganize_dialog),
            ]),
            self.progress,
            self.status,
            self.body,
        ], expand=True, spacing=8)

    # ================================================================ carregar
    def load(self, force: bool = False):
        if self.scanning:
            return
        if self.tracks and not force:
            self.render()
            return
        self.ctx.page.run_task(self._scan)

    async def _scan(self):
        self.scanning = True
        self.progress.visible = True
        self.progress.value = None
        self.status.value = "Lendo a biblioteca…"
        safe_update(self.view)

        def prog(done, total):
            self.progress.value = done / total if total else None
            self.status.value = f"Lendo capas e informações… {done}/{total}"
            safe_update(self.progress)
            safe_update(self.status)

        try:
            self.tracks = await asyncio.to_thread(cat.scan, self.ctx.settings.download_dir, True, prog)
        except Exception as ex:
            self.ctx.toast(f"Erro ao ler a biblioteca: {ex}", error=True)
        self.scanning = False
        self.progress.visible = False
        if self.group:  # reabre a página com os dados novos
            self.group = next((g for g in self._groups() if g.key == self.group.key), None)
        self.render()

    # ================================================================ navegação
    def on_tab(self, e):
        self.tab = next(iter(e.control.selected), "playlists")
        self.group = None
        self.render()

    def _groups(self) -> list[Group]:
        ts = cat.search(self.tracks, self.search.value or "")
        if self.tab == "albums":
            return cat.albums(ts)
        if self.tab == "artists":
            return cat.artists(ts)
        return cat.playlists(ts)

    def render(self):
        self.title_refs = {}
        n = len(self.tracks)
        if not self.scanning:
            self.status.value = (f"{n} faixa(s) · {_total(sum(t.duration for t in self.tracks))}" if n else "")
        if not n and not self.scanning:
            self.body.content = ft.Container(ft.Column([
                ft.Icon(ft.Icons.LIBRARY_MUSIC, size=64, color=ft.Colors.OUTLINE),
                ft.Text("Nenhuma música ou vídeo na pasta de downloads ainda.", color=ft.Colors.ON_SURFACE_VARIANT),
                ft.TextButton("Baixar algo", icon=ft.Icons.DOWNLOAD, on_click=lambda e: self.ctx.go_to(0)),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True), alignment=ft.Alignment.CENTER)
        elif self.group is not None:
            self.body.content = self._detail(self.group)
        elif self.tab == "tracks":
            ts = sorted(cat.search(self.tracks, self.search.value or ""), key=lambda t: t.display_title.lower())
            self.body.content = self._track_list(ts, show_album=True)
        else:
            self.body.content = self._grid(self._groups())
        if mounted(self.view):
            safe_update(self.view)

    def open_group(self, g: Group):
        self.group = g
        self.render()

    def back(self, e=None):
        self.group = None
        self.render()

    # ================================================================ grade de capas
    def _grid(self, groups: list[Group]) -> ft.Control:
        if not groups:
            return ft.Container(ft.Text("Nada encontrado", color=ft.Colors.ON_SURFACE_VARIANT),
                                alignment=ft.Alignment.CENTER, padding=30)
        round_ = self.tab == "artists"
        cards = []
        for g in groups:
            cover = cover_image(self.ctx, g.cover, 160, radius=999 if round_ else 10, expand=True,
                                icon=ft.Icons.PERSON if round_ else ft.Icons.ALBUM)
            cards.append(ft.Container(
                ft.Column([
                    cover,
                    ft.Text(g.name, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                            text_align=ft.TextAlign.CENTER if round_ else None),
                    ft.Text(g.subtitle, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER if round_ else ft.CrossAxisAlignment.START),
                padding=8, border_radius=12, ink=True, tooltip=g.name,
                on_click=lambda e, gg=g: self.open_group(gg),
            ))
        return ft.GridView(cards, expand=True, max_extent=200, child_aspect_ratio=0.74, spacing=6, run_spacing=6,
                           padding=ft.Padding.only(bottom=16))

    # ================================================================ página do álbum/playlist/artista
    def _detail(self, g: Group) -> ft.Control:
        round_ = self.tab == "artists"
        compact = (self.ctx.page.width or 1000) < 600
        size = 120 if compact else 180
        info = ft.Column([
            ft.Text(KIND_LABEL.get(self.tab, ""), size=11, weight=ft.FontWeight.W_600, color=ft.Colors.PRIMARY),
            ft.Text(g.name, size=20 if compact else 28, weight=ft.FontWeight.BOLD, max_lines=3,
                    overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(f"{g.subtitle} · {_total(g.duration)}", color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Row([
                ft.FilledButton("Tocar", icon=ft.Icons.PLAY_ARROW, on_click=lambda e: self.player.play_list(g.tracks, 0, False)),
                ft.OutlinedButton("Aleatório", icon=ft.Icons.SHUFFLE, on_click=lambda e: self.player.play_list(g.tracks, 0, True)),
                ft.IconButton(ft.Icons.FOLDER_OPEN, tooltip="Ver pasta na biblioteca",
                              on_click=lambda e: self._show_folder(g.tracks[0].path)),
            ], wrap=True),
        ], spacing=6, expand=True)
        header = ft.Row([
            ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Voltar", on_click=self.back),
            cover_image(self.ctx, g.cover, size, radius=999 if round_ else 12,
                        icon=ft.Icons.PERSON if round_ else ft.Icons.ALBUM),
            info,
        ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=16)
        return ft.Column([header, ft.Divider(height=1), self._track_list(g.tracks, show_album=self.tab == "artists",
                                                                          numbered=self.tab != "artists")],
                         expand=True, spacing=8)

    # ================================================================ lista de faixas
    def _track_list(self, tracks: list[Track], show_album: bool = False, numbered: bool = False) -> ft.Control:
        if not tracks:
            return ft.Container(ft.Text("Nada encontrado", color=ft.Colors.ON_SURFACE_VARIANT),
                                alignment=ft.Alignment.CENTER, padding=30)
        cur = self.player.current.path if self.player.current else None
        rows = []
        for i, t in enumerate(tracks):
            title = ft.Text(t.display_title, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            weight=ft.FontWeight.W_500, color=ft.Colors.PRIMARY if t.path == cur else None)
            self.title_refs[t.path] = title
            sub = t.artist + (f" · {t.album}" if show_album else "")
            if t.kind == "video":
                sub = "Vídeo · " + sub
            menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, items=[
                ft.PopupMenuItem(content="Tocar", icon=ft.Icons.PLAY_ARROW,
                                 on_click=lambda e, ts=tracks, i=i: self.player.play_list(ts, i)),
                ft.PopupMenuItem(content="Tocar a seguir", icon=ft.Icons.QUEUE_PLAY_NEXT,
                                 on_click=lambda e, t=t: self.player.play_next(t)),
                ft.PopupMenuItem(content="Mostrar na pasta", icon=ft.Icons.FOLDER_OPEN,
                                 on_click=lambda e, p=t.path: self._show_folder(p)),
                *([ft.PopupMenuItem(content="Abrir no player do sistema", icon=ft.Icons.OPEN_IN_NEW,
                                    on_click=lambda e, p=t.path: lib.open_external(p))]
                  if lib.can_open_externally() else []),
                ft.PopupMenuItem(content="Copiar caminho", icon=ft.Icons.CONTENT_COPY,
                                 on_click=lambda e, p=t.path: self.ctx.page.run_task(self.ctx.copy_text, p, "Caminho")),
            ])
            lead = [cover_image(self.ctx, t.cover, 44, 6)]
            if numbered:
                lead.insert(0, ft.Text(str(i + 1), width=28, size=12, text_align=ft.TextAlign.RIGHT,
                                       color=ft.Colors.ON_SURFACE_VARIANT))
            rows.append(ft.ListTile(
                leading=ft.Row(lead, spacing=10, tight=True),
                title=title,
                subtitle=ft.Text(sub, size=12, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                trailing=ft.Row([ft.Text(fmt_duration(t.duration), size=12, color=ft.Colors.ON_SURFACE_VARIANT), menu],
                                tight=True, spacing=0),
                dense=True,
                on_click=lambda e, ts=tracks, i=i: self.player.play_list(ts, i),
            ))
        return ft.ListView(rows, expand=True, spacing=0, padding=ft.Padding.only(bottom=16))

    def _on_track_change(self, track: Optional[Track]):
        cur = track.path if track else None
        changed = []
        for p, txt in self.title_refs.items():
            want = ft.Colors.PRIMARY if p == cur else None
            if txt.color != want:
                txt.color = want
                changed.append(txt)
        for txt in changed:
            safe_update(txt)

    def _show_folder(self, path: str):
        self.ctx.library_open(os.path.dirname(path), files_mode=True)

    # ================================================================ reorganizar
    def reorganize_dialog(self, e):
        if not self.tracks:
            self.ctx.toast("Nada para reorganizar.")
            return
        root = self.ctx.settings.download_dir
        layout = ft.RadioGroup(value="playlist", content=ft.Column(
            [ft.Radio(value=k, label=v[0]) for k, v in cat.REORG_LAYOUTS.items()], spacing=0))
        info = ft.Text(size=12)
        sample = ft.Column(spacing=2, tight=True)

        def refresh(_=None):
            plan = cat.reorganize_plan(self.tracks, root, layout.value)
            info.value = (f"{len(plan)} de {len(self.tracks)} arquivo(s) vão mudar de pasta. "
                          "Pastas que ficarem vazias serão apagadas." if plan else "Já está tudo organizado assim.")
            sample.controls = [ft.Text(f"• {os.path.relpath(d, root)}", size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS) for _, d in plan[:5]]
            if len(plan) > 5:
                sample.controls.append(ft.Text(f"… e mais {len(plan) - 5}", size=11, color=ft.Colors.ON_SURFACE_VARIANT))
            safe_update(info)
            safe_update(sample)

        layout.on_change = refresh
        refresh()

        async def run():
            plan = cat.reorganize_plan(self.tracks, root, layout.value)
            if not plan:
                return
            self.progress.visible = True
            self.status.value = "Movendo arquivos…"
            safe_update(self.view)

            def prog(done, total):
                self.progress.value = done / total
                self.status.value = f"Movendo arquivos… {done}/{total}"
                safe_update(self.progress)
                safe_update(self.status)

            ok, errs = await asyncio.to_thread(cat.reorganize, plan, root, prog)
            if errs:
                self.ctx.toast(f"{ok} movido(s); {len(errs)} erro(s): {errs[0]}", error=True)
            else:
                self.ctx.toast(f"{ok} arquivo(s) reorganizado(s)")
            self.on_files_changed()
            await self._scan()

        def apply(_):
            self.ctx.close_dialog()
            self.ctx.page.run_task(run)

        self.ctx.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Reorganizar pastas"),
            content=ft.Container(ft.Column([
                ft.Text("Move os arquivos baixados para pastas montadas a partir das informações de cada música "
                        "(os nomes dos arquivos não mudam).", size=13),
                layout, info, sample,
            ], tight=True, spacing=8, scroll=ft.ScrollMode.AUTO), width=480),
            actions=[ft.TextButton("Cancelar", on_click=self.ctx.close_dialog),
                     ft.FilledButton("Reorganizar", icon=ft.Icons.AUTO_FIX_HIGH, on_click=apply)],
        ))
