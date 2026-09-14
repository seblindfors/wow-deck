import io, os, tarfile, tempfile
from wowdeck import selfupdate


def _tarball(version):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for name, data in ((f'wow-deck-{version}/VERSION', version + '\n'), (f'wow-deck-{version}/bin/wow-deck', '#!/bin/sh\n'), (f'wow-deck-{version}/wowdeck/__init__.py', '')):
            info = tarfile.TarInfo(name); b = data.encode(); info.size = len(b); t.addfile(info, io.BytesIO(b))
    return buf.getvalue()


def test_apply_update_replaces_app_dir():
    with tempfile.TemporaryDirectory() as tmp:
        app = os.path.join(tmp, 'app'); os.makedirs(os.path.join(app, 'bin'))
        open(os.path.join(app, 'VERSION'), 'w').write('0.1.0\n'); open(os.path.join(app, 'bin', 'wow-deck'), 'w').write('old')
        open(os.path.join(app, 'stale.txt'), 'w').write('x')
        ver = selfupdate.apply_update(_tarball('0.3.0'), app, log=lambda *a: None)
        assert ver == '0.3.0' and not os.path.exists(os.path.join(app, 'stale.txt'))
        assert os.access(os.path.join(app, 'bin', 'wow-deck'), os.X_OK)
        assert not os.path.exists(app + '.old') and not os.path.exists(app + '.new')


def test_version_compare():
    assert selfupdate._vtuple('0.10.0') > selfupdate._vtuple('0.9.9')
