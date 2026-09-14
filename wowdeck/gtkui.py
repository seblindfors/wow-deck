"""Touch-friendly GTK4 front end for WoW Deck (PyGObject ships with SteamOS). Falls back to
the kdialog layer when GTK is unavailable. The existing flow code keeps calling `ui.*`; this
module replaces those functions with GTK dialogs that are safe to call from a worker thread."""
from __future__ import annotations
import contextlib, io, os, re, subprocess, sys, threading

try:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import GLib, Gtk, Gdk, Gio, Pango  # noqa: E402
    AVAILABLE = True
except Exception:          # pragma: no cover
    AVAILABLE = False

from . import ui

CSS = b"""
window { background: #1b1426; }
label { color: #e9e2f2; }
.title { font-size: 26px; font-weight: 800; color: #f3e6ff; }
.subtitle { font-size: 15px; color: #b9a7d6; }
.big { min-height: 88px; font-size: 21px; font-weight: 700; border-radius: 16px; padding: 10px 18px;
       background: #2b2140; color: #f3e6ff; border: 2px solid #4b3a6e; }
.big:hover, .big:active { background: #3a2c57; }
.accent { background: #6d3fc3; border-color: #a583ff; }
.accent:hover { background: #7f52d8; }
.danger { border-color: #c0553f; }
.row { min-height: 58px; font-size: 18px; border-radius: 12px; padding: 4px 16px; background: #241b35; border: 2px solid #3d2f5a; color: #e9e2f2; }
.row:checked { background: #3d2a63; border-color: #c9a227; }
.row.required { border-color: #6d5a2a; }
.log { font-family: monospace; font-size: 15px; background: #120d1b; color: #d8cff0; padding: 12px; border-radius: 12px; }
.card { background: #221a31; border-radius: 18px; padding: 18px; }
.status { font-size: 18px; color: #c9a227; font-weight: 700; }
.h2 { font-size: 22px; font-weight: 800; color: #c9a227; margin-top: 10px; }
.term { font-size: 18px; font-weight: 700; color: #f3e6ff; }
.body { font-size: 17px; color: #d8cff0; line-height: 1.35; }
.iconbtn { min-width: 60px; min-height: 60px; border-radius: 30px; font-size: 28px; font-weight: 800; padding: 0;
           background: #2b2140; color: #c9a227; border: 2px solid #4b3a6e; }
.iconbtn:hover, .iconbtn:active { background: #3a2c57; }
.dialog { background: #1b1426; }
entry { font-size: 20px; min-height: 52px; border-radius: 12px; }
"""

LOGO = ui.LOGO
_app_ref: dict = {}


def _on_main(fn):
    """Run fn on the GTK main thread and return its result (blocks the calling worker)."""
    if threading.current_thread() is threading.main_thread():
        return fn()
    done = threading.Event(); box = {}
    def wrap():
        try:
            box['v'] = fn()
        except Exception as e:      # pragma: no cover
            box['e'] = e
        done.set(); return False
    GLib.idle_add(wrap); done.wait()
    if 'e' in box:
        raise box['e']
    return box.get('v')


def _screen_height() -> int:
    try:
        mon = Gdk.Display.get_default().get_monitors()[0]
        return mon.get_geometry().height
    except Exception:
        return 800


