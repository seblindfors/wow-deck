"""Addon pre-install from a manifest. Sources: GitHub latest release zip asset, or a direct
zip URL. Zips are extracted into Interface/AddOns of every WoW flavour; installed folders are
recorded in state.json so remove() only deletes what we placed. CurseForge adopts these by
fingerprint on its next scan."""
from __future__ import annotations
import io, json, os, shutil, urllib.request, zipfile

STATE = os.path.join(os.path.expanduser('~'), '.local', 'share', 'wow-deck', 'state.json')

# id -> manifest. 'folders' is informational (what the zip contains at top level).
MANIFEST = {
    'consoleport': {'title': 'ConsolePort', 'github': 'seblindfors/ConsolePort',
                    'folders': ['ConsolePort', 'ConsolePort_Bar', 'ConsolePort_Config', 'ConsolePort_Cursor', 'ConsolePort_Keyboard', 'ConsolePort_Menu', 'ConsolePort_Rings', 'ConsolePort_Target', 'ConsolePort_World']},
    'immersion':   {'title': 'Immersion', 'github': 'seblindfors/Immersion', 'folders': ['Immersion']},
    'bugsack':     {'title': 'BugSack', 'github': 'funkydude/BugSack', 'folders': ['BugSack']},
    'buggrabber':  {'title': '!BugGrabber', 'cfwidget': 'bug-grabber', 'folders': ['!BugGrabber']},
}


def _get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'wow-deck', **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def resolve_zip_url(entry: dict) -> str:
    if 'url' in entry:
        return entry['url']
    if 'github' in entry:
        rel = json.loads(_get(f"https://api.github.com/repos/{entry['github']}/releases/latest", {'Accept': 'application/vnd.github+json'}))
        zips = [a['browser_download_url'] for a in rel.get('assets', []) if a['name'].lower().endswith('.zip')]
        if not zips:
            raise RuntimeError(f"no zip asset in latest release of {entry['github']}")
        # prefer the plain (non -classic/-bcc) build
        zips.sort(key=lambda u: any(t in u.lower() for t in ('-classic', '-bcc', '-wrath', '-cata', '-mists')))
        return zips[0]
    if 'cfwidget' in entry:
        d = json.loads(_get(f"https://api.cfwidget.com/wow/addons/{entry['cfwidget']}"))
        proj, fid = d.get('id'), (d.get('download') or {}).get('id')
        if not (proj and fid):
            raise RuntimeError(f"cfwidget has no download for {entry['cfwidget']}")
        # public redirect to the CDN zip (no API key needed)
        return f'https://www.curseforge.com/api/v1/mods/{proj}/files/{fid}/download'
    raise RuntimeError('manifest entry has no source')


def _load_state() -> dict:
    try:
        return json.load(open(STATE))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(st: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, 'w'), indent=2)


def addons_dirs(wtf_dirs: list[str]) -> list[str]:
    return [os.path.join(os.path.dirname(d), 'Interface', 'AddOns') for d in wtf_dirs]


def is_installed(addon_id: str, wtf_dirs: list[str]) -> bool:
    folders = MANIFEST[addon_id]['folders']
    return any(all(os.path.isdir(os.path.join(a, f)) for f in folders) for a in addons_dirs(wtf_dirs))


def install(addon_id: str, wtf_dirs: list[str], log=print, fetch=_get) -> list[str]:
    entry = MANIFEST[addon_id]
    url = resolve_zip_url(entry)
    log(f'  downloading {entry["title"]} from {url}')
    data = fetch(url)
    return install_zip_bytes(addon_id, data, wtf_dirs, log)


def install_zip_bytes(addon_id: str, data: bytes, wtf_dirs: list[str], log=print) -> list[str]:
    z = zipfile.ZipFile(io.BytesIO(data))
    safe = [n for n in z.namelist() if '/' in n and not n.startswith('/') and '..' not in n.split('/')]
    tops = sorted({n.split('/')[0] for n in safe})
    if not tops:
        raise RuntimeError('zip has no top-level folders')
    placed = []
    for adir in addons_dirs(wtf_dirs):
        os.makedirs(adir, exist_ok=True)
        for t in tops:
            shutil.rmtree(os.path.join(adir, t), ignore_errors=True)
        for n in safe:
            dest = os.path.normpath(os.path.join(adir, n))
            if not dest.startswith(os.path.normpath(adir) + os.sep):
                continue                                    # zip-slip guard
            if n.endswith('/'):
                os.makedirs(dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(n) as src, open(dest, 'wb') as out:
                    shutil.copyfileobj(src, out)
        placed.append(adir)
        log(f'  installed {", ".join(tops)} -> {adir}')
    st = _load_state(); st.setdefault('addons', {})[addon_id] = {'folders': tops}; _save_state(st)
    return tops


def remove(addon_id: str, wtf_dirs: list[str], log=print) -> None:
    st = _load_state()
    folders = st.get('addons', {}).get(addon_id, {}).get('folders') or MANIFEST[addon_id]['folders']
    for adir in addons_dirs(wtf_dirs):
        for f in folders:
            p = os.path.join(adir, f)
            if os.path.isdir(p):
                shutil.rmtree(p); log(f'  removed {p}')
    st.get('addons', {}).pop(addon_id, None); _save_state(st)
