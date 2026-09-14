"""Opt-in components of the setup. Each has detect()/install()/remove() so the checklist can
pre-tick installed items and un-tick to remove. Battle.net + WoW is required."""
from __future__ import annotations
import os, subprocess, time
from dataclasses import dataclass, field
from typing import Callable
from . import addons, battlenet, curseforge, deck, files, steam, ui


@dataclass
class Ctx:
    root: str
    wtf_dirs: list[str]
    shortcuts: list
    log: Callable = print
    steam_edit: bool = True     # allowed to close/relaunch Steam for config writes
    steam_closed_by_us: bool = False

    def ensure_steam_closed(self) -> bool:
        if not steam.steam_running():
            return True
        if not self.steam_edit or deck.in_gamescope():
            return False
        self.log('  closing Steam to edit its config...')
        self.steam_closed_by_us = steam.steam_shutdown()
        return self.steam_closed_by_us


@dataclass
class Component:
    id: str
    title: str
    required: bool = False
    default: bool = True
    detect: Callable[[Ctx], bool] = field(default=lambda ctx: False)
    install: Callable[[Ctx], None] = field(default=lambda ctx: None)     # headless-safe (finisher)
    remove: Callable[[Ctx], None] = field(default=lambda ctx: None)
    prepare: Callable[[Ctx], None] | None = None                        # needs dialogs/sudo; runs in Desktop Mode before Battle.net


# ---------------------------------------------------------------- battlenet (required)

def _bn_detect(ctx: Ctx) -> bool:
    return bool(ctx.shortcuts) and bool(ctx.wtf_dirs)


def wow_installed(ctx: Ctx) -> bool:
    return bool(deck.wow_wtf_dirs(ctx.root))


def _bn_install(ctx: Ctx) -> None:
    if ctx.shortcuts and ctx.wtf_dirs:
        return
    uds = steam.userdata_dirs(ctx.root)
    if not uds:
        raise RuntimeError('no Steam user profile found; log in to Steam once first')
    # The Deck's only on-screen keyboard in Desktop Mode is Steam's (Steam + X), and Battle.net
    # will ask for a login: make sure Steam is up before the installer starts.
    if not steam.steam_running():
        ctx.log('  starting Steam (needed for the on-screen keyboard during login)')
        steam.steam_launch()
        for _ in range(30):
            if steam.steam_running():
                break
            time.sleep(1)
    def closed_then_shortcut_written() -> bool:
        return ctx.ensure_steam_closed()
    # Only reference the launch wrapper if it is installed (the paddles component adds it later
    # and rewrites the launch options itself); a dangling wrapper path makes Steam fail silently.
    opts = files.LAUNCH_OPTIONS if os.access(files.WRAPPER, os.X_OK) else ''
    sc = battlenet.install(ctx.root, uds[0], opts, log=ctx.log, note=ui.note,
                           ensure_steam_closed=closed_then_shortcut_written, wow_timeout=0)
    # Steam was only closed to write the shortcut: bring it back before the long WoW wait.
    if ctx.steam_closed_by_us:
        steam.steam_launch(); ctx.steam_closed_by_us = False; ctx.log('  Steam relaunched')
    # refresh context so later components see the new shortcut / WoW dirs. WoW itself is
    # installed by the user inside Battle.net (Game Mode); setup() decides whether to wait,
    # hand off to the background finisher, or continue.
    ctx.shortcuts = deck.find_battlenet_shortcuts(ctx.root)
    ctx.wtf_dirs = deck.wow_wtf_dirs(ctx.root)


# ---------------------------------------------------------------- paddles

STEAM_INPUT_OFF = os.environ.get('WOW_DECK_STEAM_INPUT', '').lower() == 'off'   # legacy behaviour


def _paddles_detect(ctx: Ctx) -> bool:
    ok = os.path.isfile(files.ROOT_OVERRIDE) and os.access(files.WRAPPER, os.X_OK) and deck.unit_state('inputplumber.service')[1] == 'enabled'
    ok = ok and all(os.path.isfile(os.path.join(d, files.WOW_JSON)) for d in ctx.wtf_dirs)
    ok = ok and all(files.WRAPPER in sc.launch_options and (not STEAM_INPUT_OFF or steam.get_steam_input(sc) == '0') for sc in ctx.shortcuts)
    ok = ok and os.path.isfile(files.ENVD) and steam.manager_env_ignores_edge()
    return ok


def _ensure_steam_ignores_edge(ctx: Ctx) -> None:
    """install_user() already wrote environment.d and set the live user environment; a Steam
    that was started before that still has the old environment and must be restarted."""
    state = steam.steam_process_ignores_edge()
    if state is None or state:
        ctx.log('  ok      Steam ignores the emulated Edge (SDL ignore list in its environment)'); return
    if ctx.ensure_steam_closed():
        ctx.log('  Steam closed so it restarts with the SDL ignore list')   # caller relaunches (steam_closed_by_us)
    else:
        ctx.log('  NOTE    restart Steam (or reboot) so it ignores the emulated Edge; until then Steam sees two controllers while WoW runs')


def _root_phase(action: str) -> None:
    import sys
    me = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin', 'wow-deck')
    cmd = [sys.executable, me, '--root-phase', action]
    if subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode == 0:
        r = subprocess.run(['sudo', '-n', *cmd])
    elif sys.stdin.isatty():
        r = subprocess.run(['sudo', *cmd])
    else:
        for attempt in range(3):
            pw = ui.password('Your Steam Deck user password is needed for one system step:')
            if pw is None:
                raise RuntimeError('root step cancelled')
            r = subprocess.run(['sudo', '-S', '-p', '', *cmd], input=pw + '\n', text=True)
            if r.returncode == 0:
                break
            ui.error('That password was not accepted.')
    if r.returncode != 0:
        raise RuntimeError('root step failed or was cancelled')


