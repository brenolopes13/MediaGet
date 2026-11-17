"""Player de música embutido (barra inferior) com fila, anterior/próxima e aleatório."""
from __future__ import annotations

import base64
import os
import random
from typing import Callable, Optional

import flet as ft

from core import library as lib
from core.catalog import Track
from core.downloader import fmt_duration
from ui.common import AppContext, safe_update

try:
    import flet_audio as fta
except Exception:  # pragma: no cover
    fta = None


def cover_image(ctx: AppContext, path: str, size: float, radius: float = 8, icon=ft.Icons.MUSIC_NOTE,
                expand: bool = False) -> ft.Control:
    """Capa quadrada; sem capa mostra um ícone. No modo navegador envia a imagem em base64."""
    if path and os.path.isfile(path):
        src = path
        if ctx.page.web:
            try:
                with open(path, "rb") as f:
                    src = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
            except OSError:
                src = ""
        if src:
            img = ft.Image(src=src, fit=ft.BoxFit.COVER, width=None if expand else size,
                           height=None if expand else size, gapless_playback=True)
            return ft.Container(img, width=None if expand else size, height=None if expand else size,
                                border_radius=radius, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                                aspect_ratio=1 if expand else None)
    return ft.Container(ft.Icon(icon, size=size * 0.45, color=ft.Colors.ON_PRIMARY_CONTAINER),
                        width=None if expand else size, height=None if expand else size,
                        aspect_ratio=1 if expand else None,
                        bgcolor=ft.Colors.PRIMARY_CONTAINER, border_radius=radius, alignment=ft.Alignment.CENTER)


