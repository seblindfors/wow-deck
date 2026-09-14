import json, os, tempfile
from wowdeck import curseforge as cf


def _fake_wow(tmp):
    wow = os.path.join(tmp, 'pfx', 'World of Warcraft')
    wtfs = []
    for f in ('_retail_', '_classic_era_', '_ptr_'):
        d = os.path.join(wow, f, 'WTF'); os.makedirs(d); wtfs.append(d)
    return wow, wtfs


def test_wow_install_dir_and_symlink():
    with tempfile.TemporaryDirectory() as tmp:
        wow, wtfs = _fake_wow(tmp)
        assert cf.wow_install_dir(wtfs) == wow
        link = os.path.join(tmp, 'World of Warcraft')
        cf.ensure_wow_symlink(wow, link, log=lambda *a: None)
        assert os.path.islink(link) and os.path.realpath(link) == os.path.realpath(wow)
        cf.ensure_wow_symlink(wow, link, log=lambda *a: None)   # idempotent


def test_seed_instances_creates_and_merges():
    with tempfile.TemporaryDirectory() as tmp:
        wow, wtfs = _fake_wow(tmp)
        link = os.path.join(tmp, 'World of Warcraft'); os.symlink(wow, link)
        reg = os.path.join(tmp, 'cfg', 'AddonGameInstance.json')
        added = cf.seed_instances(link, wtfs, reg, log=lambda *a: None)
        assert sorted(added) == ['Classic Era', 'Retail']            # _ptr_ skipped
        data = json.load(open(reg))
        assert {i['gameVersionTypeId'] for i in data} == {517, 67408}
        assert all(i['installPath'].endswith('/') and i['gameTypeID'] == 1 for i in data)
        assert all(i['syncProfile']['GameInstanceGuid'] == i['guid'] for i in data)
        # second run adds nothing and keeps the file intact
        assert cf.seed_instances(link, wtfs, reg, log=lambda *a: None) == []
        assert len(json.load(open(reg))) == 2


def test_seed_respects_existing_entries_by_realpath():
    with tempfile.TemporaryDirectory() as tmp:
        wow, wtfs = _fake_wow(tmp)
        link = os.path.join(tmp, 'World of Warcraft'); os.symlink(wow, link)
        reg = os.path.join(tmp, 'AddonGameInstance.json')
        # an entry registered through the real path (not the symlink) must still count
        json.dump([{'guid': 'x', 'installPath': os.path.join(wow, '_retail_') + '/', 'gameVersionTypeId': 517}], open(reg, 'w'))
        added = cf.seed_instances(link, wtfs, reg, log=lambda *a: None)
        assert added == ['Classic Era']


def test_wow_dirs_without_wtf(tmp_path):
    from wowdeck import deck
    root = tmp_path
    flav = root / 'steamapps' / 'compatdata' / '1' / 'pfx' / 'drive_c' / 'Program Files (x86)' / 'World of Warcraft' / '_retail_'
    flav.mkdir(parents=True); (flav / 'Wow.exe').write_bytes(b'MZ')
    (flav.parent / '_ptr_').mkdir()             # no exe -> ignored
    assert deck.wow_flavour_dirs(str(root)) == [str(flav)]
    assert deck.wow_wtf_dirs(str(root)) == [str(flav / 'WTF')]
