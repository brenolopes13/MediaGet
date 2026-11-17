"""Android: pede acesso aos arquivos para gravar em Download/MediaGet e ler a biblioteca.

No Android 11+ só a permissão "Acesso a todos os arquivos" deixa o app abrir arquivos que
ele não criou (por exemplo, os de uma instalação anterior) e ler a biblioteca de músicas.
"""
from __future__ import annotations

import flet as ft

from core.config import dir_writable
from ui.common import AppContext

try:
    import flet_permission_handler as fph
except Exception:  # pragma: no cover - fora do Android/sem o pacote
    fph = None


class AndroidAccess:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.ph = None
        if fph is not None:
            self.ph = fph.PermissionHandler()
            ctx.page.services.append(self.ph)

    async def _granted(self) -> bool:
        try:
            st = await self.ph.get_status(fph.Permission.MANAGE_EXTERNAL_STORAGE)
            return st == fph.PermissionStatus.GRANTED
        except Exception:
            return False

    async def check(self):
        """Na abertura do app: se não tem acesso, explica e oferece abrir a tela de permissão."""
        if self.ph is None or await self._granted():
            return
        self.ctx.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Permitir acesso aos arquivos"),
            content=ft.Text(
                "Para salvar os downloads na pasta Download/MediaGet e mostrar suas músicas na "
                "Biblioteca, o MediaGet precisa do acesso a todos os arquivos.\n\n"
                "Na tela que vai abrir, ative \"Permitir acesso para gerenciar todos os arquivos\" "
                "e volte para o app."),
            actions=[
                ft.TextButton("Agora não", on_click=self.ctx.close_dialog),
                ft.FilledButton("Permitir", on_click=self._request),
            ],
        ))

    async def _request(self, e=None):
        self.ctx.close_dialog()
        try:
            await self.ph.request(fph.Permission.MANAGE_EXTERNAL_STORAGE)
            await self.ph.request(fph.Permission.STORAGE)  # Android 10 ou mais antigo
        except Exception as ex:
            self.ctx.toast(f"Não foi possível pedir a permissão: {ex}", error=True)
            return
        if await self._granted() or dir_writable(self.ctx.settings.download_dir):
            self.ctx.toast("Acesso aos arquivos liberado.")
        else:
            self.ctx.toast("Sem acesso aos arquivos: os downloads podem falhar.", error=True)
