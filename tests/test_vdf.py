import os, zlib
from wowdeck import vdf

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')


def test_text_roundtrip_localconfig():
    src = open(os.path.join(FIX, 'localconfig.snippet.vdf'), encoding='utf-8').read()
    d = vdf.loads(src)
    assert vdf.get_path(d, 'UserLocalConfigStore', 'apps', '2731573482', 'UseSteamControllerConfig') == '0'
    assert vdf.loads(vdf.dumps(d)) == d


def test_text_compat_mapping():
    d = vdf.load(os.path.join(FIX, 'config.compat.snippet.vdf'))
    m = vdf.get_path(d, 'InstallConfigStore', 'Software', 'Valve', 'Steam', 'CompatToolMapping')
    assert m['2731573482']['name'].startswith('proton')


def test_text_escapes_and_comments():
    d = vdf.loads('"a" { "k" "v \\"q\\" \\\\ x" // comment\n "n" "1" }')
    assert d == {'a': {'k': 'v "q" \\ x', 'n': '1'}}
    assert vdf.loads(vdf.dumps(d)) == d


def test_set_path_creates_parents():
    d = {}
    vdf.set_path(d, 'UserLocalConfigStore', 'apps', '123', 'UseSteamControllerConfig', '0')
    assert d['UserLocalConfigStore']['apps']['123']['UseSteamControllerConfig'] == '0'


def test_binary_roundtrip_shortcuts():
    raw = open(os.path.join(FIX, 'shortcuts.vdf'), 'rb').read()
    d = vdf.binary_loads(raw)
    sc = d['shortcuts']
    assert len(sc) == 3
    names = {v['AppName'] for v in sc.values()}
    assert 'Battle.net.exe' in names
    assert vdf.binary_dumps(d) == raw


def test_shortcut_appids_are_shortcut_ids():
    # Steam stores an explicit appid per shortcut (high bit set, unique). It is NOT a pure
    # function of Exe+AppName in current Steam (two identical entries had different ids), so
    # wow-deck reads the stored id and only derives crc32(Exe+AppName)|0x80000000 for
    # shortcuts it creates itself.
    d = vdf.binary_load(os.path.join(FIX, 'shortcuts.vdf'))
    ids = [v['appid'] for v in d['shortcuts'].values()]
    assert all(a & 0x80000000 for a in ids)
    assert len(set(ids)) == len(ids)