def _paddles_prepare(ctx: Ctx) -> None:
    """Wrapper + InputPlumber (sudo, dialogs OK). Runs before Battle.net so the shortcut gets
    the wrapper launch options at creation."""
    files.install_user(ctx.log)
    if not os.path.isfile(files.ROOT_OVERRIDE) or deck.unit_state('inputplumber.service')[1] != 'enabled':
        _root_phase('install')
    else:
        ctx.log('  ok      InputPlumber already configured')


def _paddles_install(ctx: Ctx) -> None:
    """Headless part: WoW paddle JSON (needs WoW) and, if prepare did not run, the rest."""
    files.install_user(ctx.log)
    files.install_wow_json(ctx.wtf_dirs, ctx.log)
    if not os.path.isfile(files.ROOT_OVERRIDE):
        if subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode == 0 or __import__('sys').stdin.isatty():
            _root_phase('install')
        else:
            ctx.log('  InputPlumber step needs your password: run WoW Deck -> Set up from Desktop Mode to finish it')
    for sc in ctx.shortcuts:
        need = files.WRAPPER not in sc.launch_options or (STEAM_INPUT_OFF and steam.get_steam_input(sc) != '0')
        if not need:
            ctx.log(f'  ok      Steam shortcut "{sc.name}" already configured'); continue
        if ctx.ensure_steam_closed():
            steam.set_launch_options(sc, files.LAUNCH_OPTIONS); sc.launch_options = files.LAUNCH_OPTIONS   # keep ctx current for detect()
            if STEAM_INPUT_OFF:
                steam.set_steam_input(sc, '0')
            ctx.log(f'  configured Steam shortcut "{sc.name}" (launch options' + (', Steam Input off)' if STEAM_INPUT_OFF else '; Steam Input left enabled)'))
        else:
            ctx.log(f'  MANUAL  "{sc.name}": launch options -> {files.LAUNCH_OPTIONS}' + ('; Controller -> Disable Steam Input' if STEAM_INPUT_OFF else ''))
    _ensure_steam_ignores_edge(ctx)


def _paddles_remove(ctx: Ctx) -> None:
    files.remove_user(ctx.log)
    files.remove_wow_json(ctx.wtf_dirs, ctx.log)
    for sc in ctx.shortcuts:
        if files.WRAPPER in sc.launch_options and ctx.ensure_steam_closed():
            steam.set_launch_options(sc, sc.launch_options.replace(files.WRAPPER + ' ', '').strip())
            ctx.log(f'  removed wrapper from "{sc.name}" launch options')
    _root_phase('uninstall')


# ---------------------------------------------------------------- curseforge

def _cf_detect(ctx: Ctx) -> bool:
    has_app = os.path.isfile(curseforge.APPIMAGE) or any(f.lower().startswith('curseforge') and f.lower().endswith('.appimage')
                                                          for d in (os.path.expanduser('~/Desktop'), os.path.expanduser('~/Applications')) if os.path.isdir(d) for f in os.listdir(d))
    return has_app and os.path.isfile(curseforge.INSTANCES)


def _cf_install(ctx: Ctx) -> None:
    wow = curseforge.wow_install_dir(ctx.wtf_dirs)
    if not os.path.isfile(curseforge.APPIMAGE) and not _cf_detect(ctx):
        curseforge.install_appimage(log=ctx.log)
    if os.path.isfile(curseforge.APPIMAGE):
        curseforge.write_desktop_entry(log=ctx.log)
    curseforge.ensure_wow_symlink(wow, log=ctx.log)
    if curseforge.curseforge_running():
        ctx.log('  CurseForge is running: game registry not edited (quit it and re-run, or add the game in the app)')
    else:
        curseforge.seed_instances(curseforge.WOW_LINK, ctx.wtf_dirs, log=ctx.log)


def _cf_remove(ctx: Ctx) -> None:
    for p in (curseforge.APPIMAGE, curseforge.DESKTOP_ENTRY):
        if os.path.exists(p):
            os.remove(p); ctx.log(f'  removed {p}')
    ctx.log('  kept    CurseForge config and the World of Warcraft symlink')


# ---------------------------------------------------------------- addons

def _addon_component(cid: str, title: str, ids: list[str], default=True) -> Component:
    return Component(cid, title, False, default,
                     detect=lambda ctx: all(addons.is_installed(i, ctx.wtf_dirs) for i in ids),
                     install=lambda ctx: [addons.install(i, ctx.wtf_dirs, ctx.log) for i in ids if not addons.is_installed(i, ctx.wtf_dirs)],
                     remove=lambda ctx: [addons.remove(i, ctx.wtf_dirs, ctx.log) for i in ids])


COMPONENTS: list[Component] = [
    Component('battlenet', 'Install and set up Battle.net + World of Warcraft', required=True, detect=_bn_detect, install=_bn_install),
    Component('paddles', 'Install gamepad mapping with native paddle support', detect=_paddles_detect, install=_paddles_install, remove=_paddles_remove, prepare=_paddles_prepare),
    _addon_component('consoleport', 'Install ConsolePort', ['consoleport']),
    _addon_component('bugs', 'Install BugGrabber + BugSack', ['buggrabber', 'bugsack']),
    Component('curseforge', 'Install CurseForge for addon maintenance', detect=_cf_detect, install=_cf_install, remove=_cf_remove),
]


def make_ctx(log=print, steam_edit=True) -> Ctx | None:
    root = steam.steam_root()
    if not root:
        return None
    return Ctx(root, deck.wow_wtf_dirs(root), deck.find_battlenet_shortcuts(root), log, steam_edit)