def _dialog(title: str, body: Gtk.Widget, buttons: list[tuple[str, str, str]]):
    """Modal dialog with big buttons. buttons: (id, label, css). Returns chosen id or None.
    The body scrolls; the window never exceeds the screen so the buttons stay reachable."""
    win = _app_ref.get('win')
    max_h = max(420, _screen_height() - 120)
    dlg = Gtk.Window(transient_for=win, modal=True, title='WoW Deck', decorated=True, default_width=760)
    dlg.add_css_class('dialog')
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12, margin_start=20, margin_end=20)
    v.append(_header(title))
    sw = Gtk.ScrolledWindow(vexpand=True, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.set_max_content_height(max_h - 230)
    sw.set_child(body)
    v.append(sw)
    hb = Gtk.Box(spacing=12, homogeneous=True)
    result = {}
    loop = GLib.MainLoop()
    for bid, label, css in buttons:
        b = Gtk.Button(label=label); b.add_css_class('big'); b.add_css_class(css) if css else None
        def clicked(_b, bid=bid):
            result['id'] = bid; dlg.close()
        b.connect('clicked', clicked); hb.append(b)
    v.append(hb); dlg.set_child(v)
    dlg.connect('close-request', lambda *_: (loop.quit(), False)[1])
    dlg.present()
    GLib.idle_add(lambda: (sw.get_vadjustment().set_value(0), False)[1])   # GTK may open long bodies mid-scroll
    loop.run()
    return result.get('id')


def _header(title: str, sub: str = '', trailing: Gtk.Widget | None = None) -> Gtk.Widget:
    h = Gtk.Box(spacing=16)
    if os.path.isfile(LOGO):
        img = Gtk.Image.new_from_file(LOGO); img.set_pixel_size(56); h.append(img)
    t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    l = Gtk.Label(label=title, xalign=0, wrap=True); l.add_css_class('title'); t.append(l)
    if sub:
        s = Gtk.Label(label=sub, xalign=0, wrap=True); s.add_css_class('subtitle'); t.append(s)
    t.set_hexpand(True); h.append(t)
    if trailing is not None:
        trailing.set_valign(Gtk.Align.CENTER); h.append(trailing)
    return h


# ------------------------------------------------------------------ ui.* replacements

def gtk_header(text: str, sub: str = '') -> str:
    return text + ('\n' + sub if sub else '')


def gtk_info(text: str) -> None:
    def show():
        l = Gtk.Label(label=text, wrap=True, xalign=0, selectable=True); l.set_max_width_chars(70)
        _dialog('WoW Deck', l, [('ok', 'OK', 'accent')])
    _on_main(show)


def gtk_error(text: str) -> None:
    def show():
        l = Gtk.Label(label=text, wrap=True, xalign=0, selectable=True); l.set_max_width_chars(70)
        _dialog('Something went wrong', l, [('ok', 'OK', 'danger')])
    _on_main(show)


def gtk_yesno(text: str) -> bool:
    def show():
        l = Gtk.Label(label=text, wrap=True, xalign=0); l.set_max_width_chars(70)
        return _dialog('WoW Deck', l, [('no', 'No', ''), ('yes', 'Yes', 'accent')]) == 'yes'
    return bool(_on_main(show))


def gtk_password(prompt: str) -> str | None:
    def show():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(Gtk.Label(label=prompt, wrap=True, xalign=0))
        e = Gtk.PasswordEntry(show_peek_icon=True); box.append(e)
        r = _dialog('Password needed', box, [('cancel', 'Cancel', ''), ('ok', 'Continue', 'accent')])
        return e.get_text() if r == 'ok' else None
    return _on_main(show)


def gtk_checklist(prompt: str, items: list[tuple[str, str, bool, bool]]) -> list[str] | None:
    def show():
        title, _, sub = prompt.partition('\n')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        if sub:
            box.append(Gtk.Label(label=sub, wrap=True, xalign=0))
        toggles = {}
        for id_, label, checked, req in items:
            b = Gtk.ToggleButton(label=label + ('   (required)' if req else '')); b.add_css_class('row')
            b.set_active(bool(checked or req)); b.set_sensitive(not req)
            if req: b.add_css_class('required')
            toggles[id_] = b; box.append(b)
        r = _dialog(title, box, [('cancel', 'Cancel', ''), ('ok', 'Continue', 'accent')])
        if r != 'ok':
            return None
        return [i for i, b in toggles.items() if b.get_active()]
    return _on_main(show)


def gtk_menu(prompt: str, items: list[tuple[str, str]]) -> str | None:
    def show():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        res = {}
        win_box = {}
        for id_, label in items:
            b = Gtk.Button(label=label); b.add_css_class('big')
            b.connect('clicked', lambda _b, id_=id_: (res.__setitem__('id', id_), win_box['dlg'].close()))
            box.append(b)
        # reuse _dialog machinery but capture the window to close on choice
        orig = _dialog
        return orig(prompt.split('\n')[0], box, [('cancel', 'Close', '')]) if not items else _menu_dialog(prompt, box, res, win_box)
    return _on_main(show)


def _menu_dialog(prompt, box, res, win_box):
    win = _app_ref.get('win')
    dlg = Gtk.Window(transient_for=win, modal=True, title='WoW Deck', default_width=720); dlg.add_css_class('dialog')
    win_box['dlg'] = dlg
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=18, margin_bottom=18, margin_start=22, margin_end=22)
    title, _, sub = prompt.partition('\n'); v.append(_header(title, sub)); v.append(box)
    c = Gtk.Button(label='Close'); c.add_css_class('big'); c.connect('clicked', lambda *_: dlg.close()); v.append(c)
    dlg.set_child(v); loop = GLib.MainLoop(); dlg.connect('close-request', lambda *_: (loop.quit(), False)[1]); dlg.present(); loop.run()
    return res.get('id')


