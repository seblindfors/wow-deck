import os, shutil, tempfile
from wowdeck import steam, vdf

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')


def _fake_userdata(tmp):
    ud = os.path.join(tmp, 'userdata', '123')
    os.makedirs(os.path.join(ud, 'config'))
    shutil.copy(os.path.join(FIX, 'shortcuts.vdf'), os.path.join(ud, 'config', 'shortcuts.vdf'))
    shutil.copy(os.path.join(FIX, 'localconfig.snippet.vdf'), os.path.join(ud, 'config', 'localconfig.vdf'))
    return ud


def test_list_and_edit_shortcuts():
    with tempfile.TemporaryDirectory() as tmp:
        ud = _fake_userdata(tmp)
        os.makedirs(os.path.join(tmp, 'steamapps'))
        data = vdf.binary_load(steam.shortcuts_path(ud))
        scs = [steam.Shortcut(i, int(v['appid']), v['AppName'], v['Exe'], v['StartDir'], v.get('LaunchOptions', ''), ud)
               for i, v in data['shortcuts'].items()]
        bn = [s for s in scs if s.name == 'Battle.net.exe'][0]
        assert bn.appid == 2731573482
        steam.set_launch_options(bn, '/x/wow-deck-launch.sh %command%')
        again = vdf.binary_load(steam.shortcuts_path(ud))['shortcuts'][bn.index]
        assert again['LaunchOptions'] == '/x/wow-deck-launch.sh %command%'
        # other fields untouched, still parseable, still 3 shortcuts
        assert len(vdf.binary_load(steam.shortcuts_path(ud))['shortcuts']) == 3
        assert again['Exe'] == bn.exe


def test_steam_input_flag_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        ud = _fake_userdata(tmp)
        sc = steam.Shortcut('0', 2731573482, 'Battle.net.exe', '"x"', '"y"', '', ud)
        assert steam.get_steam_input(sc) == '0'
        steam.set_steam_input(sc, '1')
        assert steam.get_steam_input(sc) == '1'
        new = steam.Shortcut('1', 999, 'New', '"x"', '"y"', '', ud)
        assert steam.get_steam_input(new) is None
        steam.set_steam_input(new, '0')
        assert steam.get_steam_input(new) == '0'
        # untouched sibling app survives
        d = vdf.load(steam.localconfig_path(ud))
        assert vdf.get_path(d, 'UserLocalConfigStore', 'apps', '413150', 'LastPlayed') == '1782074015'


def test_compat_tool_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, 'config'))
        shutil.copy(os.path.join(FIX, 'config.compat.snippet.vdf'), os.path.join(tmp, 'config', 'config.vdf'))
        assert steam.get_compat_tool(tmp, 2731573482).startswith('proton')
        steam.set_compat_tool(tmp, 4242, 'proton_experimental')
        assert steam.get_compat_tool(tmp, 4242) == 'proton_experimental'
        assert steam.get_compat_tool(tmp, 2731573482).startswith('proton')


def test_derive_shortcut_appid_high_bit():
    a = steam.derive_shortcut_appid('"/x/y.exe"', 'Y')
    assert a & 0x80000000 and a <= 0xFFFFFFFF

