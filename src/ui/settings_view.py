"""Tela de configurações."""
from __future__ import annotations

import asyncio
import sys

import flet as ft
import yt_dlp

from core.downloader import find_ffmpeg
from ui.common import AppContext, section, mounted, safe_update


class SettingsView:
    def __init__(self, ctx: AppContext, on_theme, on_ffmpeg_change):
        self.ctx = ctx
        s = ctx.settings
        self.on_theme = on_theme
        self.on_ffmpeg_change = on_ffmpeg_change

        self.dir = ft.TextField(label="Pasta de downloads", value=s.download_dir, dense=True, expand=True,
                                on_blur=self.save_dir, on_submit=self.save_dir)
        self.ff = ft.TextField(label="Caminho do ffmpeg (vazio = detectar automaticamente)", value=s.ffmpeg_path,
                               dense=True, expand=True, on_blur=self.save_ff, on_submit=self.save_ff)
        self.ff_status = ft.Text(size=12)
        self.cookies = ft.TextField(label="Arquivo de cookies (opcional, formato Netscape)", value=s.cookies_file,
                                    dense=True, expand=True, on_blur=self.save_cookies, on_submit=self.save_cookies,
                                    helper="Útil para vídeos com restrição de idade ou conteúdo de membros.")
        self.parallel = ft.Slider(min=1, max=5, divisions=4, value=s.max_parallel, label="{value}",
                                  on_change_end=self.save_parallel, expand=True)
        self.archive = ft.Switch(label="Pular itens já baixados (útil para atualizar playlists)", value=s.use_archive,
                                 on_change=self.save_archive)
        self.theme = ft.SegmentedButton(
            segments=[ft.Segment(value="system", label=ft.Text("Sistema"), icon=ft.Icon(ft.Icons.BRIGHTNESS_AUTO)),
                      ft.Segment(value="light", label=ft.Text("Claro"), icon=ft.Icon(ft.Icons.LIGHT_MODE)),
                      ft.Segment(value="dark", label=ft.Text("Escuro"), icon=ft.Icon(ft.Icons.DARK_MODE))],
            selected=[s.theme], on_change=self.save_theme,
        )
        self.version = ft.Text(f"yt-dlp {yt_dlp.version.__version__} · Python {sys.version.split()[0]}", size=12)
        self.update_btn = ft.OutlinedButton("Atualizar yt-dlp", icon=ft.Icons.SYSTEM_UPDATE, on_click=self.update_ytdlp)

        browse_ff = ft.IconButton(ft.Icons.FILE_OPEN, tooltip="Procurar", on_click=self.pick_ff,
                                  visible=not ctx.is_mobile)
        self.view = ft.Column([
            section("Armazenamento",
                    ft.Row([self.dir, ft.IconButton(ft.Icons.FOLDER_OPEN, tooltip="Escolher", on_click=self.pick_dir)]),
                    self.archive, icon=ft.Icons.SAVE),
            section("Downloads",
                    ft.Row([ft.Text("Downloads simultâneos"), self.parallel]),
                    ft.Row([self.cookies, ft.IconButton(ft.Icons.FILE_OPEN, tooltip="Procurar", on_click=self.pick_cookies)]),
                    icon=ft.Icons.DOWNLOAD),
            section("ffmpeg (conversão e metadados)",
                    ft.Row([self.ff, browse_ff]), self.ff_status,
                    ft.Text("No Windows/Linux: instale o ffmpeg (winget install ffmpeg / sudo apt install ffmpeg) "
                            "ou o pacote Python 'imageio-ffmpeg'. As versões Windows e Android já trazem "
                            "o ffmpeg embutido.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    icon=ft.Icons.BUILD),
            section("Aparência", self.theme, icon=ft.Icons.PALETTE),
            section("Sobre", self.version, ft.Row([self.update_btn]),
                    ft.Text("Use apenas para conteúdo que você tem direito de baixar.", size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT), icon=ft.Icons.INFO),
        ], scroll=ft.ScrollMode.AUTO, expand=True)
        self.refresh_ff(update=False)

    def refresh_ff(self, update=True):
        p = find_ffmpeg(self.ctx.settings.ffmpeg_path)
        self.ff_status.value = f"✔ ffmpeg encontrado: {p}" if p else "✖ ffmpeg não encontrado"
        self.ff_status.color = ft.Colors.GREEN if p else ft.Colors.ERROR
        if update:
            safe_update(self.view)
        self.on_ffmpeg_change()

    # ---------------------------------------------------------------- handlers
    def save_dir(self, e=None):
        import os

        v = (self.dir.value or "").strip()
        if v:
            try:
                os.makedirs(v, exist_ok=True)
                self.ctx.settings.download_dir = v
                self.ctx.settings.save()
                self.ctx.refresh_library()
            except OSError as ex:
                self.ctx.toast(f"Pasta inválida: {ex}", error=True)

    async def pick_dir(self, e):
        p = await self.ctx.pick_folder("Pasta de downloads", self.ctx.settings.download_dir)
        if p:
            self.dir.value = p
            self.save_dir()
            safe_update(self.view)

    def save_ff(self, e=None):
        self.ctx.settings.ffmpeg_path = (self.ff.value or "").strip()
        self.ctx.settings.save()
        self.refresh_ff()

    async def pick_ff(self, e):
        p = await self.ctx.pick_file("Localizar ffmpeg")
        if p:
            self.ff.value = p
            self.save_ff()

    def save_cookies(self, e=None):
        self.ctx.settings.cookies_file = (self.cookies.value or "").strip()
        self.ctx.settings.save()

    async def pick_cookies(self, e):
        p = await self.ctx.pick_file("Arquivo de cookies")
        if p:
            self.cookies.value = p
            self.save_cookies()
            safe_update(self.view)

    def save_parallel(self, e):
        self.ctx.settings.max_parallel = int(self.parallel.value)
        self.ctx.settings.save()
        self.ctx.manager.set_parallel(int(self.parallel.value))

    def save_archive(self, e):
        self.ctx.settings.use_archive = self.archive.value
        self.ctx.settings.save()

    def save_theme(self, e):
        self.ctx.settings.theme = (self.theme.selected or ["system"])[0]
        self.ctx.settings.save()
        self.on_theme()

    async def update_ytdlp(self, e):
        """Atualiza o yt-dlp via pip (somente desktop, fora de executáveis empacotados)."""
        if self.ctx.is_mobile or getattr(sys, "frozen", False):
            self.ctx.toast("Neste modo, atualize instalando a nova versão do app.", error=True)
            return
        self.update_btn.disabled = True
        self.update_btn.content = "Atualizando…"
        safe_update(self.view)
        proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "pip", "install", "-U", "yt-dlp",
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        self.update_btn.disabled = False
        self.update_btn.content = "Atualizar yt-dlp"
        if proc.returncode == 0:
            self.ctx.toast("yt-dlp atualizado. Reinicie o app para usar a nova versão.")
        else:
            self.ctx.toast("Falha ao atualizar: " + out.decode(errors="ignore")[-200:], error=True)
        safe_update(self.view)