def gtk_note(text: str) -> None:
    print(text, flush=True)
    log = _app_ref.get('log')
    if log:
        GLib.idle_add(log, text)


def _para(text: str, css: str = 'body') -> Gtk.Label:
    l = Gtk.Label(label=text, xalign=0, wrap=True, hexpand=True, wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=70)
    l.add_css_class(css); return l


def gtk_help(title: str, sections) -> None:
    """Help page: headings, paragraphs and term/description items as wrapping labels."""
    def show():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_end=12)
        for heading, intro, items in sections:
            box.append(_para(heading, 'h2'))
            if intro:
                box.append(_para(intro))
            for it in items:
                if isinstance(it, tuple):
                    box.append(_para(it[0], 'term')); box.append(_para(it[1]))
                else:
                    row = Gtk.Box(spacing=8); row.append(_para('•', 'body')); row.get_first_child().set_hexpand(False)
                    row.get_first_child().set_valign(Gtk.Align.START); row.append(_para(it)); box.append(row)
        _dialog(title, box, [('ok', 'Close', 'accent')])
    _on_main(show)


def gtk_textbox(title: str, text: str) -> None:
    def show():
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR); tv.get_buffer().set_text(text); tv.add_css_class('log')
        sw = Gtk.ScrolledWindow(min_content_height=380, min_content_width=680); sw.set_child(tv)
        _dialog(title, sw, [('ok', 'Close', 'accent')])
    _on_main(show)


def install_ui_layer():
    for name, fn in (('header', gtk_header), ('info', gtk_info), ('error', gtk_error), ('yesno', gtk_yesno), ('password', gtk_password),
                     ('checklist', gtk_checklist), ('menu', gtk_menu), ('note', gtk_note), ('textbox', gtk_textbox)):
        setattr(ui, name, fn)


# ------------------------------------------------------------------ main window

