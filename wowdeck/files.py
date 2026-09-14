"""Payload placement. User-level writes run as the deck user; root-level writes run via
`sudo wow-deck --root-phase <action>` (see cli.root_phase)."""
from __future__ import annotations
import json, os, shutil, stat, subprocess, sys

SHARE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'share')
HOME = os.path.expanduser('~')
USER_BIN = os.path.join(HOME, '.local', 'bin')
USER_DATA = os.path.join(HOME, '.local', 'share', 'wow-deck')
WRAPPER = os.path.join(USER_BIN, 'wow-deck-launch.sh')
ENV_CONF = os.path.join(USER_DATA, 'env.conf')
LAUNCH_OPTIONS = f'{WRAPPER} %command%'
ENVD = os.path.join(HOME, '.config', 'environment.d', '50-wow-deck.conf')
ENVD_CONTENT = ('# wow-deck: keep Steam itself from opening the emulated DualSense Edge that InputPlumber\n'
                '# presents while World of Warcraft runs (Steam would treat it as a second controller and\n'
                '# double every Steam-side input). Steam-launched games get their own list from Steam and\n'
                '# the wow-deck launch wrapper lets the Edge through for WoW.\n'
                'SDL_GAMECONTROLLER_IGNORE_DEVICES=0x054c/0x0df2\n')

ROOT_OVERRIDE = '/etc/inputplumber/devices.d/50-steam_deck.yaml'
ROOT_KEEPLIST = '/etc/atomic-update.conf.d/wow-deck.conf'
ROOT_FILES = {ROOT_OVERRIDE: '50-steam_deck.yaml', ROOT_KEEPLIST: 'wow-deck.conf'}
WOW_JSON = 'GamePadConfig_SteamDeck.json'


def _payload(name: str) -> str:
    return open(os.path.join(SHARE, name), encoding='utf-8').read()


def _write(path: str, content: str, mode: int = 0o644, log=print) -> bool:
    old = open(path, encoding='utf-8').read() if os.path.isfile(path) else None
    if old == content:
        log(f'  ok      {path}')
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    os.chmod(path, mode)
    log(f'  {"updated" if old is not None else "wrote  "} {path}')
    return True


PROFILE = os.path.join(USER_DATA, 'wow-deck-edge.yaml')


def _user_systemctl(*args) -> bool:
    return subprocess.run(['systemctl', '--user', *args], capture_output=True).returncode == 0


def install_steam_env(log=print) -> None:
    """environment.d for persistence (read at login / daemon-reload) plus a live set-environment
    so a Steam started from now on ignores the Edge. A running Steam needs a restart."""
    _write(ENVD, ENVD_CONTENT, 0o644, log)
    ok = _user_systemctl('daemon-reload') and _user_systemctl('set-environment', 'SDL_GAMECONTROLLER_IGNORE_DEVICES=0x054c/0x0df2')
    log('  set     SDL_GAMECONTROLLER_IGNORE_DEVICES in the systemd user environment' if ok else '  WARN    could not set the systemd user environment (systemctl --user)')


def remove_steam_env(log=print) -> None:
    if os.path.exists(ENVD):
        os.remove(ENVD); log(f'  removed {ENVD}')
    _user_systemctl('daemon-reload'); _user_systemctl('unset-environment', 'SDL_GAMECONTROLLER_IGNORE_DEVICES')


def install_user(log=print) -> None:
    _write(WRAPPER, _payload('wow-deck-launch.sh'), 0o755, log)
    _write(PROFILE, _payload('wow-deck-edge.yaml'), 0o644, log)
    install_steam_env(log)
    if not os.path.isfile(ENV_CONF):
        _write(ENV_CONF, '# KEY="VALUE" overrides sourced by wow-deck-launch.sh (quote values).\n', 0o644, log)
    else:
        log(f'  kept    {ENV_CONF}')


def install_wow_json(wtf_dirs: list[str], log=print) -> None:
    for d in wtf_dirs:
        _write(os.path.join(d, WOW_JSON), _payload(WOW_JSON), 0o644, log)


def remove_user(log=print) -> None:
    for p in (WRAPPER, PROFILE):
        if os.path.exists(p):
            os.remove(p); log(f'  removed {p}')
    remove_steam_env(log)
    log(f'  kept    {USER_DATA} (logs/config; delete manually if unwanted)')


def remove_wow_json(wtf_dirs: list[str], log=print) -> None:
    for d in wtf_dirs:
        p = os.path.join(d, WOW_JSON)
        if os.path.exists(p):
            os.remove(p); log(f'  removed {p}')


# ---------------------------------------------------------------- root phase (runs as root)

def root_install(log=print) -> None:
    for path, name in ROOT_FILES.items():
        _write(path, _payload(name), 0o644, log)
    r = subprocess.run(['systemctl', 'enable', 'inputplumber.service'], capture_output=True, text=True)
    log('  enabled inputplumber.service' if r.returncode == 0 else f'  FAILED enable inputplumber: {r.stderr.strip()}')
    # (Re)start only if no Proton game is running: a hot restart re-plugs the controller.
    if subprocess.run(['pgrep', '-x', 'wineserver'], capture_output=True).returncode != 0:
        r = subprocess.run(['systemctl', 'restart', 'inputplumber.service'], capture_output=True, text=True)
        log('  restarted inputplumber.service' if r.returncode == 0 else f'  FAILED restart: {r.stderr.strip()}')
    else:
        log('  a Wine/Proton game is running: InputPlumber not restarted (takes effect at next boot)')


def root_uninstall(log=print) -> None:
    for path in ROOT_FILES:
        if os.path.exists(path):
            os.remove(path); log(f'  removed {path}')
    subprocess.run(['systemctl', 'disable', 'inputplumber.service'], capture_output=True)
    log('  disabled inputplumber.service (stock SteamOS state)')
    if subprocess.run(['pgrep', '-x', 'wineserver'], capture_output=True).returncode != 0:
        subprocess.run(['systemctl', 'restart', 'inputplumber.service'], capture_output=True)
        log('  restarted inputplumber.service with stock config (Deck no longer managed)')
