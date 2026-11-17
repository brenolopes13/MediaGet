"""Biblioteca: navegar pelas pastas baixadas, renomear, copiar, mover, excluir e ver metadados."""
from __future__ import annotations

import datetime as dt
import os

import flet as ft

from core import library as lib
from core.downloader import fmt_size
from ui.catalog_view import CatalogView
from ui.common import AppContext, mounted, safe_update
from ui.player import Player

KIND_ICON = {
    "pasta": (ft.Icons.FOLDER, ft.Colors.AMBER),
    "audio": (ft.Icons.AUDIO_FILE, ft.Colors.PURPLE),
    "video": (ft.Icons.VIDEO_FILE, ft.Colors.BLUE),
    "imagem": (ft.Icons.IMAGE, ft.Colors.TEAL),
    "meta": (ft.Icons.DESCRIPTION, ft.Colors.BLUE_GREY),
    "outro": (ft.Icons.INSERT_DRIVE_FILE, ft.Colors.GREY),
}


class LibraryView:
    def __init__(self, ctx: AppContext, player: Player):
        self.ctx = ctx
        self.mode = "catalog"
        self.cwd = ctx.settings.download_dir
        self.selected: set[str] = set()
        self.entries: list[lib.Entry] = []

        self.breadcrumb = ft.Row(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)
        self.search = ft.TextField(hint_text="Buscar mídia em todas as subpastas…", prefix_icon=ft.Icons.SEARCH,
                                   dense=True, on_change=self.on_search, expand=True)
        self.only_media = ft.Checkbox(label="Só mídia", value=False, on_change=lambda e: self.load())
        self.with_sidecars = ft.Checkbox(label="Incluir metadados ao copiar/renomear", value=True,
                                         tooltip="Renomeia/copia junto .info.json, capas e legendas de mesmo nome")
        self.list = ft.ListView(expand=True, spacing=0)
        self.sel_bar_text = ft.Text(weight=ft.FontWeight.W_600)
        self.sel_bar = ft.Container(
            ft.Row([
                ft.IconButton(ft.Icons.CLOSE, tooltip="Limpar seleção", on_click=self.clear_selection),
                self.sel_bar_text,
                ft.IconButton(ft.Icons.SELECT_ALL, tooltip="Selecionar tudo", on_click=self.select_all),
                ft.IconButton(ft.Icons.DRIVE_FILE_RENAME_OUTLINE, tooltip="Renomear em lote", on_click=self.batch_rename_dialog),
                ft.IconButton(ft.Icons.COPY, tooltip="Copiar para…", on_click=lambda e: self.copy_move(list(self.selected), False)),
                ft.IconButton(ft.Icons.DRIVE_FILE_MOVE, tooltip="Mover para…", on_click=lambda e: self.copy_move(list(self.selected), True)),
                ft.IconButton(ft.Icons.CONTENT_COPY, tooltip="Copiar caminhos", on_click=self.copy_paths),
                ft.IconButton(ft.Icons.DELETE, tooltip="Excluir", icon_color=ft.Colors.ERROR,
                              on_click=lambda e: self.delete(list(self.selected))),
            ], spacing=0, wrap=True),
            bgcolor=ft.Colors.SECONDARY_CONTAINER, border_radius=10, padding=ft.Padding.symmetric(horizontal=4),
            visible=False,
        )
        self.files_view = ft.Column([
            ft.Row([
                ft.IconButton(ft.Icons.ARROW_UPWARD, tooltip="Pasta acima", on_click=self.go_up),
                ft.IconButton(ft.Icons.HOME, tooltip="Pasta de downloads", on_click=lambda e: self.open(ctx.settings.download_dir)),
                self.breadcrumb,
                ft.IconButton(ft.Icons.CREATE_NEW_FOLDER, tooltip="Nova pasta", on_click=self.new_folder),
                ft.IconButton(ft.Icons.REFRESH, tooltip="Atualizar", on_click=lambda e: self.load()),
            ]),
            ft.Row([self.search, self.only_media], wrap=False),
            self.with_sidecars,
            self.sel_bar,
            self.list,
        ], expand=True, spacing=6)
        self.catalog = CatalogView(ctx, player, on_files_changed=lambda: self.load(update=False))
        self.mode_switch = ft.SegmentedButton(
            selected=["catalog"], allow_multiple_selection=False, show_selected_icon=False,
            segments=[ft.Segment(value="catalog", label=ft.Text("Catálogo"), icon=ft.Icon(ft.Icons.GRID_VIEW)),
                      ft.Segment(value="files", label=ft.Text("Pastas e arquivos"), icon=ft.Icon(ft.Icons.FOLDER))],
            on_change=lambda e: self.set_mode(next(iter(e.control.selected), "catalog")),
        )
        self.body = ft.Container(self.catalog.view, expand=True)
        self.view = ft.Column([self.mode_switch, self.body], expand=True, spacing=10)
        ctx.refresh_library = self.refresh_all
        ctx.library_open = self.open_from_elsewhere

    # ================================================================ modo catálogo / pastas
    def set_mode(self, mode: str, update: bool = True):
        self.mode = mode
        self.mode_switch.selected = [mode]
        self.body.content = self.catalog.view if mode == "catalog" else self.files_view
        self.show(update)

    def show(self, update: bool = True):
        """Chamado ao entrar na aba Biblioteca."""
        if self.mode == "catalog":
            self.catalog.load(force=True)
        else:
            self.load(update=False)
        if update:
            safe_update(self.view)

    def refresh_all(self):
        self.load(update=False)
        self.catalog.tracks = []  # força reler no próximo acesso

    # ================================================================ navegação
    def open_from_elsewhere(self, path: str, files_mode: bool = True):
        self.ctx.go_to(2)
        if files_mode and self.mode != "files":
            self.set_mode("files")
        self.open(path)

    def open(self, path: str):
        if os.path.isdir(path):
            self.cwd = path
            self.selected.clear()
            self.search.value = ""
            self.load()

    def go_up(self, e):
        parent = os.path.dirname(self.cwd.rstrip("/\\"))
        if parent and parent != self.cwd:
            self.open(parent)

    def _render_breadcrumb(self):
        root = self.ctx.settings.download_dir
        parts = []
        if os.path.normcase(self.cwd).startswith(os.path.normcase(root)):
            rel = os.path.relpath(self.cwd, root)
            parts.append(("Downloads", root))
            acc = root
            if rel != ".":
                for p in rel.split(os.sep):
                    acc = os.path.join(acc, p)
                    parts.append((p, acc))
        else:
            parts.append((self.cwd, self.cwd))
        ctrls = []
        for i, (label, path) in enumerate(parts):
            if i:
                ctrls.append(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16))
            ctrls.append(ft.TextButton(label, on_click=lambda e, p=path: self.open(p)))
        self.breadcrumb.controls = ctrls

    def load(self, update=True):
        if not os.path.isdir(self.cwd):
            self.cwd = self.ctx.settings.download_dir
            os.makedirs(self.cwd, exist_ok=True)
        q = (self.search.value or "").strip().lower()
        if q:
            ents = [e for e in lib.walk_media(self.cwd) if q in e.name.lower()]
        else:
            ents = lib.list_dir(self.cwd)
            if self.only_media.value:
                ents = [e for e in ents if e.kind in ("pasta", "audio", "video")]
        self.entries = ents
        self.selected &= {e.path for e in ents}
        self._render_breadcrumb()
        self.list.controls = [self._row(e, show_folder=bool(q)) for e in ents] or [
            ft.Container(ft.Text("Pasta vazia" if not q else "Nada encontrado", color=ft.Colors.ON_SURFACE_VARIANT),
                         padding=30, alignment=ft.Alignment.CENTER)]
        self._update_sel_bar()
        if update and mounted(self.files_view):
            safe_update(self.files_view)

    def on_search(self, e):
        self.load()

    # ================================================================ linhas
    def _row(self, e: lib.Entry, show_folder=False) -> ft.Control:
        icon, color = KIND_ICON[e.kind]
        when = dt.datetime.fromtimestamp(e.mtime).strftime("%d/%m/%Y %H:%M")
        sub = when if e.is_dir else f"{fmt_size(e.size)} · {when}"
        if show_folder:
            sub = os.path.relpath(os.path.dirname(e.path), self.cwd) + " · " + sub
        menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            items=[
                ft.PopupMenuItem(content="Renomear", icon=ft.Icons.EDIT, on_click=lambda _, p=e.path: self.rename_dialog(p)),
                ft.PopupMenuItem(content="Copiar para…", icon=ft.Icons.COPY, on_click=lambda _, p=e.path: self.copy_move([p], False)),
                ft.PopupMenuItem(content="Mover para…", icon=ft.Icons.DRIVE_FILE_MOVE, on_click=lambda _, p=e.path: self.copy_move([p], True)),
                ft.PopupMenuItem(content="Duplicar", icon=ft.Icons.FILE_COPY, on_click=lambda _, p=e.path: self.duplicate(p)),
                ft.PopupMenuItem(content="Copiar caminho", icon=ft.Icons.CONTENT_COPY,
                                 on_click=lambda _, p=e.path: self.ctx.page.run_task(self.ctx.copy_text, p, "Caminho")),
                ft.PopupMenuItem(content="Copiar nome", icon=ft.Icons.TEXT_FIELDS,
                                 on_click=lambda _, n=e.name: self.ctx.page.run_task(self.ctx.copy_text, n, "Nome")),
                *([ft.PopupMenuItem(content="Ver metadados", icon=ft.Icons.INFO_OUTLINE,
                                    on_click=lambda _, p=e.path: self.show_metadata(p))] if e.kind in ("audio", "video") else []),
                *([ft.PopupMenuItem(content="Abrir", icon=ft.Icons.OPEN_IN_NEW,
                                    on_click=lambda _, p=e.path: lib.open_external(p))] if lib.can_open_externally() else []),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(content="Excluir", icon=ft.Icons.DELETE, on_click=lambda _, p=e.path: self.delete([p])),
            ],
        )
        cb = ft.Checkbox(value=e.path in self.selected, data=e.path, on_change=self.on_check)
        return ft.ListTile(
            leading=ft.Row([cb, ft.Icon(icon, color=color)], spacing=0, tight=True),
            title=ft.Text(e.name, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            subtitle=ft.Text(sub, size=11),
            trailing=menu,
            dense=True,
            on_click=lambda _, en=e: self.on_tap(en),
            on_long_press=lambda _, p=e.path: self.toggle(p),
        )

    def on_tap(self, e: lib.Entry):
        if self.selected:
            self.toggle(e.path)
        elif e.is_dir:
            self.open(e.path)
        elif e.kind in ("audio", "video"):
            self.show_metadata(e.path)
        elif lib.can_open_externally():
            lib.open_external(e.path)

    # ================================================================ seleção
    def on_check(self, e):
        self.toggle(e.control.data, e.control.value)

    def toggle(self, path, value=None):
        if value is None:
            value = path not in self.selected
        (self.selected.add if value else self.selected.discard)(path)
        self.load()

    def select_all(self, e):
        self.selected = {en.path for en in self.entries}
        self.load()

    def clear_selection(self, e):
        self.selected.clear()
        self.load()

    def _update_sel_bar(self):
        n = len(self.selected)
        self.sel_bar.visible = n > 0
        self.sel_bar_text.value = f"{n} selecionado(s)"

    # ================================================================ ações
    def _report(self, ok: int, errs: list[str], verb: str):
        if errs:
            self.ctx.toast(f"{ok} {verb}; {len(errs)} erro(s): {errs[0]}", error=True)
        else:
            self.ctx.toast(f"{ok} item(ns) {verb}")
        self.selected.clear()
        self.load()

    def rename_dialog(self, path: str):
        name = os.path.basename(path)
        stem, ext = (name, "") if os.path.isdir(path) else os.path.splitext(name)

        def do(new):
            try:
                lib.rename(path, new, self.with_sidecars.value)
                self.ctx.toast("Renomeado")
            except Exception as ex:
                self.ctx.toast(str(ex), error=True)
            self.load()

        self.ctx.prompt("Renomear", "Novo nome", stem, do, "Renomear",
                        helper=f"A extensão {ext} é mantida automaticamente" if ext else None)

    def batch_rename_dialog(self, e):
        paths = sorted(self.selected, key=lambda p: os.path.basename(p).lower())
        if not paths:
            return
        find = ft.TextField(label="Procurar", dense=True, expand=True)
        repl = ft.TextField(label="Substituir por", dense=True, expand=True)
        regex = ft.Checkbox(label="Expressão regular")
        prefix = ft.TextField(label="Prefixo", dense=True, expand=True)
        suffix = ft.TextField(label="Sufixo", dense=True, expand=True)
        numbering = ft.Checkbox(label="Numerar (01 - …)")
        start = ft.TextField(label="Início", value="1", width=90, dense=True)
        case = ft.Dropdown(label="Maiúsc./minúsc.", value="", dense=True, width=200, options=[
            ft.DropdownOption(key="", text="Não alterar"), ft.DropdownOption(key="title", text="Título Capitalizado"),
            ft.DropdownOption(key="upper", text="MAIÚSCULAS"), ft.DropdownOption(key="lower", text="minúsculas")])
        preview = ft.ListView(height=200, spacing=2)

        def plan():
            try:
                st = int(start.value or 1)
            except ValueError:
                st = 1
            return lib.batch_plan(paths, find.value or "", repl.value or "", prefix.value or "", suffix.value or "",
                                  numbering.value, st, max(2, len(str(st + len(paths)))), case.value or "",
                                  regex.value)

        def refresh(_=None):
            preview.controls = [
                ft.Text(f"{os.path.basename(o)}  →  {n}", size=12,
                        color=None if os.path.basename(o) == n else ft.Colors.PRIMARY)
                for o, n in plan()
            ]
            if mounted(preview):
                safe_update(preview)

        for c in (find, repl, prefix, suffix, start):
            c.on_change = refresh
        for c in (regex, numbering):
            c.on_change = refresh
        case.on_select = refresh
        refresh()

        def apply(_):
            self.ctx.close_dialog()
            ok, errs = lib.batch_rename(plan(), self.with_sidecars.value)
            self._report(ok, errs, "renomeado(s)")

        self.ctx.page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"Renomear {len(paths)} itens"),
            content=ft.Container(ft.Column([
                ft.Row([find, repl]), regex, ft.Row([prefix, suffix]),
                ft.Row([numbering, start], wrap=True), case,
                ft.Text("Pré-visualização", weight=ft.FontWeight.W_600), preview,
            ], tight=True, scroll=ft.ScrollMode.AUTO), width=560),
            actions=[ft.TextButton("Cancelar", on_click=self.ctx.close_dialog),
                     ft.FilledButton("Renomear", on_click=apply)],
        ))

    async def _copy_move_async(self, paths, move):
        dest = await self.ctx.pick_folder("Mover para…" if move else "Copiar para…")
        if not dest:
            return
        ok, errs = lib.copy_to(paths, dest, move=move, with_sidecars=self.with_sidecars.value)
        self._report(ok, errs, "movido(s)" if move else "copiado(s)")

    def copy_move(self, paths, move):
        if paths:
            self.ctx.page.run_task(self._copy_move_async, paths, move)

    def duplicate(self, path):
        try:
            lib.duplicate(path)
            self.ctx.toast("Cópia criada")
        except Exception as ex:
            self.ctx.toast(str(ex), error=True)
        self.load()

    def copy_paths(self, e):
        self.ctx.page.run_task(self.ctx.copy_text, "\n".join(sorted(self.selected)), "Caminhos")

    def delete(self, paths):
        if not paths:
            return
        names = ", ".join(os.path.basename(p) for p in paths[:3]) + ("…" if len(paths) > 3 else "")

        def do():
            ok, errs = lib.delete(paths, self.with_sidecars.value)
            self._report(ok, errs, "excluído(s)")

        self.ctx.confirm("Excluir definitivamente?", f"{len(paths)} item(ns): {names}\nEssa ação não pode ser desfeita.",
                         do, "Excluir", danger=True)

    def new_folder(self, e):
        def do(name):
            try:
                lib.make_folder(self.cwd, name)
            except Exception as ex:
                self.ctx.toast(str(ex), error=True)
            self.load()

        self.ctx.prompt("Nova pasta", "Nome da pasta", "", do, "Criar")

    def show_metadata(self, path):
        meta = lib.read_metadata(path)
        rows = [ft.Text(os.path.basename(path), weight=ft.FontWeight.BOLD, selectable=True)]
        if not meta:
            rows.append(ft.Text("Nenhum metadado encontrado. Ative 'Salvar metadados (.info.json)' ou "
                                "'Embutir metadados' ao baixar.", color=ft.Colors.ON_SURFACE_VARIANT))
        for k, v in meta.items():
            v = str(v)
            rows.append(ft.Column([ft.Text(k, size=11, color=ft.Colors.PRIMARY),
                                   ft.Text(v if len(v) < 600 else v[:600] + "…", size=13, selectable=True)], spacing=0))
        actions = [ft.TextButton("Copiar caminho", icon=ft.Icons.CONTENT_COPY,
                                 on_click=lambda e: self.ctx.page.run_task(self.ctx.copy_text, path, "Caminho"))]
        if meta.get("webpage_url"):
            actions.append(ft.TextButton("Copiar link original", icon=ft.Icons.LINK,
                                         on_click=lambda e: self.ctx.page.run_task(self.ctx.copy_text, meta["webpage_url"], "Link")))
        if lib.can_open_externally():
            actions.append(ft.TextButton("Abrir", icon=ft.Icons.PLAY_ARROW, on_click=lambda e: lib.open_external(path)))
        actions.append(ft.TextButton("Fechar", on_click=self.ctx.close_dialog))
        self.ctx.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Metadados"),
            content=ft.Container(ft.Column(rows, scroll=ft.ScrollMode.AUTO, spacing=8, tight=True), width=520, height=420),
            actions=actions,
        ))
