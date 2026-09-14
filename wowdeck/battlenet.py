"""Battle.net installation under Steam's Proton, the way Steam itself launches a non-Steam
game: SteamLinuxRuntime_sniper entry point -> proton waitforexitandrun -> exe, with the
STEAM_COMPAT_* environment. The user still logs in and installs WoW inside Battle.net."""
from __future__ import annotations
import os, subprocess, threading, time, urllib.request, zlib
from . import deck, steam

INSTALLER_URL = 'https://www.battle.net/download/getInstallerForGame?os=win&gameProgram=BATTLENET_APP&version=Live'
APPNAME = 'Battle.net'
SLR = 'SteamLinuxRuntime_sniper'
# Proton 10 first: on 2026-09-14 the Battle.net installer failed its version download
# (BLZBNTBTS00000028) under Experimental 11 but installed fine under 10.0-4b.
PREFERRED_TOOLS = ('proton_10', 'proton_experimental', 'proton_11')   # first that exists wins


def shortcut_appid() -> int:
    """Stable id for our Battle.net shortcut/prefix (Steam accepts any id with the high bit set).
    Not derived from the exe path because that path contains the id itself."""
    return (zlib.crc32(b'wow-deck:Battle.net') | 0x80000000) & 0xFFFFFFFF


def compatdata(root: str, appid: int) -> str:
    return os.path.join(root, 'steamapps', 'compatdata', str(appid))


def battlenet_exe(compat: str) -> str:
    return os.path.join(compat, 'pfx', 'drive_c', 'Program Files (x86)', 'Battle.net', 'Battle.net.exe')


def wow_exe(compat: str) -> str:
    return os.path.join(compat, 'pfx', 'drive_c', 'Program Files (x86)', 'World of Warcraft', '_retail_', 'Wow.exe')


def pick_proton(root: str) -> tuple[str, str] | None:
    """(CompatToolMapping name, install dir) for the best available Proton. WOW_DECK_PROTON
    (e.g. proton_10) forces a specific tool."""
    forced = os.environ.get('WOW_DECK_PROTON')
    for name in ([forced] if forced else []) + list(PREFERRED_TOOLS):
        d = deck.compat_tool_dir(root, name)
        if d and os.path.isfile(os.path.join(d, 'proton')):
            ver = deck.proton_versions(root).get(os.path.basename(d), '')
            if ver in deck.PROTON_BAD:
                continue
            return name, d
    return None


def download_installer(dest_dir: str, log=print) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, 'Battle.net-Setup.exe')
    if os.path.isfile(dest) and os.path.getsize(dest) > 1_000_000:
        log(f'  ok      {dest}'); return dest
    log(f'  downloading Battle.net installer')
    req = urllib.request.Request(INSTALLER_URL, headers={'User-Agent': 'wow-deck'})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    log(f'  wrote   {dest} ({os.path.getsize(dest) // 1024} KB)')
    return dest


def proton_env(root: str, compat: str, proton_dir: str, appid: int, exe: str) -> dict:
    env = dict(os.environ)
    slr = os.path.join(root, 'steamapps', 'common', SLR)
    env.update({
        'STEAM_COMPAT_DATA_PATH': compat,
        'STEAM_COMPAT_CLIENT_INSTALL_PATH': root,
        'STEAM_COMPAT_APP_ID': str(appid), 'SteamAppId': str(appid), 'SteamGameId': str(appid),
        'STEAM_COMPAT_TOOL_PATHS': f'{proton_dir}:{slr}',
        'STEAM_COMPAT_LIBRARY_PATHS': root,
        'STEAM_COMPAT_INSTALL_PATH': os.path.dirname(exe),
        'STEAM_COMPAT_MOUNTS': os.path.dirname(exe),
        'WINE_SIMULATE_WRITECOPY': '1',           # Battle.net renders blank without it (community guide)
    })
    return env


