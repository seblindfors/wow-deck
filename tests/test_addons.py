import io, os, tempfile, zipfile
from wowdeck import addons


def _zip(folders):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for f in folders:
            z.writestr(f'{f}/{f}.toc', '## Interface: 120000\n')
            z.writestr(f'{f}/Core.lua', 'print(1)\n')
        z.writestr('../evil.lua', 'x')     # zip-slip attempt must be ignored
    return buf.getvalue()


def test_install_and_remove_records_state(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(addons, 'STATE', os.path.join(tmp, 'state.json'))
        wtfs = []
        for fl in ('_retail_', '_classic_era_'):
            d = os.path.join(tmp, 'World of Warcraft', fl, 'WTF'); os.makedirs(d); wtfs.append(d)
        tops = addons.install_zip_bytes('bugsack', _zip(['BugSack']), wtfs, log=lambda *a: None)
        assert tops == ['BugSack']
        assert addons.is_installed('bugsack', wtfs)
        assert os.path.isfile(os.path.join(tmp, 'World of Warcraft', '_retail_', 'Interface', 'AddOns', 'BugSack', 'BugSack.toc'))
        assert not os.path.exists(os.path.join(tmp, 'World of Warcraft', '_retail_', 'Interface', 'evil.lua'))
        addons.remove('bugsack', wtfs, log=lambda *a: None)
        assert not addons.is_installed('bugsack', wtfs)


def test_consoleport_suite_detection(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(addons, 'STATE', os.path.join(tmp, 'state.json'))
        wtfs = [os.path.join(tmp, 'World of Warcraft', '_retail_', 'WTF')]; os.makedirs(wtfs[0])
        assert not addons.is_installed('consoleport', wtfs)
        addons.install_zip_bytes('consoleport', _zip(addons.MANIFEST['consoleport']['folders']), wtfs, log=lambda *a: None)
        assert addons.is_installed('consoleport', wtfs)
