"""Steam client files on the Deck: locate roots, read/write shortcuts, per-app Steam Input
flag, compat tool mapping. Writes require Steam to be closed (callers enforce)."""
from __future__ import annotations
import os, glob, subprocess, time, zlib
from dataclasses import dataclass
from . import vdf

HOME = os.path.expanduser('~')


def steam_root() -> str | None:
    for p in (f'{HOME}/.steam/root', f'{HOME}/.local/share/Steam', f'{HOME}/.steam/steam'):
        if os.path.isdir(os.path.join(p, 'steamapps')):
            return os.path.realpath(p)
    return None


def userdata_dirs(root: str) -> list[str]:
    return [d for d in sorted(glob.glob(os.path.join(root, 'userdata', '*'))) if os.path.basename(d) != '0'
            and os.path.isdir(os.path.join(d, 'config'))]


@dataclass
class Shortcut:
    index: str
    appid: int
    name: str
    exe: str
    startdir: str
    launch_options: str
    userdata: str

    @property
    def compatdata(self) -> str:
        return os.path.join(steam_root() or '', 'steamapps', 'compatdata', str(self.appid))


def shortcuts_path(userdata: str) -> str:
    return os.path.join(userdata, 'config', 'shortcuts.vdf')


def list_shortcuts(root: str) -> list[Shortcut]:
    out = []
    for ud in userdata_dirs(root):
        p = shortcuts_path(ud)
        if not os.path.isfile(p):
            continue
        data = vdf.binary_load(p)
        for idx, sc in data.get('shortcuts', {}).items():
            out.append(Shortcut(idx, int(sc.get('appid', 0)), sc.get('AppName', ''), sc.get('Exe', ''),
                                sc.get('StartDir', ''), sc.get('LaunchOptions', ''), ud))
    return out


def derive_shortcut_appid(exe: str, name: str) -> int:
    """What third-party tools use when creating a shortcut. Steam accepts it as-is."""
    return (zlib.crc32((exe + name).encode('utf-8')) | 0x80000000) & 0xFFFFFFFF


def set_launch_options(sc: Shortcut, options: str) -> None:
    p = shortcuts_path(sc.userdata)
    data = vdf.binary_load(p)
    data['shortcuts'][sc.index]['LaunchOptions'] = options
    vdf.binary_dump(data, p)


# per-app Steam Input: 0 = disabled, 1 = default, 2 = forced on
def localconfig_path(userdata: str) -> str:
    return os.path.join(userdata, 'config', 'localconfig.vdf')


def get_steam_input(sc: Shortcut) -> str | None:
    d = vdf.load(localconfig_path(sc.userdata))
    return vdf.get_path(d, 'UserLocalConfigStore', 'apps', str(sc.appid), 'UseSteamControllerConfig')


def set_steam_input(sc: Shortcut, value: str) -> None:
    p = localconfig_path(sc.userdata)
    d = vdf.load(p)
    vdf.set_path(d, 'UserLocalConfigStore', 'apps', str(sc.appid), 'UseSteamControllerConfig', value)
    vdf.dump(d, p)


def config_vdf_path(root: str) -> str:
    return os.path.join(root, 'config', 'config.vdf')


def get_compat_tool(root: str, appid: int) -> str | None:
    d = vdf.load(config_vdf_path(root))
    return vdf.get_path(d, 'InstallConfigStore', 'Software', 'Valve', 'Steam', 'CompatToolMapping', str(appid), 'name')


# Steam must not open the emulated DualSense Edge itself (it would show up as a second
# controller next to the Deck and double every Steam-side input). Steam's config.vdf knobs
# (controller_blacklist, SteamController_PSSupport) do not stop Steam's own UI from opening
# it; the SDL ignore list in Steam's *own* environment does. files.install_user() puts it in
# ~/.config/environment.d (systemd user manager -> steam-launcher.service and the Game Mode
# session) and sets it live; Steam picks it up at its next start.
EDGE_VIDPID = '0x054c/0x0df2'
IGNORE_VAR = 'SDL_GAMECONTROLLER_IGNORE_DEVICES'


