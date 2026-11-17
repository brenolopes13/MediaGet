"""Tela principal: colar link, analisar, escolher formato/qualidade/organização e baixar."""
from __future__ import annotations

import asyncio
import os
import re

import flet as ft

from core import presets as P
from core.downloader import (DownloadJob, DownloadOptions, analyze, find_ffmpeg, fmt_duration,
                             preview_path, resolve_templates)
from ui.common import AppContext, dropdown, section, mounted, safe_update

URL_RE = re.compile(r"https?://\S+")


class DownloadView:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        s = ctx.settings
        self.info: dict | None = None
        self.entry_checks: list[ft.Checkbox] = []

        # ---------------------------------------------------------------- link
        self.url = ft.TextField(
            label="Link do vídeo, música ou playlist",
            hint_text="Cole aqui um ou mais links (um por linha)",
            multiline=True, min_lines=1, max_lines=4,
            prefix_icon=ft.Icons.LINK,
            on_submit=self.on_analyze,
            expand=True,
        )
        self.paste_btn = ft.IconButton(ft.Icons.CONTENT_PASTE, tooltip="Colar", on_click=self.on_paste)
        self.clear_btn = ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=self.on_clear)
        self.analyze_btn = ft.FilledButton("Analisar", icon=ft.Icons.SEARCH, on_click=self.on_analyze)
        self.busy = ft.ProgressRing(width=20, height=20, stroke_width=2, visible=False)

        # ---------------------------------------------------------------- prévia
        self.preview = ft.Column(visible=False, spacing=8)

        # ---------------------------------------------------------------- formato
        self.mode = ft.SegmentedButton(
            segments=[
                ft.Segment(value="video", label=ft.Text("Vídeo"), icon=ft.Icon(ft.Icons.MOVIE)),
                ft.Segment(value="audio", label=ft.Text("Somente áudio"), icon=ft.Icon(ft.Icons.MUSIC_NOTE)),
            ],
            selected=[s.mode],
            on_change=self.on_mode,
        )
        self.fmt = dropdown("Formato", {}, "", self.on_option)
        self.quality = dropdown("Qualidade", {}, "", self.on_option)
        self._fill_format_options()

        # ---------------------------------------------------------------- organização
        self.folder_dd = dropdown("Organizar em pastas", P.FOLDER_PRESETS, s.folder_preset, self.on_option)
        self.folder_custom = ft.TextField(label="Template de pastas", value=s.folder_custom, dense=True,
                                          on_change=self.on_option, helper=P.TEMPLATE_HELP,
                                          visible=s.folder_preset == "custom")
        self.file_dd = dropdown("Nome do arquivo", P.FILE_PRESETS, s.file_preset, self.on_option)
        self.file_custom = ft.TextField(label="Template do nome", value=s.file_custom, dense=True,
                                        on_change=self.on_option, visible=s.file_preset == "custom")
        self.path_preview = ft.Text(size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.dest = ft.Text(s.download_dir, size=12, expand=True, overflow=ft.TextOverflow.ELLIPSIS)

        # ---------------------------------------------------------------- metadados
        def sw(label, attr, tip=None):
            return ft.Switch(label=label, value=getattr(s, attr), data=attr, on_change=self.on_switch,
                             tooltip=tip)

        self.switches = [
            sw("Embutir metadados (título, artista, data…)", "embed_metadata"),
            sw("Embutir capa/miniatura no arquivo", "embed_thumbnail"),
            sw("Modo música (separa 'Artista - Música', álbum = playlist)", "music_mode"),
            sw("Salvar metadados completos (.info.json)", "write_info_json"),
            sw("Salvar miniatura como imagem", "write_thumbnail"),
            sw("Salvar descrição (.description)", "write_description"),
            sw("Guardar metadados em subpasta 'metadados'", "metadata_subfolder"),
            sw("Baixar legendas", "subtitles"),
        ]
        self.sub_langs = ft.TextField(label="Idiomas das legendas", value=s.sub_langs, dense=True,
                                      helper="Ex.: pt.*,en.*  (all = todos)", on_change=self.on_option,
                                      visible=s.subtitles)
        self.ff_warning = ft.Container(visible=False)

        self.download_btn = ft.FilledButton(
            "Baixar", icon=ft.Icons.DOWNLOAD, on_click=self.on_download,
            style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=28, vertical=18)),
        )

        self.view = ft.Column(
            [
                section("Link", ft.Row([self.url, self.paste_btn, self.clear_btn],
                                       vertical_alignment=ft.CrossAxisAlignment.START),
                        ft.Row([self.analyze_btn, self.busy]), self.preview, icon=ft.Icons.LINK),
                section("Formato e qualidade", self.mode,
                        ft.ResponsiveRow([ft.Container(self.fmt, col={"xs": 12, "sm": 6}),
                                          ft.Container(self.quality, col={"xs": 12, "sm": 6})]),
                        self.ff_warning, icon=ft.Icons.TUNE),
                section("Organização", self.folder_dd, self.folder_custom, self.file_dd, self.file_custom,
                        ft.Row([ft.Icon(ft.Icons.FOLDER, size=16), self.dest,
                                ft.TextButton("Alterar", icon=ft.Icons.FOLDER_OPEN, on_click=self.on_change_dest)]),
                        ft.Row([ft.Icon(ft.Icons.SUBDIRECTORY_ARROW_RIGHT, size=16), ft.Container(self.path_preview, expand=True)]),
                        icon=ft.Icons.FOLDER_COPY),
                ft.Card(content=ft.ExpansionTile(
                    title=ft.Text("Metadados e extras", weight=ft.FontWeight.W_600),
                    leading=ft.Icon(ft.Icons.LABEL, color=ft.Colors.PRIMARY),
                    controls=[ft.Container(ft.Column([*self.switches, self.sub_langs], spacing=4),
                                           padding=ft.Padding.only(left=16, right=16, bottom=12))],
                ), margin=ft.Margin.only(bottom=10)),
                ft.Row([self.download_btn], alignment=ft.MainAxisAlignment.END),
                ft.Container(height=24),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self.refresh_ffmpeg_warning()
        self.update_preview(update=False)

    # ======================================================================= helpers
    def _fill_format_options(self):
        s = self.ctx.settings
        if s.mode == "video":
            fmts, quals, fv, qv = P.VIDEO_FORMATS, P.VIDEO_QUALITIES, s.video_format, s.video_quality
            if self.info and self.info.get("heights"):
                avail = set(self.info["heights"])
                quals = {k: (v + ("" if k == "best" or any(h >= int(k) for h in avail) else " — indisponível"))
                         for k, v in quals.items()}
        else:
            fmts, quals, fv, qv = P.AUDIO_FORMATS, P.AUDIO_QUALITIES, s.audio_format, s.audio_quality
        self.fmt.options = [ft.DropdownOption(key=k, text=v) for k, v in fmts.items()]
        self.fmt.value = fv if fv in fmts else next(iter(fmts))
        self.quality.options = [ft.DropdownOption(key=k, text=v) for k, v in quals.items()]
        self.quality.value = qv if qv in quals else "best"
        self.quality.disabled = s.mode == "audio" and self.fmt.value in ("flac", "wav", "best")

    def refresh_ffmpeg_warning(self):
        has = bool(find_ffmpeg(self.ctx.settings.ffmpeg_path))
        self.ff_warning.visible = not has
        self.ff_warning.content = ft.Container(
            ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.ON_TERTIARY_CONTAINER),
                    ft.Text("ffmpeg não encontrado: conversão de formato, junção de vídeo em alta qualidade "
                            "e metadados embutidos ficam limitados. Veja Configurações.",
                            size=12, expand=True, color=ft.Colors.ON_TERTIARY_CONTAINER)]),
            bgcolor=ft.Colors.TERTIARY_CONTAINER, padding=10, border_radius=8,
        )

    def urls(self) -> list[str]:
        txt = self.url.value or ""
        found = URL_RE.findall(txt)
        return found or ([txt.strip()] if txt.strip() else [])

    def templates(self, is_playlist=None):
        s = self.ctx.settings
        if is_playlist is None:
            is_playlist = bool(self.info and self.info.get("is_playlist"))
        return resolve_templates(s.folder_preset, s.folder_custom, s.file_preset, s.file_custom, s.mode, is_playlist)

    def update_preview(self, update=True):
        s = self.ctx.settings
        folder_t, file_t = self.templates()
        ext = (s.video_format if s.mode == "video" else (s.audio_format if s.audio_format != "best" else "m4a"))
        sample = None
        if self.info:
            sample = dict(self.info.get("raw") or {})
            if self.info.get("is_playlist"):
                sample["playlist_title"] = self.info["title"]
                sample["playlist_index"] = 1
                if self.info.get("uploader"):
                    sample["playlist_uploader"] = self.info["uploader"]
                if self.info["entries"]:
                    sample["title"] = self.info["entries"][0]["title"]
        self.path_preview.value = "Exemplo: " + preview_path(folder_t, file_t, sample, ext)
        self.dest.value = s.download_dir
        if update:
            safe_update(self.view)

    # ======================================================================= eventos
    async def on_paste(self, e):
        txt = await self.ctx.paste_text()
        if txt:
            cur = (self.url.value or "").strip()
            self.url.value = (cur + "\n" + txt.strip()) if cur else txt.strip()
            safe_update(self.url)
            if len(self.urls()) == 1:
                await self.on_analyze(None)

    def on_clear(self, e):
        self.url.value = ""
        self.info = None
        self.preview.visible = False
        self.preview.controls.clear()
        self._fill_format_options()
        self.update_preview()

    async def on_analyze(self, e):
        urls = self.urls()
        if not urls:
            self.ctx.toast("Cole um link primeiro.", error=True)
            return
        if len(urls) > 1:
            self.info = None
            self.preview.controls = [ft.Text(f"{len(urls)} links detectados — todos serão baixados com as "
                                             "mesmas opções.", italic=True)]
            self.preview.visible = True
            safe_update(self.view)
            return
        self.analyze_btn.disabled = True
        self.busy.visible = True
        safe_update(self.view)
        try:
            self.info = await asyncio.to_thread(analyze, urls[0], self.ctx.settings.cookies_file)
            self._render_preview()
        except Exception as ex:
            self.info = None
            self.preview.controls = [ft.Text(f"Não foi possível ler o link: {str(ex).replace('ERROR: ', '')[:400]}",
                                             color=ft.Colors.ERROR)]
            self.preview.visible = True
        finally:
            self.analyze_btn.disabled = False
            self.busy.visible = False
            self._fill_format_options()
            self.update_preview(update=False)
            safe_update(self.view)

    def _render_preview(self):
        i = self.info
        thumb = (ft.Image(src=i["thumbnail"], width=160, height=90, fit=ft.BoxFit.COVER, border_radius=8,
                          error_content=ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED))
                 if i.get("thumbnail") else ft.Container(ft.Icon(ft.Icons.MOVIE, size=40), width=160, height=90,
                                                         bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=8,
                                                         alignment=ft.Alignment.CENTER))
        sub = " · ".join(x for x in [i.get("uploader"), i.get("extractor"),
                                     f"{len(i['entries'])} itens" if i["is_playlist"] else fmt_duration(i.get("duration"))] if x)
        head = ft.ResponsiveRow([
            ft.Container(thumb, col={"xs": 12, "sm": 4, "md": 3}),
            ft.Container(ft.Column([ft.Text(i["title"], weight=ft.FontWeight.BOLD, size=16, selectable=True),
                                    ft.Text(sub, size=12, color=ft.Colors.ON_SURFACE_VARIANT)], spacing=4),
                         col={"xs": 12, "sm": 8, "md": 9}),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        controls: list[ft.Control] = [head]

        self.entry_checks = []
        if i["is_playlist"]:
            for en in i["entries"]:
                self.entry_checks.append(ft.Checkbox(
                    label=f"{en['index']:>3}. {en['title']}" + (f"  ({fmt_duration(en['duration'])})" if en.get("duration") else ""),
                    value=True, data=en["index"], on_change=self._update_count,
                ))
            self.sel_count = ft.Text(size=12)
            controls += [
                ft.Row([
                    ft.TextButton("Marcar todos", icon=ft.Icons.CHECK_BOX, on_click=lambda e: self._check_all(True)),
                    ft.TextButton("Desmarcar todos", icon=ft.Icons.CHECK_BOX_OUTLINE_BLANK, on_click=lambda e: self._check_all(False)),
                    ft.TextButton("Inverter", icon=ft.Icons.SWAP_HORIZ, on_click=lambda e: self._check_all(None)),
                    self.sel_count,
                ], wrap=True),
                ft.Container(ft.ListView(self.entry_checks, spacing=0, height=min(300, 42 * len(self.entry_checks) + 8)),
                             border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), border_radius=8, padding=4),
            ]
            self._update_count(None, update=False)
        self.preview.controls = controls
        self.preview.visible = True

    def _check_all(self, val):
        for c in self.entry_checks:
            c.value = (not c.value) if val is None else val
        self._update_count(None)

    def _update_count(self, e, update=True):
        n = sum(1 for c in self.entry_checks if c.value)
        self.sel_count.value = f"{n} de {len(self.entry_checks)} selecionados"
        if update:
            safe_update(self.preview)

    def on_mode(self, e):
        self.ctx.settings.mode = (self.mode.selected or ["video"])[0]
        self._fill_format_options()
        self.ctx.settings.save()
        self.update_preview()

    def on_option(self, e):
        s = self.ctx.settings
        if s.mode == "video":
            s.video_format, s.video_quality = self.fmt.value, self.quality.value
        else:
            s.audio_format, s.audio_quality = self.fmt.value, self.quality.value
        self.quality.disabled = s.mode == "audio" and self.fmt.value in ("flac", "wav", "best")
        s.folder_preset = self.folder_dd.value
        s.file_preset = self.file_dd.value
        s.folder_custom = self.folder_custom.value or ""
        s.file_custom = self.file_custom.value or "%(title)s.%(ext)s"
        s.sub_langs = self.sub_langs.value or ""
        self.folder_custom.visible = s.folder_preset == "custom"
        self.file_custom.visible = s.file_preset == "custom"
        s.save()
        self.update_preview()

    def on_switch(self, e):
        setattr(self.ctx.settings, e.control.data, e.control.value)
        self.sub_langs.visible = self.ctx.settings.subtitles
        self.ctx.settings.save()
        safe_update(self.view)

    async def on_change_dest(self, e):
        p = await self.ctx.pick_folder("Pasta de destino", self.ctx.settings.download_dir)
        if p:
            self.ctx.settings.download_dir = p
            self.ctx.settings.save()
            self.update_preview()
            self.ctx.refresh_library()

    def on_download(self, e):
        urls = self.urls()
        if not urls:
            self.ctx.toast("Cole um link primeiro.", error=True)
            return
        s = self.ctx.settings
        folder_t, file_t = self.templates()
        ff = find_ffmpeg(s.ffmpeg_path)
        items = ""
        single = len(urls) == 1 and self.info and self.info.get("url") == urls[0]
        if single and self.info["is_playlist"]:
            chosen = [c.data for c in self.entry_checks if c.value]
            if not chosen:
                self.ctx.toast("Nenhum item da playlist selecionado.", error=True)
                return
            if len(chosen) != len(self.entry_checks):
                items = ",".join(map(str, chosen))
        for u in urls:
            is_pl = bool(single and self.info["is_playlist"]) or ("list=" in u and "watch" not in u) or "/playlist" in u
            folder_t, file_t = self.templates(is_pl)
            opts = DownloadOptions(
                url=u, base_dir=s.download_dir, mode=s.mode,
                video_format=s.video_format, video_quality=s.video_quality,
                audio_format=s.audio_format, audio_quality=s.audio_quality,
                folder_template=folder_t, file_template=file_t,
                embed_metadata=s.embed_metadata, embed_thumbnail=s.embed_thumbnail,
                write_info_json=s.write_info_json, write_thumbnail=s.write_thumbnail,
                write_description=s.write_description, subtitles=s.subtitles, sub_langs=s.sub_langs,
                metadata_subfolder=s.metadata_subfolder, music_mode=s.music_mode,
                playlist_items=items if single else "", is_playlist=is_pl,
                ffmpeg=ff, cookies_file=s.cookies_file,
                archive_file=os.path.join(s.download_dir, f".mediaget-arquivo-{s.mode}.txt") if s.use_archive else "",
            )
            title = self.info["title"] if single else u
            self.ctx.manager.add(DownloadJob(options=opts, title=title))
        self.ctx.toast(f"{len(urls)} download(s) adicionado(s) à fila")
        self.ctx.go_to(1)
