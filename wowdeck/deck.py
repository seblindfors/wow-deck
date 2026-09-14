"""SteamOS / Deck facts: OS version, session type, InputPlumber, Proton versions, WoW
prefixes. Read-only helpers plus InputPlumber target switching (unprivileged CLI)."""
from __future__ import annotations
import glob, os, re, subprocess
from . import steam

INPUTPLUMBER_MIN_STEAMOS = (3, 7)
PROTON_BAD = {'proton-10.0-1', 'proton-10.0-2'}          # PROTON_*_HIDRAW inverted; DS5 still fine but avoid
EDGE_HID_ID = '0003:0000054C:00000DF2'


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, '', f'{cmd[0]}: not found')


def os_release() -> dict:
    d = {}
    try:
        for line in open('/etc/os-release'):
            if '=' in line:
                k, v = line.rstrip('\n').split('=', 1)
                d[k] = v.strip('"')
    except OSError:
        pass
    return d


def is_steamos() -> bool:
    return os_release().get('ID') == 'steamos'


def steamos_version() -> tuple[int, ...] | None:
    v = os_release().get('VERSION_ID')
    return tuple(int(x) for x in re.findall(r'\d+', v)) if v else None


def in_gamescope() -> bool:
    return run(['pgrep', '-x', 'gamescope-wl']).returncode == 0 or os.environ.get('XDG_SESSION_DESKTOP') == 'gamescope' \
        or os.path.exists('/run/user/1000/gamescope-environment') and run(['pgrep', '-x', 'kwin_wayland']).returncode != 0


def inputplumber_version() -> str | None:
    r = run(['inputplumber', '--version'])
    return r.stdout.strip().split()[-1] if r.returncode == 0 and r.stdout.strip() else None


def unit_state(unit: str) -> tuple[str, str]:
    return run(['systemctl', 'is-active', unit]).stdout.strip(), run(['systemctl', 'is-enabled', unit]).stdout.strip()


def ip_devices() -> list[str]:
    r = run(['inputplumber', 'devices', 'list'])
    return re.findall(r'^│\s*(\d+)\s*│', r.stdout, re.M) if r.returncode == 0 else []


def ip_targets(dev: str = '0') -> list[str]:
    r = run(['inputplumber', 'device', dev, 'targets', 'list'])
    rows = re.findall(r'^│\s*([a-z0-9-]+)\s*│', r.stdout, re.M) if r.returncode == 0 else []
    return [x for x in rows if x not in ('Id',)]


def ip_set_target(target: str, dev: str = '0') -> bool:
    return run(['inputplumber', 'device', dev, 'targets', 'set', target]).returncode == 0


def edge_present() -> bool:
    for p in glob.glob('/sys/class/hidraw/hidraw*/device/uevent'):
        try:
            if f'HID_ID={EDGE_HID_ID}' in open(p).read():
                return True
        except OSError:
            pass
    return False


def proton_versions(root: str) -> dict[str, str]:
    out = {}
    for d in sorted(glob.glob(os.path.join(root, 'steamapps', 'common', 'Proton*'))):
        try:
            out[os.path.basename(d)] = open(os.path.join(d, 'version')).read().split()[-1]
        except (OSError, IndexError):
            out[os.path.basename(d)] = '?'
    return out


def compat_tool_dir(root: str, tool_name: str) -> str | None:
    """Map a CompatToolMapping name (proton_experimental, proton_10, ...) to its install dir."""
    names = {'proton_experimental': 'Proton - Experimental', 'proton_9': 'Proton 9.0 (Beta)',
             'proton_10': 'Proton 10.0', 'proton_11': 'Proton 11.0', 'proton_hotfix': 'Proton Hotfix'}
    cand = names.get(tool_name)
    if cand and os.path.isdir(os.path.join(root, 'steamapps', 'common', cand)):
        return os.path.join(root, 'steamapps', 'common', cand)
    for d in glob.glob(os.path.join(root, 'compatibilitytools.d', '*')):
        if os.path.basename(d) == tool_name:
            return d
    return None