def steam_pids() -> list[int]:
    r = subprocess.run(['pgrep', '-x', 'steam'], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split()]


def steam_process_ignores_edge() -> bool | None:
    """True/False for the running Steam client; None when Steam is not running."""
    pids = steam_pids()
    if not pids:
        return None
    for pid in pids:
        try:
            env = open(f'/proc/{pid}/environ', 'rb').read().split(b'\0')
        except OSError:
            continue
        for kv in env:
            if kv.startswith(IGNORE_VAR.encode() + b'='):
                return EDGE_VIDPID.encode() in kv.lower()
    return False


def manager_env_ignores_edge() -> bool:
    r = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith(IGNORE_VAR + '='):
            return EDGE_VIDPID in line.lower()
    return False


def set_compat_tool(root: str, appid: int, name: str) -> None:
    p = config_vdf_path(root)
    d = vdf.load(p)
    vdf.set_path(d, 'InstallConfigStore', 'Software', 'Valve', 'Steam', 'CompatToolMapping', str(appid),
                 {'name': name, 'config': '', 'priority': '250'})
    vdf.dump(d, p)


def steam_running() -> bool:
    return subprocess.run(['pgrep', '-x', 'steam'], capture_output=True).returncode == 0


def steam_shutdown(timeout: float = 60) -> bool:
    if not steam_running():
        return True
    subprocess.run(['steam', '-shutdown'], capture_output=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not steam_running():
            return True
        time.sleep(1)
    return False


def session_env() -> dict:
    """Environment for launching desktop apps even when we run from SSH: reuse the running
    desktop session's display/bus variables if ours are missing."""
    env = dict(os.environ)
    if env.get('DISPLAY') and env.get('DBUS_SESSION_BUS_ADDRESS'):
        return env
    uid = os.getuid()
    env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{uid}')
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{uid}/bus')
    env.setdefault('WAYLAND_DISPLAY', 'wayland-0')
    try:
        for line in subprocess.run(['pgrep', '-a', 'Xwayland'], capture_output=True, text=True).stdout.splitlines():
            parts = line.split()
            if ':' in ' '.join(parts):
                for i, tok in enumerate(parts):
                    if tok.startswith(':') and tok[1:].isdigit():
                        env.setdefault('DISPLAY', tok)
                    if tok == '-auth' and i + 1 < len(parts):
                        env.setdefault('XAUTHORITY', parts[i + 1])
                break
    except OSError:
        pass
    env.setdefault('DISPLAY', ':0')
    return env


def steam_launch() -> None:
    """Start Steam detached from our own process tree. On SteamOS, logind kills every process
    of a session when it ends (e.g. an SSH session), so prefer a transient unit in the user's
    systemd manager; fall back to a plain detached Popen."""
    env = session_env()
    setenv = [f'--setenv={k}={env[k]}' for k in ('DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR') if env.get(k)]
    r = subprocess.run(['systemd-run', '--user', '--collect', '--unit=wow-deck-steam', *setenv, 'steam'],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        subprocess.run(['systemctl', '--user', 'reset-failed', 'wow-deck-steam.service'], capture_output=True, env=env)
        r = subprocess.run(['systemd-run', '--user', '--collect', '--unit=wow-deck-steam', *setenv, 'steam'],
                           capture_output=True, text=True, env=env)
    if r.returncode != 0:
        subprocess.Popen(['steam'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env)


def add_shortcut(userdata: str, appname: str, exe: str, startdir: str, launch_options: str = '',
                 appid: int | None = None, icon: str = '', tags: list[str] | None = None) -> Shortcut:
    """Create a non-Steam shortcut in shortcuts.vdf (Steam must be closed). Exe/StartDir are
    stored quoted, as Steam does. Returns the new Shortcut."""
    p = shortcuts_path(userdata)
    data = vdf.binary_load(p) if os.path.isfile(p) else {'shortcuts': {}}
    scs = data.setdefault('shortcuts', {})
    qexe, qdir = f'"{exe}"', f'"{startdir}"'
    appid = appid or derive_shortcut_appid(qexe, appname)
    idx = str(max([int(k) for k in scs] + [-1]) + 1)
    scs[idx] = {
        'appid': appid, 'AppName': appname, 'Exe': qexe, 'StartDir': qdir, 'icon': icon, 'ShortcutPath': '',
        'LaunchOptions': launch_options, 'IsHidden': 0, 'AllowDesktopConfig': 1, 'AllowOverlay': 1, 'OpenVR': 0,
        'Devkit': 0, 'DevkitGameID': '', 'DevkitOverrideAppID': 0, 'LastPlayTime': 0, 'FlatpakAppID': '',
        'tags': {str(i): t for i, t in enumerate(tags or [])},
    }
    vdf.binary_dump(data, p)
    return Shortcut(idx, appid, appname, qexe, qdir, launch_options, userdata)


def remove_shortcut(root: str, sc: Shortcut) -> None:
    """Delete a shortcut and its per-app settings (compat tool, Steam Input). Steam closed."""
    p = shortcuts_path(sc.userdata)
    data = vdf.binary_load(p)
    # match by appid, not by index: indices shift after every removal
    keep = [v for v in data['shortcuts'].values() if int(v.get('appid', -1)) != sc.appid]
    data['shortcuts'] = {str(i): v for i, v in enumerate(keep)}   # Steam keys are 0..n-1
    vdf.binary_dump(data, p)
    cfg = config_vdf_path(root); d = vdf.load(cfg)
    m = vdf.get_path(d, 'InstallConfigStore', 'Software', 'Valve', 'Steam', 'CompatToolMapping')
    if isinstance(m, dict) and m.pop(str(sc.appid), None) is not None:
        vdf.dump(d, cfg)
    lc = localconfig_path(sc.userdata); d = vdf.load(lc)
    apps = vdf.get_path(d, 'UserLocalConfigStore', 'apps')
    if isinstance(apps, dict) and apps.pop(str(sc.appid), None) is not None:
        vdf.dump(d, lc)


ART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'share', 'art')


def shortcut_icon_path() -> str:
    """Stable path for the shortcut icon (Steam stores the path in shortcuts.vdf)."""
    return os.path.join(ART_DIR, 'icon.png')


def set_shortcut_icon(sc: Shortcut) -> None:
    """Set the shortcut's icon field (Steam closed). Grid art does not cover the list icon."""
    p = shortcuts_path(sc.userdata)
    data = vdf.binary_load(p)
    for v in data['shortcuts'].values():
        if int(v.get('appid', -1)) == sc.appid:
            v['icon'] = shortcut_icon_path()
    vdf.binary_dump(data, p)


def set_shortcut_art(userdata: str, appid: int, log=print) -> None:
    """Install grid artwork for a shortcut: Steam reads userdata/<id>/config/grid/<appid>[p|_hero|_icon].*"""
    grid = os.path.join(userdata, 'config', 'grid')
    os.makedirs(grid, exist_ok=True)
    import shutil
    for src, dest in (('landscape.jpg', f'{appid}.jpg'), ('portrait.jpg', f'{appid}p.jpg'),
                      ('hero.jpg', f'{appid}_hero.jpg'), ('icon.png', f'{appid}_icon.png')):
        sp = os.path.join(ART_DIR, src)
        if os.path.isfile(sp):
            # remove other extensions of the same slot so Steam does not pick a stale one
            base = dest.rsplit('.', 1)[0]
            for ext in ('png', 'jpg', 'jpeg'):
                p = os.path.join(grid, f'{base}.{ext}')
                if os.path.exists(p) and p != os.path.join(grid, dest):
                    os.remove(p)
            shutil.copyfile(sp, os.path.join(grid, dest))
    log(f'  artwork installed for shortcut {appid}')
