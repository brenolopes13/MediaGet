"""MediaGet — baixador de áudio e vídeo com yt-dlp (Windows, Linux e Android)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import flet as ft  # noqa: E402

from core.config import Settings  # noqa: E402
from core.downloader import DownloadManager  # noqa: E402
from ui.common import AppContext  # noqa: E402
from ui.download_view import DownloadView  # noqa: E402
from ui.library_view import LibraryView  # noqa: E402
from ui.player import Player  # noqa: E402
from ui.queue_view import QueueView  # noqa: E402
from ui.settings_view import SettingsView  # noqa: E402

NAV = [
    (ft.Icons.DOWNLOAD_OUTLINED, ft.Icons.DOWNLOAD, "Baixar"),
    (ft.Icons.QUEUE_OUTLINED, ft.Icons.QUEUE, "Fila"),
    (ft.Icons.LIBRARY_MUSIC_OUTLINED, ft.Icons.LIBRARY_MUSIC, "Biblioteca"),
    (ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS, "Ajustes"),
]


def main(page: ft.Page):
    settings = Settings.load()
    manager = DownloadManager(settings.max_parallel)
    ctx = AppContext(page, settings, manager)

    page.title = "MediaGet"
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.DEEP_PURPLE)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.DEEP_PURPLE)
    page.padding = 0

    def apply_theme():
        page.theme_mode = {"light": ft.ThemeMode.LIGHT, "dark": ft.ThemeMode.DARK}.get(settings.theme, ft.ThemeMode.SYSTEM)
        page.update()

    if not ctx.is_mobile:
        try:
            page.window.width, page.window.height = 1000, 760
            page.window.min_width, page.window.min_height = 420, 560
        except Exception:
            pass

    download = DownloadView(ctx)
    queue = QueueView(ctx)
    player = Player(ctx)
    library = LibraryView(ctx, player)
    settings_v = SettingsView(ctx, apply_theme, lambda: download.refresh_ffmpeg_warning())
    views = [download.view, queue.view, library.view, settings_v.view]

    body = ft.Container(views[0], expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=12))
    titles = ["Baixar mídia", "Fila de downloads", "Biblioteca", "Configurações"]
    title = ft.Text(titles[0], size=20, weight=ft.FontWeight.BOLD)
    badge = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

    rail = ft.NavigationRail(
        selected_index=0, label_type=ft.NavigationRailLabelType.ALL, min_width=88,
        leading=ft.Container(ft.Icon(ft.Icons.CLOUD_DOWNLOAD, size=34, color=ft.Colors.PRIMARY),
                             padding=ft.Padding.only(top=16, bottom=8)),
        destinations=[ft.NavigationRailDestination(icon=i, selected_icon=si, label=l) for i, si, l in NAV],
        on_change=lambda e: go_to(e.control.selected_index),
    )
    bar = ft.NavigationBar(
        selected_index=0,
        destinations=[ft.NavigationBarDestination(icon=i, selected_icon=si, label=l) for i, si, l in NAV],
        on_change=lambda e: go_to(e.control.selected_index),
    )

    def go_to(i: int):
        rail.selected_index = bar.selected_index = i
        body.content = views[i]
        title.value = titles[i]
        if i == 2:
            library.show(update=False)
        page.update()

    ctx.go_to = go_to

    def update_badge():
        n = manager.active_count
        badge.value = f"{n} baixando" if n else ""

    # atualiza o contador do topo quando algo muda na fila
    old_rebuild = queue.rebuild

    def rebuild_and_badge(update=True):
        old_rebuild(update)
        update_badge()
        if update:
            try:
                badge.update()
            except Exception:
                pass

    manager.on_change = rebuild_and_badge
    queue.rebuild = rebuild_and_badge

    header = ft.Container(ft.Row([title, ft.Container(expand=True), badge]),
                          padding=ft.Padding.only(left=16, right=16, top=12))
    content = ft.Column([header, body, player.bar], expand=True, spacing=0)

    def layout():
        wide = (page.width or 1000) >= 720 and not ctx.is_mobile
        page.controls.clear()
        if wide:
            page.navigation_bar = None
            page.add(ft.Row([rail, ft.VerticalDivider(width=1), content], expand=True, spacing=0))
        else:
            page.navigation_bar = bar
            page.add(ft.SafeArea(content, expand=True))
        page.update()

    state = {"wide": None}

    def on_resize(e):
        wide = (page.width or 1000) >= 720 and not ctx.is_mobile
        if wide != state["wide"]:
            state["wide"] = wide
            layout()

    page.on_resize = on_resize
    apply_theme()
    state["wide"] = (page.width or 1000) >= 720 and not ctx.is_mobile
    layout()

    # loop leve para manter o contador "baixando" atualizado enquanto a fila trabalha
    async def ticker():
        import asyncio

        last = None
        while True:
            await asyncio.sleep(1)
            update_badge()
            if badge.value != last:
                last = badge.value
                queue.summary.value = f"{len(manager.jobs)} download(s) · {manager.active_count} em andamento"
                try:
                    page.update()
                except Exception:
                    pass

    page.run_task(ticker)


if __name__ == "__main__":
    if "--web" in sys.argv:
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=8550)
    else:
        ft.run(main)