def wow_flavour_dirs(root: str) -> list[str]:
    """WoW flavour folders that have the game executable (`_retail_`, `_classic_era_`, ...).
    Battle.net writes Wow.exe early in the install; WTF/ and Interface/AddOns/ only appear on
    the first launch, so callers create those as needed."""
    pat = os.path.join(root, 'steamapps', 'compatdata', '*', 'pfx', 'drive_c', 'Program Files (x86)',
                       'World of Warcraft', '_*_')
    out = []
    for d in sorted(glob.glob(pat)):
        if any(os.path.isfile(os.path.join(d, n)) for n in ('Wow.exe', 'WoW.exe', 'WowClassic.exe', 'WowT.exe', 'WowB.exe')):
            out.append(d)
    return out


def wow_wtf_dirs(root: str) -> list[str]:
    """`<flavour>/WTF` for every installed flavour (the folder may not exist yet)."""
    return [os.path.join(d, 'WTF') for d in wow_flavour_dirs(root)]


def find_battlenet_shortcuts(root: str) -> list[steam.Shortcut]:
    return [s for s in steam.list_shortcuts(root) if 'battle.net' in (s.name + s.exe).lower() and 'setup' not in s.exe.lower()]


def password_status() -> str | None:
    """'P' usable password, 'NP' none set, 'L' locked (from `passwd -S` for the current user)."""
    r = run(['passwd', '-S'])
    parts = r.stdout.split()
    return parts[1] if r.returncode == 0 and len(parts) > 1 else None


RETURN_TO_GAME_MODE = ("sh -c 'if [[ \"$(steamosctl get-default-login-mode)\" == desktop ]]; then steamosctl switch-to-game-mode; "
                       "else qdbus org.kde.Shutdown /Shutdown org.kde.Shutdown.logout; fi'")   # SteamOS Return.desktop


def return_to_game_mode() -> None:
    subprocess.Popen(RETURN_TO_GAME_MODE, shell=True, start_new_session=True)


MALIIT_DESKTOP = '/usr/share/applications/com.github.maliit.keyboard.desktop'


def ensure_virtual_keyboard(log=print) -> bool:
    """Configure KWin (Plasma Desktop Mode) to use the Maliit on-screen keyboard so text fields
    get a keyboard without Steam. Takes effect at the next Desktop Mode login. Returns True if
    it changed something."""
    if not os.path.isfile(MALIIT_DESKTOP):
        return False
    w = next((x for x in ('kwriteconfig6', 'kwriteconfig5') if run([x, '--help']).returncode in (0, 1)), None)
    r = next((x for x in ('kreadconfig6', 'kreadconfig5') if run([x, '--help']).returncode in (0, 1)), None)
    if not (w and r):
        return False
    cur = run([r, '--file', 'kwinrc', '--group', 'Wayland', '--key', 'InputMethod']).stdout.strip()
    if cur == MALIIT_DESKTOP:
        return False
    run([w, '--file', 'kwinrc', '--group', 'Wayland', '--key', 'InputMethod', MALIIT_DESKTOP])
    run([w, '--file', 'kwinrc', '--group', 'Wayland', '--key', 'VirtualKeyboardEnabled', 'true'])
    run(['qdbus', 'org.kde.KWin', '/KWin', 'reconfigure'])
    log('  enabled the KDE on-screen keyboard (Maliit) for Desktop Mode; active after the next login')
    return True


def set_user_password(new: str) -> bool:
    """Set a password for the current (passwordless) user by driving `passwd` through a pty.
    Works when no password is set (passwd then only asks for the new one twice)."""
    import pty, select
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp('passwd', ['passwd'])
    out = b''
    try:
        for _ in range(2):
            r, _, _ = select.select([fd], [], [], 10)
            if not r:
                break
            out += os.read(fd, 4096)
            if b'assword' in out.lower():
                os.write(fd, new.encode() + b'\n'); out = b''
        r, _, _ = select.select([fd], [], [], 10)
        if r:
            out += os.read(fd, 4096)
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    return os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