class Player:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.queue: list[Track] = []
        self.order: list[int] = []
        self.pos = -1
        self.shuffle = False
        self.playing = False
        self.duration_ms = 0
        self.position_ms = 0
        self.listeners: list[Callable[[Optional[Track]], None]] = []
        self.audio = None
        if fta is not None:
            self.audio = fta.Audio(
                volume=1.0,
                on_state_change=self._on_state,
                on_position_change=self._on_position,
                on_duration_change=self._on_duration,
            )
            ctx.page.services.append(self.audio)

        self.cover_slot = ft.Container(width=52, height=52)
        self.title = ft.Text("", weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.artist = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS)
        self.play_btn = ft.IconButton(ft.Icons.PLAY_CIRCLE_FILLED, icon_size=44, icon_color=ft.Colors.PRIMARY,
                                      tooltip="Tocar/pausar", on_click=self.toggle)
        self.shuffle_btn = ft.IconButton(ft.Icons.SHUFFLE, tooltip="Aleatório", on_click=self.toggle_shuffle)
        self.t_pos = ft.Text("0:00", size=11)
        self.t_dur = ft.Text("0:00", size=11)
        self.slider = ft.Slider(min=0, max=1, value=0, expand=True, on_change_end=self._seek)
        self.bar = ft.Container(
            ft.Column([
                ft.Row([
                    self.cover_slot,
                    ft.Column([self.title, self.artist], spacing=0, expand=True),
                    self.shuffle_btn,
                    ft.IconButton(ft.Icons.SKIP_PREVIOUS, tooltip="Anterior", on_click=lambda e: self.prev()),
                    self.play_btn,
                    ft.IconButton(ft.Icons.SKIP_NEXT, tooltip="Próxima", on_click=lambda e: self.next()),
                    ft.IconButton(ft.Icons.CLOSE, tooltip="Fechar player", icon_size=18, on_click=self.stop),
                ], spacing=4),
                ft.Row([self.t_pos, self.slider, self.t_dur], spacing=4),
            ], spacing=0),
            padding=ft.Padding.only(left=12, right=8, top=6, bottom=0),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=ft.Border.only(top=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
            visible=False,
        )

    # ------------------------------------------------------------------ estado
    @property
    def current(self) -> Optional[Track]:
        if 0 <= self.pos < len(self.order):
            return self.queue[self.order[self.pos]]
        return None

    def _notify(self):
        for fn in list(self.listeners):
            try:
                fn(self.current)
            except Exception:
                pass

    def _render(self):
        t = self.current
        self.bar.visible = t is not None
        if t:
            self.cover_slot.content = cover_image(self.ctx, t.cover, 52, 6)
            self.title.value = t.display_title
            self.artist.value = f"{t.artist} · {t.album}"
        self.play_btn.icon = ft.Icons.PAUSE_CIRCLE_FILLED if self.playing else ft.Icons.PLAY_CIRCLE_FILLED
        self.shuffle_btn.icon_color = ft.Colors.PRIMARY if self.shuffle else None
        self.slider.max = max(1, self.duration_ms)
        self.slider.value = min(self.position_ms, self.slider.max)
        self.t_pos.value = fmt_duration(self.position_ms / 1000) or "0:00"
        self.t_dur.value = fmt_duration(self.duration_ms / 1000) or "0:00"
        safe_update(self.bar)

    # ------------------------------------------------------------------ comandos
    def play_list(self, tracks: list[Track], start: int = 0, shuffle: Optional[bool] = None):
        if not tracks:
            return
        if shuffle is not None:
            self.shuffle = shuffle
        self.queue = list(tracks)
        self.order = list(range(len(tracks)))
        if shuffle is True:  # botão "Aleatório": embaralha tudo
            random.shuffle(self.order)
            self.pos = 0
        elif self.shuffle:  # clicou numa faixa com aleatório ligado: ela primeiro, o resto embaralhado
            start = max(0, min(start, len(tracks) - 1))
            rest = [i for i in self.order if i != start]
            random.shuffle(rest)
            self.order = [start] + rest
            self.pos = 0
        else:
            self.pos = max(0, min(start, len(tracks) - 1))
        self._load_current()

    def play_next(self, track: Track):
        """Coloca a faixa para tocar logo depois da atual."""
        if self.current is None:
            self.play_list([track])
            return
        self.queue.append(track)
        self.order.insert(self.pos + 1, len(self.queue) - 1)
        self.ctx.toast(f"Vai tocar a seguir: {track.display_title}")

    def _load_current(self):
        t = self.current
        if t is None:
            return
        self.position_ms = 0
        self.duration_ms = int(t.duration * 1000)
        if t.kind == "video" or self.audio is None:
            # vídeo (ou sem suporte a áudio): abre no player do sistema
            if lib.can_open_externally():
                lib.open_external(t.path)
            else:
                self.ctx.toast("Este arquivo não pode ser tocado aqui.", error=True)
            self.playing = False
            self._render()
            self._notify()
            return
        self.audio.src = t.path
        self.playing = True
        self._render()
        self._notify()
        self.ctx.page.run_task(self._play_async)

    async def _play_async(self):
        try:
            self.audio.update()
            await self.audio.play()
        except Exception as ex:
            self.playing = False
            self._render()
            self.ctx.toast(f"Não foi possível tocar: {ex}", error=True)

    def toggle(self, e=None):
        if self.current is None or self.audio is None:
            return
        self.ctx.page.run_task(self._pause_async if self.playing else self._resume_async)

    async def _pause_async(self):
        await self.audio.pause()
        self.playing = False
        self._render()

    async def _resume_async(self):
        await self.audio.resume()
        self.playing = True
        self._render()

    def next(self, auto: bool = False):
        if not self.order:
            return
        if self.pos + 1 < len(self.order):
            self.pos += 1
            self._load_current()
        elif auto:
            self.playing = False
            self.position_ms = 0
            self._render()
        else:
            self.pos = 0
            self._load_current()

    def prev(self):
        if not self.order:
            return
        if self.position_ms > 4000:  # como nos apps de streaming: volta ao início da faixa
            self.ctx.page.run_task(self._seek_to, 0)
            return
        self.pos = max(0, self.pos - 1)
        self._load_current()

    def toggle_shuffle(self, e=None):
        self.shuffle = not self.shuffle
        if self.order:
            cur = self.order[self.pos]
            rest = [i for i in range(len(self.queue)) if i != cur]
            if self.shuffle:
                random.shuffle(rest)
            self.order = [cur] + rest if self.shuffle else list(range(len(self.queue)))
            self.pos = 0 if self.shuffle else cur
        self._render()

    def stop(self, e=None):
        if self.audio is not None:
            self.ctx.page.run_task(self.audio.release)
        self.queue, self.order, self.pos = [], [], -1
        self.playing = False
        self._render()
        self._notify()

    async def _seek_to(self, ms: int):
        try:
            await self.audio.seek(ft.Duration(milliseconds=int(ms)))
            self.position_ms = int(ms)
            self._render()
        except Exception:
            pass

    def _seek(self, e):
        if self.audio is not None and self.current:
            self.ctx.page.run_task(self._seek_to, int(e.control.value))

    # ------------------------------------------------------------------ eventos do áudio
    def _on_state(self, e):
        st = e.state
        if st == fta.AudioState.COMPLETED:
            self.next(auto=True)
            return
        self.playing = st == fta.AudioState.PLAYING
        self._render()

    def _on_position(self, e):
        self.position_ms = int(e.position or 0)
        self._render()

    def _on_duration(self, e):
        try:
            self.duration_ms = int(e.duration.in_milliseconds)
        except Exception:
            pass
        self._render()
