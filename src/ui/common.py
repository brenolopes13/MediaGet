"""Utilidades de interface compartilhadas entre as telas."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

import flet as ft

if TYPE_CHECKING:
    from core.config import Settings
    from core.downloader import DownloadManager


class AppContext:
    """Objeto passado para todas as telas com estado global e atalhos."""

    def __init__(self, page: ft.Page, settings: "Settings", manager: "DownloadManager"):
        self.page = page
        self.settings = settings
        self.manager = manager
        self.picker = ft.FilePicker()
        self.clipboard = ft.Clipboard()
        page.services.append(self.picker)
        page.services.append(self.clipboard)
        self.is_mobile = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
        self.go_to: Callable[[int], None] = lambda i: None
        self.refresh_library: Callable[[], None] = lambda: None

    # ------------------------------------------------------------------ avisos
    def toast(self, msg: str, error: bool = False):
        self.page.show_dialog(ft.SnackBar(
            content=ft.Text(msg, color=ft.Colors.ON_ERROR_CONTAINER if error else None),
            bgcolor=ft.Colors.ERROR_CONTAINER if error else None,
            duration=4000 if error else 2500,
        ))

    def close_dialog(self, *_):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def confirm(self, title: str, text: str, on_yes: Callable[[], None], yes_label: str = "Confirmar",
                danger: bool = False):
        def yes(_):
            self.close_dialog()
            on_yes()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(text),
            actions=[
                ft.TextButton("Cancelar", on_click=self.close_dialog),
                ft.FilledButton(yes_label, on_click=yes,
                                style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR) if danger else None),
            ],
        ))

    def prompt(self, title: str, label: str, value: str, on_ok: Callable[[str], None], ok_label: str = "OK",
               helper: Optional[str] = None):
        field = ft.TextField(label=label, value=value, autofocus=True, helper=helper)

        def ok(_=None):
            v = (field.value or "").strip()
            if not v:
                return
            self.close_dialog()
            on_ok(v)

        field.on_submit = ok
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Container(field, width=420),
            actions=[ft.TextButton("Cancelar", on_click=self.close_dialog), ft.FilledButton(ok_label, on_click=ok)],
        ))

    # ------------------------------------------------------------------ serviços
    async def pick_folder(self, title: str = "Escolher pasta", initial: Optional[str] = None) -> Optional[str]:
        try:
            return await self.picker.get_directory_path(dialog_title=title, initial_directory=initial)
        except Exception as ex:
            self.toast(f"Seletor de pastas indisponível: {ex}", error=True)
            return None

    async def pick_file(self, title: str = "Escolher arquivo") -> Optional[str]:
        try:
            files = await self.picker.pick_files(dialog_title=title, allow_multiple=False)
            return files[0].path if files else None
        except Exception as ex:
            self.toast(f"Seletor de arquivos indisponível: {ex}", error=True)
            return None

    async def copy_text(self, text: str, what: str = "Texto"):
        try:
            await self.clipboard.set(text)
            self.toast(f"{what} copiado para a área de transferência")
        except Exception as ex:
            self.toast(f"Não foi possível copiar: {ex}", error=True)

    async def paste_text(self) -> str:
        try:
            return (await self.clipboard.get()) or ""
        except Exception:
            return ""


def section(title: str, *controls: ft.Control, icon=None) -> ft.Card:
    header = ft.Row([ft.Icon(icon, size=20, color=ft.Colors.PRIMARY)] if icon else [], spacing=8)
    header.controls.append(ft.Text(title, weight=ft.FontWeight.W_600, size=15))
    return ft.Card(
        content=ft.Container(ft.Column([header, *controls], spacing=12), padding=16),
        margin=ft.Margin.only(bottom=10),
    )


def dropdown(label: str, options: dict, value: str, on_select=None, expand=True) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        value=value,
        options=[ft.DropdownOption(key=k, text=v[0] if isinstance(v, tuple) else v) for k, v in options.items()],
        on_select=on_select,
        expand=expand,
        dense=True,
    )


def mounted(ctrl) -> bool:
    """True se o controle já está na página (no Flet 1.x, .page levanta erro quando não está)."""
    try:
        return ctrl.page is not None
    except RuntimeError:
        return False


def safe_update(ctrl) -> None:
    """Atualiza o controle somente se ele estiver visível na página."""
    if mounted(ctrl):
        try:
            ctrl.update()
        except RuntimeError:
            pass
