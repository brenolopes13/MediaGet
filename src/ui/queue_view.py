"""Tela da fila de downloads com progresso em tempo real."""
from __future__ import annotations

import os

import flet as ft

from core import library as lib
from core.downloader import DownloadJob
from ui.common import AppContext, mounted, safe_update

STATUS_STYLE = {
    "na fila": (ft.Icons.SCHEDULE, ft.Colors.ON_SURFACE_VARIANT),
    "baixando": (ft.Icons.DOWNLOADING, ft.Colors.PRIMARY),
    "processando": (ft.Icons.SETTINGS, ft.Colors.TERTIARY),
    "concluído": (ft.Icons.CHECK_CIRCLE, ft.Colors.GREEN),
    "erro": (ft.Icons.ERROR, ft.Colors.ERROR),
    "cancelado": (ft.Icons.CANCEL, ft.Colors.ON_SURFACE_VARIANT),
}


class JobCard:
    def __init__(self, ctx: AppContext, job: DownloadJob, on_removed):
        self.ctx = ctx
        self.job = job
        self.on_removed = on_removed
        self.icon = ft.Icon(ft.Icons.SCHEDULE, size=28)
        self.title = ft.Text(job.title, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.status = ft.Text(size=12)
        self.detail = ft.Text(size=12, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=2,
                              overflow=ft.TextOverflow.ELLIPSIS)
        self.bar = ft.ProgressBar(value=0, border_radius=4)
        self.errors = ft.Text(size=11, color=ft.Colors.ERROR, visible=False, selectable=True)
        self.actions = ft.Row(spacing=0, wrap=True)
        self.card = ft.Card(content=ft.Container(ft.Column([
            ft.Row([self.icon, ft.Column([self.title, self.status], spacing=2, expand=True)]),
            self.bar, self.detail, self.errors, self.actions,
        ], spacing=6), padding=14), margin=ft.Margin.only(bottom=8))
        job.on_update = self.refresh
        self.refresh(job, update=False)

    def refresh(self, job: DownloadJob = None, update=True):
        j = self.job
        icon, color = STATUS_STYLE.get(j.status, STATUS_STYLE["na fila"])
        self.icon.icon, self.icon.color = icon, color
        self.title.value = j.title
        parts = [j.status.capitalize()]
        if j.item_count and j.options.is_playlist:
            parts.append(f"item {j.item_index or '?'} de {j.item_count}")
        if j.status == "baixando" and j.progress:
            parts.append(f"{j.progress * 100:.0f}%")
        if j.speed:
            parts.append(j.speed)
        if j.eta:
            parts.append(f"faltam {j.eta}")
        self.status.value = " · ".join(parts)
        self.status.color = color
        self.detail.value = j.detail
        if j.status == "processando" or (j.status == "baixando" and not j.progress):
            self.bar.value = None  # indeterminado
        else:
            self.bar.value = j.progress
        self.bar.visible = not j.finished or j.status == "concluído"
        errs = j.errors[-3:]
        notes = [n for n in j.notes if n]
        self.errors.value = "\n".join(errs + (["ℹ " + n for n in notes] if j.finished else []))
        self.errors.visible = bool(self.errors.value)
        self.errors.color = ft.Colors.ERROR if errs else ft.Colors.ON_SURFACE_VARIANT
        self._build_actions()
        if update and mounted(self.card):
            try:
                safe_update(self.card)
            except Exception:
                pass

    def _build_actions(self):
        j = self.job
        a = []
        if not j.finished:
            a.append(ft.TextButton("Cancelar", icon=ft.Icons.STOP, on_click=lambda e: j.cancel()))
        else:
            if j.files:
                folder = os.path.dirname(j.files[-1])
                a.append(ft.TextButton("Ver na biblioteca", icon=ft.Icons.LIBRARY_MUSIC,
                                       on_click=lambda e: self._show_in_library(folder)))
                if lib.can_open_externally():
                    a.append(ft.TextButton("Abrir pasta", icon=ft.Icons.FOLDER_OPEN,
                                           on_click=lambda e: lib.open_external(folder)))
            if j.status in ("erro", "cancelado") or j.errors:
                a.append(ft.TextButton("Tentar de novo", icon=ft.Icons.REFRESH, on_click=self._retry))
            a.append(ft.TextButton("Remover", icon=ft.Icons.DELETE_OUTLINE, on_click=self._remove))
        a.append(ft.IconButton(ft.Icons.LINK, tooltip="Copiar link", icon_size=18,
                               on_click=lambda e: self.ctx.page.run_task(self.ctx.copy_text, j.options.url, "Link")))
        self.actions.controls = a

    def _show_in_library(self, folder):
        self.ctx.library_open(folder)

    def _retry(self, e):
        self.job = self.ctx.manager.retry(self.job)

    def _remove(self, e):
        self.ctx.manager.remove(self.job)


class QueueView:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cards: dict[str, JobCard] = {}
        self.list = ft.ListView(expand=True, spacing=0, padding=ft.Padding.only(bottom=24))
        self.empty = ft.Container(
            ft.Column([ft.Icon(ft.Icons.INBOX, size=64, color=ft.Colors.OUTLINE),
                       ft.Text("Nenhum download na fila", color=ft.Colors.ON_SURFACE_VARIANT),
                       ft.TextButton("Adicionar link", icon=ft.Icons.ADD, on_click=lambda e: ctx.go_to(0))],
                      horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            alignment=ft.Alignment.CENTER, expand=True,
        )
        self.summary = ft.Text(size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self.view = ft.Column([
            self.summary,
            ft.Row([ft.TextButton("Cancelar todos", icon=ft.Icons.STOP_CIRCLE, on_click=self.cancel_all),
                    ft.TextButton("Limpar concluídos", icon=ft.Icons.CLEAR_ALL,
                                  on_click=lambda e: ctx.manager.clear_finished())],
                   wrap=True, spacing=0),
            self.list,
            self.empty,
        ], expand=True)
        ctx.manager.on_change = self.rebuild
        self.rebuild(update=False)

    def cancel_all(self, e):
        for j in self.ctx.manager.jobs:
            if not j.finished:
                j.cancel()

    def rebuild(self, update=True):
        jobs = self.ctx.manager.jobs
        new_cards = {}
        for j in jobs:
            card = self.cards.get(j.id) or JobCard(self.ctx, j, self.rebuild)
            new_cards[j.id] = card
        self.cards = new_cards
        self.list.controls = [self.cards[j.id].card for j in jobs]
        self.empty.visible = not jobs
        self.list.visible = bool(jobs)
        active = self.ctx.manager.active_count
        self.summary.value = f"{len(jobs)} download(s) · {active} em andamento"
        if update and mounted(self.view):
            safe_update(self.view)