class Hub:
    def __init__(self, cli, open_action: str | None = None):
        self.cli = cli; self.open_action = open_action
        self.app = Gtk.Application(application_id='org.consoleport.wowdeck', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.app.connect('activate', self.on_activate)

    def on_activate(self, app):
        prov = Gtk.CssProvider(); prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = Gtk.ApplicationWindow(application=app, title='WoW Deck', default_width=1100, default_height=680)
        _app_ref['win'] = self.win; _app_ref['log'] = self.append_log
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=22, margin_bottom=22, margin_start=26, margin_end=26)
        self.status = Gtk.Label(label='', xalign=0); self.status.add_css_class('status')
        helpb = Gtk.Button(label='?'); helpb.add_css_class('iconbtn'); helpb.set_tooltip_text('What WoW Deck does')
        helpb.connect('clicked', lambda *_: self.do_help())
        outer.append(_header('WoW Deck', 'World of Warcraft on the Steam Deck, with ConsolePort.', trailing=helpb))
        outer.append(self.status)
        self.stack = Gtk.Stack(vexpand=True); outer.append(self.stack)
        # home grid
        grid = Gtk.Grid(row_spacing=14, column_spacing=14, row_homogeneous=True, column_homogeneous=True, vexpand=True)
        buttons = [('Set up / change components', 'accent', self.do_setup), ('Check status', '', self.do_status),
                   ('Open CurseForge', '', self.do_curseforge), ('Check for WoW Deck updates', '', self.do_update),
                   ('Switch to Game Mode', '', self.do_gamemode), ('Uninstall WoW Deck', 'danger', self.do_uninstall)]
        for i, (label, css, cb) in enumerate(buttons):
            b = Gtk.Button(label=label); b.add_css_class('big'); css and b.add_css_class(css)
            b.connect('clicked', lambda _b, cb=cb: cb()); grid.attach(b, i % 2, i // 2, 1, 1)
        self.stack.add_named(grid, 'home')
        # log page
        lp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.logview = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR); self.logview.add_css_class('log')
        sw = Gtk.ScrolledWindow(vexpand=True); sw.set_child(self.logview); lp.append(sw)
        self.uninstalled = False
        self.back = Gtk.Button(label='Back'); self.back.add_css_class('big')
        self.back.connect('clicked', lambda *_: self.app.quit() if self.uninstalled else self.stack.set_visible_child_name('home'))
        self.back.set_sensitive(False); lp.append(self.back)
        self.stack.add_named(lp, 'log')
        self.win.set_child(outer); self.win.present()
        self.refresh_status()
        if self.open_action:
            GLib.timeout_add(600, lambda: ({'setup': self.do_setup, 'status': self.do_status}.get(self.open_action, lambda: None)(), False)[1])

    def refresh_status(self):
        from . import selfupdate, steam
        env = steam.session_env()
        fin = subprocess.run(['systemctl', '--user', 'is-active', 'wow-deck-finish.service'], capture_output=True, env=env).returncode == 0
        txt = f'WoW Deck {selfupdate.current_version()}'
        if fin:
            txt += '   ·   finishing a setup in the background (waiting for World of Warcraft)'
        elif os.path.isfile(self.cli.FINISH_DONE):
            txt += '   ·   last background finish: ' + open(self.cli.FINISH_DONE).read().strip()
        self.status.set_text(txt)

    def append_log(self, line: str):
        buf = self.logview.get_buffer(); buf.insert(buf.get_end_iter(), line + '\n')
        self.logview.scroll_to_mark(buf.create_mark(None, buf.get_end_iter(), False), 0, False, 0, 0)
        return False

    def run_in_worker(self, fn, title):
        self.logview.get_buffer().set_text(''); self.stack.set_visible_child_name('log'); self.back.set_sensitive(False)
        self.append_log(f'== {title}')
        def work():
            out = io.StringIO()
            class Tee(io.TextIOBase):
                def write(s, t):
                    out.write(t)
                    for line in t.rstrip('\n').split('\n'):
                        if line: GLib.idle_add(self.append_log, re.sub(r'\x1b\[[0-9;]*m', '', line))
                    return len(t)
            with contextlib.redirect_stdout(Tee()):
                try:
                    fn()
                except Exception as e:
                    GLib.idle_add(self.append_log, f'FAILED: {e}')
            GLib.idle_add(self.back.set_sensitive, True); GLib.idle_add(self.refresh_status)
        threading.Thread(target=work, daemon=True).start()

    def do_setup(self):
        import argparse
        self.run_in_worker(lambda: self.cli.setup(argparse.Namespace(no_steam_edit=False)), 'Set up')

    def do_status(self):
        import argparse
        self.run_in_worker(lambda: self.cli.doctor(argparse.Namespace()), 'Status')

    def do_curseforge(self):
        from . import curseforge
        app = self.cli._find_curseforge_app()
        if app:
            curseforge.launch(app); self.status.set_text('CurseForge starting...')
        else:
            gtk_info('CurseForge is not installed yet. Tick it in "Set up".')

    def do_uninstall(self):
        import argparse
        if not gtk_yesno('Remove everything WoW Deck installed: addons, CurseForge, the paddle mapping and WoW Deck itself?\n\n'
                         'Battle.net, its Steam shortcut and World of Warcraft stay.'):
            return
        self.uninstalled = True
        self.back.set_label('Close')
        self.run_in_worker(lambda: self.cli.uninstall_all(argparse.Namespace(no_steam_edit=False)), 'Uninstall')

    def do_help(self):
        from .help import SECTIONS
        gtk_help('What WoW Deck does', SECTIONS)

    def do_update(self):
        from . import selfupdate
        self.run_in_worker(lambda: print(selfupdate.check_and_update(log=print)), 'Update')

    def do_gamemode(self):
        from . import deck
        if gtk_yesno('Switch to Game Mode now?'):
            deck.return_to_game_mode(); self.app.quit()

    def run(self) -> int:
        return self.app.run([])


def run_hub(cli, open_action: str | None = None) -> int:
    install_ui_layer()
    return Hub(cli, open_action).run()
