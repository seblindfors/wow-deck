"""CurseForge (Linux AppImage) setup for addon maintenance: place the AppImage, add a desktop
entry, give it a stable WoW path, and pre-register the WoW flavours in its instance registry.

Registry: ~/.config/CurseForge/agent/GameInstances/AddonGameInstance.json (JSON array).
Observed on a Deck (2026-09): retail = gameVersionTypeId 517, Classic Era = 67408; the app
fills installedAddons/cachedScans itself after a scan. It rewrites the file while running, so
seeding only happens when CurseForge is not running."""
from __future__ import annotations
import datetime, json, os, subprocess, tempfile, urllib.request, uuid, zipfile

HOME = os.path.expanduser('~')
DOWNLOAD_URL = 'https://curseforge.overwolf.com/downloads/curseforge-latest-linux.zip'
APPIMAGE = os.path.join(HOME, 'Applications', 'CurseForge.AppImage')
DESKTOP_ENTRY = os.path.join(HOME, '.local', 'share', 'applications', 'curseforge.desktop')
WOW_LINK = os.path.join(HOME, 'World of Warcraft')
CONFIG_DIR = os.path.join(HOME, '.config', 'CurseForge')
INSTANCES = os.path.join(CONFIG_DIR, 'agent', 'GameInstances', 'AddonGameInstance.json')

# WoW flavour folder -> (CurseForge gameVersionTypeId, display name). Unknown folders are skipped.
FLAVOURS = {'_retail_': (517, 'Retail'), '_classic_era_': (67408, 'Classic Era')}


def wow_install_dir(wtf_dirs: list[str]) -> str | None:
    """Common 'World of Warcraft' directory from a list of .../_flavour_/WTF paths."""
    roots = {os.path.dirname(os.path.dirname(d)) for d in wtf_dirs}
    return sorted(roots)[0] if roots else None


def ensure_wow_symlink(wow_dir: str, link: str = WOW_LINK, log=print) -> None:
    if os.path.islink(link):
        if os.path.realpath(link) == os.path.realpath(wow_dir):
            log(f'  ok      {link} -> {wow_dir}'); return
        os.remove(link)
    elif os.path.exists(link):
        log(f'  WARN    {link} exists and is not a symlink; leaving it alone'); return
    os.symlink(wow_dir, link)
    log(f'  linked  {link} -> {wow_dir}')


def curseforge_running() -> bool:
    return subprocess.run(['pgrep', '-f', 'CurseForge.*AppImage|/tmp/.mount_CurseF'], capture_output=True).returncode == 0


def install_appimage(dest: str = APPIMAGE, url: str = DOWNLOAD_URL, log=print) -> str:
    if os.path.isfile(dest):
        log(f'  ok      {dest} (already present; CurseForge self-updates)'); return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    log(f'  downloading {url}')
    with tempfile.TemporaryDirectory() as tmp:
        zpath = os.path.join(tmp, 'cf.zip')
        urllib.request.urlretrieve(url, zpath)
        with zipfile.ZipFile(zpath) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.appimage')]
            if not names:
                raise RuntimeError('no AppImage in CurseForge zip')
            with z.open(names[0]) as src, open(dest, 'wb') as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
    os.chmod(dest, 0o755)
    log(f'  wrote   {dest}')
    return dest


def write_desktop_entry(appimage: str = APPIMAGE, path: str = DESKTOP_ENTRY, log=print) -> None:
    content = ('[Desktop Entry]\nType=Application\nName=CurseForge\nComment=WoW addon manager\n'
               f'Exec="{appimage}" %U\nIcon=curseforge\nTerminal=false\nCategories=Game;Utility;\n'
               'MimeType=x-scheme-handler/curseforge;\n')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path) and open(path).read() == content:
        log(f'  ok      {path}'); return
    open(path, 'w').write(content)
    log(f'  wrote   {path}')


def _instance(flavour_dir: str, version_type: int, name: str) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    guid = str(uuid.uuid4())
    return {
        'guid': guid, 'gameTypeID': 1, 'installPath': flavour_dir.rstrip('/') + '/', 'name': name,
        'cachedScans': [], 'isValid': True, 'lastPreviousMatchUpdate': '0001-01-01T00:00:00',
        'lastRefreshAttempt': '0001-01-01T00:00:00', 'isEnabled': True, 'gameVersion': None,
        'gameVersionFlavor': None, 'gameVersionTypeId': version_type, 'preferenceAlternateFile': False,
        'preferenceAutoInstallUpdates': False, 'preferenceDeleteOrphanedDependencies': False,
        'preferenceDeleteSavedVariables': False, 'preferenceReleaseType': 1, 'preferenceModdingFolderPath': None,
        'syncProfile': {'PreferenceEnabled': False, 'PreferenceAutoSync': True, 'PreferenceAutoDelete': False,
                        'PreferenceBackupSavedVariables': False, 'GameInstanceGuid': guid, 'SyncProfileID': 0,
                        'SavedVariablesProfile': None, 'LastSyncDate': '0001-01-01T00:00:00'},
        'installDate': now, 'installedAddons': [], 'installedGamePrerequisites': [],
        'wasGameVersionTypeIdManuallyChanged': False, 'wasNameManuallyChanged': False,
    }


def seed_instances(wow_link: str, wtf_dirs: list[str], registry: str = INSTANCES, log=print) -> list[str]:
    """Add missing WoW flavours to CurseForge's instance registry. Paths go through the
    stable symlink so they match what the guide produces by hand. Returns names added."""
    existing = []
    if os.path.isfile(registry):
        try:
            existing = json.load(open(registry))
        except json.JSONDecodeError:
            log(f'  WARN    {registry} is not valid JSON; not touching it'); return []
    known = {os.path.realpath(i.get('installPath', '')).rstrip('/') for i in existing}
    added = []
    for wtf in wtf_dirs:
        flav_dir = os.path.dirname(wtf)                       # .../World of Warcraft/_retail_
        flav = os.path.basename(flav_dir)
        if flav not in FLAVOURS:
            log(f'  skip    {flav} (unknown CurseForge flavour id)'); continue
        if os.path.realpath(flav_dir).rstrip('/') in known:
            log(f'  ok      {FLAVOURS[flav][1]} already registered'); continue
        existing.append(_instance(os.path.join(wow_link, flav), *FLAVOURS[flav]))
        added.append(FLAVOURS[flav][1])
    if added:
        os.makedirs(os.path.dirname(registry), exist_ok=True)
        json.dump(existing, open(registry, 'w'), indent=2)
        log(f'  registered {", ".join(added)} in {registry}')
    return added


def launch(appimage: str = APPIMAGE) -> None:
    subprocess.Popen([appimage], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
