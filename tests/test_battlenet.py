import os, shutil, tempfile
from wowdeck import battlenet, steam, vdf

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')


def test_shortcut_appid_is_stable_and_high_bit():
    a = battlenet.shortcut_appid()
    assert a == battlenet.shortcut_appid() and a & 0x80000000


def test_add_shortcut_roundtrip_and_compat_mapping():
    with tempfile.TemporaryDirectory() as tmp:
        ud = os.path.join(tmp, 'userdata', '1'); os.makedirs(os.path.join(ud, 'config'))
        shutil.copy(os.path.join(FIX, 'shortcuts.vdf'), os.path.join(ud, 'config', 'shortcuts.vdf'))
        os.makedirs(os.path.join(tmp, 'config')); shutil.copy(os.path.join(FIX, 'config.compat.snippet.vdf'), os.path.join(tmp, 'config', 'config.vdf'))
        shutil.copy(os.path.join(FIX, 'localconfig.snippet.vdf'), os.path.join(ud, 'config', 'localconfig.vdf'))
        appid = battlenet.shortcut_appid()
        exe = battlenet.battlenet_exe(battlenet.compatdata(tmp, appid))
        sc = steam.add_shortcut(ud, 'Battle.net', exe, os.path.dirname(exe), '/x/wrap %command%', appid=appid)
        d = vdf.binary_load(steam.shortcuts_path(ud))
        assert len(d['shortcuts']) == 4 and d['shortcuts'][sc.index]['appid'] == appid
        assert d['shortcuts'][sc.index]['Exe'] == f'"{exe}"' and d['shortcuts'][sc.index]['LaunchOptions'] == '/x/wrap %command%'
        assert vdf.binary_dumps(vdf.binary_loads(vdf.binary_dumps(d))) == vdf.binary_dumps(d)   # stable re-encode
        steam.set_compat_tool(tmp, appid, 'proton_experimental'); steam.set_steam_input(sc, '0')
        assert steam.get_compat_tool(tmp, appid) == 'proton_experimental' and steam.get_steam_input(sc) == '0'


def test_proton_env_has_required_keys():
    env = battlenet.proton_env('/steam', '/steam/steamapps/compatdata/1', '/steam/steamapps/common/Proton 10.0', 1, '/x/Battle.net-Setup.exe')
    for k in ('STEAM_COMPAT_DATA_PATH', 'STEAM_COMPAT_CLIENT_INSTALL_PATH', 'STEAM_COMPAT_TOOL_PATHS', 'WINE_SIMULATE_WRITECOPY', 'SteamAppId'):
        assert env[k]


def test_remove_shortcut_cleans_all_three_files():
    with tempfile.TemporaryDirectory() as tmp:
        ud = os.path.join(tmp, 'userdata', '1'); os.makedirs(os.path.join(ud, 'config'))
        shutil.copy(os.path.join(FIX, 'shortcuts.vdf'), os.path.join(ud, 'config', 'shortcuts.vdf'))
        os.makedirs(os.path.join(tmp, 'config')); shutil.copy(os.path.join(FIX, 'config.compat.snippet.vdf'), os.path.join(tmp, 'config', 'config.vdf'))
        shutil.copy(os.path.join(FIX, 'localconfig.snippet.vdf'), os.path.join(ud, 'config', 'localconfig.vdf'))
        appid = battlenet.shortcut_appid()
        sc = steam.add_shortcut(ud, 'Battle.net', '/x/Battle.net.exe', '/x', appid=appid)
        steam.set_compat_tool(tmp, appid, 'proton_10'); steam.set_steam_input(sc, '0')
        steam.remove_shortcut(tmp, sc)
        d = vdf.binary_load(steam.shortcuts_path(ud))
        assert len(d['shortcuts']) == 3 and list(d['shortcuts']) == ['0', '1', '2']
        assert steam.get_compat_tool(tmp, appid) is None and steam.get_steam_input(sc) is None
        assert steam.get_compat_tool(tmp, 2731573482).startswith('proton')   # others intact


def test_remove_shortcuts_in_batch_by_appid():
    with tempfile.TemporaryDirectory() as tmp:
        ud = os.path.join(tmp, 'userdata', '1'); os.makedirs(os.path.join(ud, 'config'))
        shutil.copy(os.path.join(FIX, 'shortcuts.vdf'), os.path.join(ud, 'config', 'shortcuts.vdf'))
        os.makedirs(os.path.join(tmp, 'config')); shutil.copy(os.path.join(FIX, 'config.compat.snippet.vdf'), os.path.join(tmp, 'config', 'config.vdf'))
        shutil.copy(os.path.join(FIX, 'localconfig.snippet.vdf'), os.path.join(ud, 'config', 'localconfig.vdf'))
        data = vdf.binary_load(steam.shortcuts_path(ud))
        scs = [steam.Shortcut(i, int(v['appid']), v['AppName'], v['Exe'], v['StartDir'], '', ud) for i, v in data['shortcuts'].items()]
        for sc in scs:                      # stale indices on purpose
            steam.remove_shortcut(tmp, sc)
        assert vdf.binary_load(steam.shortcuts_path(ud))['shortcuts'] == {}