def run_under_proton(root: str, compat: str, proton_dir: str, appid: int, exe: str, wait: bool = True, log=print) -> subprocess.Popen:
    slr_entry = os.path.join(root, 'steamapps', 'common', SLR, '_v2-entry-point')
    proton = os.path.join(proton_dir, 'proton')
    os.makedirs(compat, exist_ok=True)
    if os.path.isfile(slr_entry):
        cmd = [slr_entry, '--verb=waitforexitandrun', '--', proton, 'waitforexitandrun', exe]
    else:
        log('  WARN    SteamLinuxRuntime_sniper not found; running Proton without the container')
        cmd = [proton, 'waitforexitandrun', exe]
    log(f'  running under {os.path.basename(proton_dir)}: {os.path.basename(exe)}')
    p = subprocess.Popen(cmd, env=proton_env(root, compat, proton_dir, appid, exe), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait:
        p.wait()
    return p


def wait_for(path: str, timeout: float, poll: float = 5.0, log=print, note=None) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.isfile(path):
            return True
        time.sleep(poll)
        if note and int(time.time() - t0) % 60 < poll:
            note(f'  waiting for {os.path.basename(path)}...')
    return os.path.isfile(path)


def install(root: str, userdata: str, launch_options: str, log=print, note=print,
            ensure_steam_closed=lambda: True, wow_timeout: float = 0) -> steam.Shortcut | None:
    """Full flow: pick Proton, download installer, run it in a fresh prefix, wait for
    Battle.net.exe, create the Steam shortcut (Steam closed), then optionally wait for WoW."""
    tool = pick_proton(root)
    if not tool:
        raise RuntimeError('no usable Proton found (install Proton Experimental or 10.0 from Steam first)')
    tool_name, proton_dir = tool
    appid = shortcut_appid()
    compat = compatdata(root, appid)
    bnet = battlenet_exe(compat)
    if not os.path.isfile(bnet):
        setup_exe = download_installer(os.path.join(os.path.expanduser('~'), '.local', 'share', 'wow-deck'), log)
        note('Battle.net installer starting. Accept the defaults and log in when asked.')
        run_under_proton(root, compat, proton_dir, appid, setup_exe, wait=False, log=log)
        if not wait_for(bnet, timeout=1800, log=log, note=note):
            raise RuntimeError('Battle.net did not finish installing (Battle.net.exe not found after 30 min)')
        log(f'  ok      Battle.net installed in {compat}')
    else:
        log(f'  ok      Battle.net already installed in {compat}')
    existing = [s for s in steam.list_shortcuts(root) if s.appid == appid]
    if existing:
        sc = existing[0]; log(f'  ok      Steam shortcut "{sc.name}" exists')
    else:
        if not ensure_steam_closed():
            raise RuntimeError('Steam must be closed to add the shortcut; close Steam and re-run')
        sc = steam.add_shortcut(userdata, APPNAME, bnet, os.path.dirname(bnet), launch_options, appid=appid,
                                icon=steam.shortcut_icon_path())
        steam.set_compat_tool(root, appid, tool_name)
        steam.set_shortcut_art(userdata, appid, log)
        # Steam Input stays at its default here: Steam's on-screen keyboard only types into
        # Steam-launched apps with Steam Input active, and the user has to log in next. The
        # paddles component decides about Steam Input for play.
        log(f'  created Steam shortcut "{APPNAME}" ({appid}) on {tool_name}')
    if wow_timeout and not os.path.isfile(wow_exe(compat)):
        note('Now install World of Warcraft inside Battle.net. Waiting for it to finish...')
        if wait_for(wow_exe(compat), timeout=wow_timeout, poll=15, log=log, note=note):
            log('  ok      World of Warcraft installed')
        else:
            log('  WoW not installed yet; run the setup again after Battle.net finishes downloading it')
    return sc


def battlenet_running() -> bool:
    # Wine's Battle.net main process is not reliably found by comm name; match the command
    # line (C:\\...\\Battle.net.exe) or its Agent, either means the app is up.
    return (subprocess.run(['pgrep', '-f', r'Battle\.net\.exe'], capture_output=True).returncode == 0
            or subprocess.run(['pgrep', '-x', 'Agent.exe'], capture_output=True).returncode == 0)


def launch_battlenet(root: str, log=print) -> bool:
    """Start Battle.net in our prefix (detached) so the user can log in / install WoW."""
    tool = pick_proton(root)
    if not tool:
        return False
    appid = shortcut_appid(); compat = compatdata(root, appid); exe = battlenet_exe(compat)
    if not os.path.isfile(exe):
        return False
    run_under_proton(root, compat, tool[1], appid, exe, wait=False, log=log)
    return True


def wait_for_wow(root: str, ask_continue, log=print, note=print, chunk: float = 600) -> bool:
    """Wait for Wow.exe in chunks; between chunks ask the user whether to keep waiting.
    Relaunches Battle.net if it is not running. Returns True when WoW is present."""
    compat = compatdata(root, shortcut_appid()); target = wow_exe(compat)
    from . import steam as _steam
    with KeyboardRaiser(_steam.session_env()):
        while not os.path.isfile(target):
            if not battlenet_running():
                log('  Battle.net is not running; starting it so you can log in and install WoW')
                launch_battlenet(root, log)
            note('Log in to Battle.net and install World of Warcraft. The on-screen keyboard appears when you tap a field.')
            if wait_for(target, timeout=chunk, poll=10, log=log):
                break
            if not ask_continue():
                return False
    return os.path.isfile(target)


class KeyboardRaiser:
    """While running, raise KDE's on-screen keyboard whenever a Battle.net window has focus.
    KWin hides the keyboard on focus changes to windows without text-input support (all
    Wine windows), so raising it *after* focus lands there is the only thing that works.
    Desktop Mode only; harmless no-op elsewhere."""

    def __init__(self, env: dict | None = None):
        self.env = env or dict(os.environ)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _q(self, *a) -> str:
        return subprocess.run(['qdbus', 'org.kde.KWin', '/VirtualKeyboard', *a], capture_output=True, text=True, env=self.env).stdout.strip()

    def _run(self):
        while not self._stop.is_set():
            try:
                w = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True, text=True, env=self.env).stdout.strip()
                name = subprocess.run(['xdotool', 'getwindowname', w], capture_output=True, text=True, env=self.env).stdout if w else ''
                if 'battle.net' in name.lower() and self._q('org.kde.kwin.VirtualKeyboard.visible') != 'true':
                    self._q('org.kde.kwin.VirtualKeyboard.forceActivate')
            except Exception:
                pass
            self._stop.wait(0.7)

    def __enter__(self):
        if subprocess.run(['pgrep', '-x', 'kwin_wayland'], capture_output=True).returncode == 0:
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t.is_alive():
            self._t.join(timeout=2)
        if self._q('org.kde.kwin.VirtualKeyboard.visible') == 'true':
            self._q('org.kde.kwin.VirtualKeyboard.forceActivate')


def battlenet_config(compat: str) -> str:
    return os.path.join(compat, 'pfx', 'drive_c', 'users', 'steamuser', 'AppData', 'Roaming', 'Battle.net', 'Battle.net.config')


def logged_in(compat: str) -> bool:
    """True once Battle.net has stored a saved account (written after the first login)."""
    try:
        import json
        cfg = json.load(open(battlenet_config(compat), encoding='utf-8'))
        return bool(cfg.get('Client', {}).get('SavedAccountNames'))
    except Exception:
        return False


def launch_via_steam(appid: int, env: dict | None = None) -> bool:
    """Ask the running Steam client to launch a shortcut (works as the normal launch path in
    Game Mode; from Desktop Mode it has been unreliable). Returns True if the command ran."""
    r = subprocess.run(['steam', f'steam://rungameid/{appid}'], capture_output=True, env=env or dict(os.environ))
    return r.returncode == 0
