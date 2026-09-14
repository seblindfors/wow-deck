from __future__ import annotations
import argparse, os, subprocess, sys
from . import battlenet, components, curseforge, deck, files, selfupdate, steam, ui

OK, WARN, FAIL = '\033[32mOK  \033[0m', '\033[33mWARN\033[0m', '\033[31mFAIL\033[0m'


def _p(status, msg):
    print(f'{status} {msg}')


def doctor(args) -> int:
    blockers = 0
    if not deck.is_steamos():
        _p(WARN, f"not SteamOS (ID={deck.os_release().get('ID')}); reporting what can be read")
    v = deck.steamos_version() if deck.is_steamos() else None
    if v:
        good = v >= deck.INPUTPLUMBER_MIN_STEAMOS
        _p(OK if good else FAIL, f'SteamOS {".".join(map(str, v))}' + ('' if good else ' (< 3.7: no InputPlumber)'))
        blockers += not good
    _p(WARN if deck.in_gamescope() else OK, 'session: ' + ('Game Mode (Steam files are read-only here)' if deck.in_gamescope() else 'Desktop Mode'))

    ipv = deck.inputplumber_version()
    if ipv:
        active, enabled = deck.unit_state('inputplumber.service')
        _p(OK if (active == 'active' and enabled == 'enabled') else WARN, f'inputplumber {ipv}: {active}, {enabled}')
        _p(OK if os.path.isfile(files.ROOT_OVERRIDE) else WARN, f'Deck override {files.ROOT_OVERRIDE}')
        _p(OK if os.path.isfile(files.ROOT_KEEPLIST) else WARN, f'update keep-list {files.ROOT_KEEPLIST}')
        devs = deck.ip_devices()
        _p(OK if devs else WARN, f'InputPlumber composite devices: {devs or "none (not managing the Deck)"}')
        if devs:
            _p(OK, f'current target: {", ".join(deck.ip_targets(devs[0])) or "?"}')
    else:
        _p(FAIL, 'inputplumber binary not found'); blockers += 1

    pw = deck.password_status()
    if pw is not None:
        _p(OK if pw == 'P' else FAIL, 'user password: ' + ('set' if pw == 'P' else f'{pw} (run "passwd" first; the root step needs it)'))
        blockers += pw != 'P'
    _p(OK if os.access(files.WRAPPER, os.X_OK) else WARN, f'wrapper {files.WRAPPER}')

    root = steam.steam_root()
    if not root:
        _p(FAIL, 'Steam root not found'); return 1
    protons = deck.proton_versions(root)
    _p(OK if protons else WARN, 'Proton: ' + ', '.join(f'{k} ({v})' for k, v in protons.items()))
    scs = deck.find_battlenet_shortcuts(root)
    if not scs:
        _p(WARN, 'no Battle.net shortcut in Steam yet (WoW Deck -> Set up installs Battle.net and adds it)')
    for sc in scs:
        _p(OK, f'shortcut "{sc.name}" appid {sc.appid}')
        has_opts = files.WRAPPER in sc.launch_options and '%command%' in sc.launch_options
        _p(OK if has_opts else WARN, f'  launch options: {sc.launch_options or "(none)"}' + ('' if has_opts else f'  -> set to: {files.LAUNCH_OPTIONS}'))
        si = steam.get_steam_input(sc)
        _p(OK, f'  Steam Input: {"disabled" if si == "0" else "enabled (wrapper filters the device list)"}')
        st = steam.steam_process_ignores_edge(); menv = steam.manager_env_ignores_edge()
        _p(OK if st or (st is None and menv) else WARN,
           f'  Steam ignores the emulated Edge: {"yes" if st else "Steam not running; user env " + ("set" if menv else "NOT set") if st is None else "NO (restart Steam; inputs double up while WoW runs)"}')
        tool = steam.get_compat_tool(root, sc.appid)
        tdir = deck.compat_tool_dir(root, tool or '')
        tver = protons.get(os.path.basename(tdir)) if tdir else None
        bad = tver in deck.PROTON_BAD
        _p(FAIL if bad else (OK if tool else WARN), f'  Proton: {tool or "(default)"}' + (f' = {tver}' if tver else '') + (' (broken hidraw env in this build; pick 10.0-3+ or Experimental)' if bad else ''))
        blockers += bad
    wtfs = deck.wow_wtf_dirs(root)
    _p(OK if wtfs else WARN, f'WoW installs: {len(wtfs)}')
    for d in wtfs:
        _p(OK if os.path.isfile(os.path.join(d, files.WOW_JSON)) else WARN, f'  {files.WOW_JSON} in {d.split("compatdata/")[-1]}')
    return 1 if blockers else 0


def _sudo_root_phase(action: str) -> int:
    me = os.path.abspath(sys.argv[0])
    print(f'Root step ({action}): running "sudo {me} --root-phase {action}"')
    return subprocess.call(['sudo', sys.executable, me, '--root-phase', action])


def install(args) -> int:
    root = steam.steam_root()
    if not root:
        print('Steam root not found'); return 1
    if args.dry_run:
        wtfs = deck.wow_wtf_dirs(root)
        print('DRY RUN. Would write:')
        for p in (files.WRAPPER, files.ENV_CONF, *[os.path.join(d, files.WOW_JSON) for d in wtfs]):
            print(f'  {"update " if os.path.exists(p) else "create "} {p}')
        print(f'  root: {", ".join(files.ROOT_FILES)}; enable+restart inputplumber.service')
        for sc in deck.find_battlenet_shortcuts(root):
            print(f'  Steam "{sc.name}" ({sc.appid}): LaunchOptions -> {files.LAUNCH_OPTIONS}' + ('; UseSteamControllerConfig -> 0' if components.STEAM_INPUT_OFF else ''))
        print(f'  {files.ENVD} + systemctl --user set-environment (Steam ignores the emulated Edge)')
        return 0
    print('User files:')
    files.install_user()
    wtfs = deck.wow_wtf_dirs(root)
    print(f'WoW config ({len(wtfs)} install(s)):')
    files.install_wow_json(wtfs)
    if not args.skip_root:
        if deck.password_status() not in (None, 'P') and subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode != 0:
            print('Root step skipped: no password is set for this user. Run "passwd" in Konsole, then "wow-deck install" again.')
            return 1
        if _sudo_root_phase('install') != 0:
            print('Root step failed or was cancelled; re-run "wow-deck install" later.'); return 1
    scs = deck.find_battlenet_shortcuts(root)
    print('Steam shortcut:')
    if not scs:
        print('  no Battle.net shortcut found; run "wow-deck setup" to install Battle.net and add it.')
    elif args.no_steam_edit or deck.in_gamescope():
        for sc in scs:
            print(f'  "{sc.name}": set launch options to\n      {files.LAUNCH_OPTIONS}' + ('\n  and Controller settings -> Disable Steam Input.' if components.STEAM_INPUT_OFF else ''))
        print('  then restart Steam so it picks up the SDL ignore list from the user environment.')
    else:
        if steam.steam_running():
            print('  closing Steam to edit its config...')
            if not steam.steam_shutdown():
                print('  Steam did not exit; edit manually:\n      ' + files.LAUNCH_OPTIONS); return 1
        for sc in scs:
            steam.set_launch_options(sc, files.LAUNCH_OPTIONS); print(f'  "{sc.name}": launch options set')
            if components.STEAM_INPUT_OFF:
                steam.set_steam_input(sc, '0'); print(f'  "{sc.name}": Steam Input disabled')
        steam.steam_launch(); print('  Steam relaunched (with the SDL ignore list)')
    print('\nDone. Run "wow-deck doctor" to verify.')
    return 0


def uninstall(args) -> int:
    if getattr(args, 'all', False):
        return uninstall_all(args)
    root = steam.steam_root()
    print('User files:')
    files.remove_user()
    relaunch = False
    if root:
        files.remove_wow_json(deck.wow_wtf_dirs(root))
        print('Steam shortcut:')
        for sc in deck.find_battlenet_shortcuts(root):
            if files.WRAPPER not in sc.launch_options:
                print(f'  "{sc.name}": no wrapper in launch options'); continue
            if steam.steam_running() and not deck.in_gamescope() and not args.no_steam_edit:
                print('  closing Steam to edit its config...'); relaunch = steam.steam_shutdown()
            if not steam.steam_running():
                steam.set_launch_options(sc, sc.launch_options.replace(files.WRAPPER + ' ', '').strip())
                print(f'  "{sc.name}": wrapper removed from launch options (Steam Input setting left as is)')
            else:
                print(f'  "{sc.name}": remove "{files.WRAPPER}" from launch options manually')
        if steam.steam_process_ignores_edge():
            print('  Steam still has the SDL ignore list in its environment until it is restarted')
    if not args.skip_root:
        _sudo_root_phase('uninstall')
    if relaunch and not args.no_steam_relaunch:
        steam.steam_launch(); print('Steam relaunched')
    print('Done.')
    return 0


def uninstall_all(args) -> int:
    """Hub "Uninstall": remove every optional component WoW Deck installed (addons, CurseForge,
    paddle mapping incl. the root step) and then WoW Deck itself. Battle.net, its Steam
    shortcut and World of Warcraft stay."""
    ctx = components.make_ctx(print, steam_edit=not getattr(args, 'no_steam_edit', False))
    if ctx is None:
        print('Steam root not found'); return 1
    env = steam.session_env()
    subprocess.run(['systemctl', '--user', 'stop', 'wow-deck-finish.service'], capture_output=True, env=env)
    failures = []
    # paddles last: it may close Steam and needs sudo
    for c in sorted((c for c in components.COMPONENTS if not c.required and c.detect(ctx)), key=lambda c: c.id == 'paddles'):
        print(f'== Removing {c.title}')
        try:
            c.remove(ctx)
        except Exception as e:
            failures.append(f'{c.title}: {e}'); print(f'  FAILED {e}')
    if ctx.steam_closed_by_us:
        steam.steam_launch(); print('Steam relaunched')
    print('== Removing WoW Deck')
    home = os.path.expanduser('~')
    appid = 'org.consoleport.wowdeck'
    for p in (os.path.join(files.USER_BIN, 'wow-deck'),
              os.path.join(home, '.local', 'share', 'applications', f'{appid}.desktop'), os.path.join(home, 'Desktop', f'{appid}.desktop'),
              os.path.join(home, '.local', 'share', 'applications', 'wow-deck.desktop'), os.path.join(home, 'Desktop', 'wow-deck.desktop'),
              os.path.join(home, '.local', 'share', 'icons', 'hicolor', '256x256', 'apps', f'{appid}.png')):
        if os.path.lexists(p):
            os.remove(p); print(f'  removed {p}')
    import shutil
    if os.path.isdir(files.USER_DATA):
        shutil.rmtree(files.USER_DATA, ignore_errors=True); print(f'  removed {files.USER_DATA}')
    print('Done. Battle.net, its Steam shortcut and World of Warcraft were left in place.'
          + ('' if not failures else '\nProblems: ' + '; '.join(failures)))
    return 1 if failures else 0


def paddles(args) -> int:
    if subprocess.run(['pgrep', '-x', 'wineserver'], capture_output=True).returncode == 0 and not args.force:
        print('A Wine/Proton game is running; switching targets now would crash its controller bus. Use --force to override.')
        return 1
    devs = deck.ip_devices()
    if not devs:
        print('InputPlumber is not managing the Deck'); return 1
    target = 'ds5-edge' if args.state == 'on' else 'deck-uhid'
    ok = deck.ip_set_target(target, devs[0])
    if ok and args.state == 'on':
        deck.run(['inputplumber', 'device', devs[0], 'targets', 'set', 'ds5-edge', 'deck-uhid'])
        deck.run(['inputplumber', 'device', devs[0], 'profile', 'load', files.PROFILE])
    elif ok:
        deck.run(['inputplumber', 'device', devs[0], 'profile', 'load', '/usr/share/inputplumber/profiles/default.yaml'])
    print(f'target -> {target}: {"ok" if ok else "failed"}')
    return 0 if ok else 1




def setup(args) -> int:
    log_lines: list[str] = []
    def log(*a):
        line = ' '.join(str(x) for x in a); print(line, flush=True); log_lines.append(line)
    ctx = components.make_ctx(log, steam_edit=not args.no_steam_edit)
    if ctx is None:
        ui.error('Steam was not found on this system.'); return 1
    if deck.in_gamescope():
        ui.error('Please run the setup from Desktop Mode (Steam menu -> Power -> Switch to Desktop).'); return 1
    if deck.password_status() not in (None, 'P'):
        # Passwordless Deck: create one here so the paddles step can use sudo (Decky asks the same).
        while True:
            pw = ui.password('Your Steam Deck has no user password yet. Native paddles need one for a single system step.\n\n'
                             'Choose a password for the "deck" user (you can change it later with passwd):')
            if pw is None:
                ui.error('Setup cancelled: a password is required for the native paddles step.\nUntick that item to set up without it.'); return 1
            pw2 = ui.password('Repeat the password:')
            if pw and pw == pw2:
                if deck.set_user_password(pw):
                    ui.info('Password set.'); break
                ui.error('Setting the password failed. Open Konsole and run "passwd", then start the setup again.'); return 1
            ui.error('The passwords did not match; try again.')
    env = steam.session_env()
    if subprocess.run(['systemctl', '--user', 'is-active', 'wow-deck-finish.service'], capture_output=True, env=env).returncode == 0:
        ui.info('WoW Deck is still finishing a previous setup in the background (waiting for World of Warcraft to be installed).\n\n'
                'Switch to Game Mode, open Battle.net from your library and install WoW; the rest completes on its own.'); return 0
    deck.ensure_virtual_keyboard(log)
    state = {c.id: c.detect(ctx) for c in components.COMPONENTS}
    items = [(c.id, c.title + ('   [installed]' if state[c.id] else ''), state[c.id] or c.default, c.required) for c in components.COMPONENTS]
    chosen = ui.checklist(ui.header('Set up World of Warcraft', 'Installed items are ticked; untick one to remove it.'), items)
    if chosen is None:
        print('cancelled'); return 1
    to_install = [c for c in components.COMPONENTS if c.id in chosen and not state[c.id]]
    to_remove = [c for c in components.COMPONENTS if c.id not in chosen and state[c.id] and not c.required]
    if to_remove and not ui.yesno('Remove: ' + ', '.join(c.title for c in to_remove) + '?'):
        to_remove = []
    if not to_install and not to_remove:
        ui.info('Everything selected is already installed. Nothing to do.'); return 0
    failures = []
    def run_step(c, fn, verb):
        log(f'== {verb} {c.title}'); ui.note(f'{verb} {c.title}...')
        try:
            fn(ctx); return True
        except Exception as e:
            failures.append(f'{c.title}: {e}'); log(f'  FAILED {e}'); return False
    for c in to_remove:
        run_step(c, c.remove, 'Removing')
    # 1. dialog/sudo-capable preparation (wrapper, InputPlumber) while we still have a Desktop session
    for c in to_install:
        if c.prepare:
            run_step(c, c.prepare, 'Preparing')
    # 2. Battle.net + Steam shortcut (required component)
    bn = next((c for c in to_install if c.required), None)
    if bn and not run_step(bn, bn.install, 'Installing'):
        if ctx.steam_closed_by_us or not steam.steam_running():
            steam.steam_launch()
        ui.error('Setup stopped:\n\n' + '\n'.join(failures)); return 1
    rest = [c for c in to_install if not c.required]
    # 3. WoW not installed yet: hand off to the background finisher and switch to Game Mode
    if rest and not components.wow_installed(ctx):
        if ctx.steam_closed_by_us or not steam.steam_running():
            steam.steam_launch(); log('Steam started')
        ok = spawn_finisher([c.id for c in rest], log)
        msg = ('Battle.net is installed and in your Steam library.\n\n'
               'Next: switch to Game Mode, open Battle.net from the library, log in (Steam + X for the keyboard, '
               'or scan the QR code with the Battle.net mobile app) and install World of Warcraft.\n\n'
               + ('The remaining items finish automatically in the background once WoW is installed: '
                  + ', '.join(c.title.replace('Install ', '') for c in rest) + '.' if ok else
                  'Run WoW Deck -> Set up again after WoW is installed to finish the remaining items.')
               + '\n\nSwitch to Game Mode now?')
        if deck.is_steamos() and ui.yesno(msg):
            deck.return_to_game_mode()
        return 0
    # 4. WoW present: finish directly
    for c in rest:
        run_step(c, c.install, 'Installing')
    if ctx.steam_closed_by_us or not steam.steam_running():
        steam.steam_launch(); log('Steam started')
    summary = '\n'.join(l for l in log_lines if l.startswith('==') or '  FAILED' in l or 'MANUAL' in l)
    if failures:
        ui.error('Setup finished with problems:\n\n' + '\n'.join(failures) + '\n\nDetails:\n' + summary); return 1
    if deck.is_steamos() and ui.yesno('Setup complete.\n\n' + summary + '\n\nSwitch to Game Mode now? Battle.net is in your library there.'):
        deck.return_to_game_mode()
    else:
        ui.info('Setup complete.\n\n' + summary + '\n\nLaunch Battle.net from your Steam library in Game Mode.')
    return 0


def curseforge_cmd(args) -> int:
    root = steam.steam_root()
    if not root:
        print('Steam root not found'); return 1
    wtfs = deck.wow_wtf_dirs(root)
    wow = curseforge.wow_install_dir(wtfs)
    if not wow:
        print('No World of Warcraft install found under Steam compatdata; install WoW via Battle.net first.'); return 1
    if args.dry_run:
        print('DRY RUN. Would: place AppImage at', curseforge.APPIMAGE, '| desktop entry', curseforge.DESKTOP_ENTRY,
              '| symlink', curseforge.WOW_LINK, '->', wow, '| register flavours:',
              ', '.join(curseforge.FLAVOURS[os.path.basename(os.path.dirname(d))][1] for d in wtfs if os.path.basename(os.path.dirname(d)) in curseforge.FLAVOURS))
        return 0
    print('CurseForge:')
    if not args.no_download:
        curseforge.install_appimage()
    if os.path.isfile(curseforge.APPIMAGE):
        curseforge.write_desktop_entry()
    curseforge.ensure_wow_symlink(wow)
    if curseforge.curseforge_running():
        print('  CurseForge is running: not editing its game registry. Quit it and re-run, or use "Manually add a game".')
    else:
        curseforge.seed_instances(curseforge.WOW_LINK, wtfs)
    if args.launch and os.path.isfile(curseforge.APPIMAGE):
        curseforge.launch(); print('  launched CurseForge')
    return 0


def battlenet_cmd(args) -> int:
    """Developer/support verb: run the Battle.net install flow regardless of detection."""
    root = steam.steam_root()
    if not root:
        print('Steam root not found'); return 1
    uds = steam.userdata_dirs(root)
    ctx = components.make_ctx(print, steam_edit=not args.no_steam_edit)
    sc = battlenet.install(root, uds[0], files.LAUNCH_OPTIONS, log=print, note=ui.note,
                           ensure_steam_closed=ctx.ensure_steam_closed, wow_timeout=args.wait_wow)
    if ctx.steam_closed_by_us:
        steam.steam_launch(); print('Steam relaunched')
    print('shortcut:', sc)
    return 0


def _find_curseforge_app() -> str | None:
    cands = [curseforge.APPIMAGE] + [os.path.join(d, f) for d in (os.path.expanduser('~/Applications'), os.path.expanduser('~/Desktop'))
                                      if os.path.isdir(d) for f in sorted(os.listdir(d)) if f.lower().startswith('curseforge') and f.lower().endswith('.appimage')]
    return next((c for c in cands if os.path.isfile(c)), None)


def hub(args) -> int:
    """WoW Deck: setup + maintenance menu (what the desktop launcher opens)."""
    if not getattr(args, 'text', False):
        try:
            from . import gtkui
            if gtkui.AVAILABLE and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                import sys as _s
                return gtkui.run_hub(_s.modules[__name__], getattr(args, 'open', None))
        except Exception as e:          # fall back to the dialog menu
            print(f'GTK UI unavailable ({e}); using dialogs', flush=True)
    while True:
        cf = _find_curseforge_app()
        items = [('setup', 'Set up / change installed components'),
                 ('status', 'Check status (doctor)')]
        if cf:
            items.append(('curseforge', 'Open CurseForge (addon manager)'))
        items += [('update', f'Check for WoW Deck updates (installed: {selfupdate.current_version()})'),
                  ('gamemode', 'Switch to Game Mode'),
                  ('help', 'Help: what WoW Deck does'),
                  ('uninstall', 'Uninstall WoW Deck (addons, CurseForge, paddle mapping; Battle.net/WoW stay)'),
                  ('quit', 'Quit')]
        env = steam.session_env()
        fin = 'finishing a setup in the background (waiting for WoW)' if subprocess.run(['systemctl', '--user', 'is-active', 'wow-deck-finish.service'], capture_output=True, env=env).returncode == 0 else ''
        if not fin and os.path.isfile(FINISH_DONE):
            fin = 'last background finish: ' + open(FINISH_DONE).read().strip()
        choice = ui.menu(ui.header('WoW Deck', fin or 'World of Warcraft on the Steam Deck, with ConsolePort.'), items)
        if choice in (None, 'quit'):
            return 0
        if choice == 'setup':
            setup(argparse.Namespace(no_steam_edit=False))
        elif choice == 'status':
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                doctor(argparse.Namespace())
            import re
            ui.textbox('Status', re.sub(r'\x1b\[[0-9;]*m', '', buf.getvalue()))
        elif choice == 'curseforge' and cf:
            curseforge.launch(cf); ui.note('CurseForge starting...')
        elif choice == 'update':
            msg = selfupdate.check_and_update(log=print)
            ui.info(msg)
            if 'updated' in msg:
                return 0
        elif choice == 'gamemode':
            deck.return_to_game_mode(); return 0
        elif choice == 'help':
            from .help import render_text
            ui.textbox('What WoW Deck does', render_text(90))
        elif choice == 'uninstall':
            if ui.yesno('Remove everything WoW Deck installed: addons, CurseForge, the paddle mapping and WoW Deck itself?\n\nBattle.net, its Steam shortcut and World of Warcraft stay.'):
                uninstall_all(argparse.Namespace(no_steam_edit=False)); return 0


def help_cmd(args) -> int:
    from .help import render_text
    import shutil
    print(render_text(min(96, shutil.get_terminal_size((80, 24)).columns - 2))); return 0


FINISH_LOG = os.path.join(files.USER_DATA, 'finish.log')
FINISH_DONE = os.path.join(files.USER_DATA, 'finish.done')


def finish(args) -> int:
    """Headless finisher: wait for WoW to be installed (hours), then install the selected
    user-level components. Runs as a transient user unit so it survives the switch to Game Mode."""
    import time
    os.makedirs(files.USER_DATA, exist_ok=True)
    logf = open(FINISH_LOG, 'a', buffering=1)
    def log(*a):
        line = ' '.join(str(x) for x in a); print(line, flush=True); logf.write(time.strftime('%H:%M:%S ') + line + '\n')
    ctx = components.make_ctx(log, steam_edit=False)
    if ctx is None:
        log('Steam root not found'); return 1
    root = ctx.root
    compat = battlenet.compatdata(root, battlenet.shortcut_appid())
    wanted = [c for c in components.COMPONENTS if c.id in set(args.components.split(',')) and not c.required]
    log(f'== finish: waiting for WoW; then {", ".join(c.id for c in wanted) or "nothing"}')
    if os.path.exists(FINISH_DONE):
        os.remove(FINISH_DONE)
    deadline = time.time() + args.timeout_hours * 3600
    seen_login = False
    last_launch = 0.0
    while time.time() < deadline:
        if not seen_login and battlenet.logged_in(compat):
            seen_login = True; log('  Battle.net login detected')
        if os.path.isfile(battlenet.wow_exe(compat)):
            log('  World of Warcraft executable present (Battle.net keeps downloading data; files can be placed now)'); break
        # In Game Mode, open Battle.net for the user through Steam (once every few minutes if
        # it is not running), so the hand-off is "switch to Game Mode" and nothing else.
        if deck.in_gamescope() and steam.steam_running() and not battlenet.battlenet_running() and time.time() - last_launch > 240:
            last_launch = time.time()
            ok = battlenet.launch_via_steam(battlenet.shortcut_appid(), steam.session_env())
            log(f'  asked Steam to launch Battle.net: {"sent" if ok else "failed"}')
        time.sleep(20)
    else:
        log('  gave up waiting for WoW'); return 1
    time.sleep(30)                       # let Battle.net finish writing the install
    ctx.wtf_dirs = deck.wow_wtf_dirs(root); ctx.shortcuts = deck.find_battlenet_shortcuts(root)
    failures = []
    for c in wanted:
        log(f'== Installing {c.title}')
        try:
            c.install(ctx)
        except Exception as e:
            failures.append(f'{c.title}: {e}'); log(f'  FAILED {e}')
    open(FINISH_DONE, 'w').write(('OK' if not failures else 'FAILED ' + '; '.join(failures)) + '\n')
    log('== finish complete' + (' with failures' if failures else ''))
    return 1 if failures else 0


def spawn_finisher(component_ids: list[str], log=print) -> bool:
    me = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin', 'wow-deck')
    env = steam.session_env()
    subprocess.run(['systemctl', '--user', 'reset-failed', 'wow-deck-finish.service'], capture_output=True, env=env)
    r = subprocess.run(['systemd-run', '--user', '--unit=wow-deck-finish', '--collect', sys.executable, me, 'finish',
                        '--components', ','.join(component_ids)], capture_output=True, text=True, env=env)
    log('  background finisher started' if r.returncode == 0 else f'  FAILED to start finisher: {r.stderr.strip()}')
    return r.returncode == 0


def root_phase(action: str) -> int:
    if os.geteuid() != 0:
        print('--root-phase must run as root'); return 1
    print(f'Root files ({action}):')
    (files.root_install if action == 'install' else files.root_uninstall)()
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)   # keep our output ordered around sudo/subprocess calls
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog='wow-deck', description='Native paddle buttons for WoW on the Steam Deck.')
    ap.add_argument('--root-phase', choices=['install', 'uninstall'], help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('doctor', help='check every layer and report')
    pi = sub.add_parser('install', help='install/update everything'); pi.add_argument('--skip-root', action='store_true'); pi.add_argument('--no-steam-edit', action='store_true', help='print the Steam steps instead of editing Steam files'); pi.add_argument('--dry-run', action='store_true', help='show what would change')
    sub.add_parser('update', help='alias for install')
    pu = sub.add_parser('uninstall', help='remove the paddle mapping (--all: also addons, CurseForge and WoW Deck itself)'); pu.add_argument('--skip-root', action='store_true'); pu.add_argument('--no-steam-edit', action='store_true'); pu.add_argument('--no-steam-relaunch', action='store_true', help=argparse.SUPPRESS); pu.add_argument('--all', action='store_true', help='remove every component WoW Deck installed and WoW Deck itself (Battle.net/WoW stay)')
    pf = sub.add_parser('finish', help=argparse.SUPPRESS); pf.add_argument('--components', default=''); pf.add_argument('--timeout-hours', type=float, default=12)
    pb = sub.add_parser('battlenet', help=argparse.SUPPRESS); pb.add_argument('--no-steam-edit', action='store_true'); pb.add_argument('--wait-wow', type=float, default=0)
    ph = sub.add_parser('hub', help='WoW Deck menu (setup + maintenance)'); ph.add_argument('--text', action='store_true', help='use kdialog/zenity menus instead of the GTK window'); ph.add_argument('--open', choices=['setup', 'status'], help=argparse.SUPPRESS)
    sub.add_parser('help', help='explain what WoW Deck does')
    ps = sub.add_parser('setup', help='guided, opt-in setup (dialogs)'); ps.add_argument('--no-steam-edit', action='store_true')
    pc = sub.add_parser('curseforge', help='set up the CurseForge addon manager for this WoW install')
    pc.add_argument('--no-download', action='store_true', help='do not download the AppImage'); pc.add_argument('--launch', action='store_true'); pc.add_argument('--dry-run', action='store_true')
    pp = sub.add_parser('paddles', help='switch the controller target now'); pp.add_argument('state', choices=['on', 'off']); pp.add_argument('--force', action='store_true')
    args = ap.parse_args(argv)
    if args.root_phase:
        return root_phase(args.root_phase)
    if args.cmd in (None, 'doctor'):
        return doctor(args)
    return {'install': install, 'update': install, 'uninstall': uninstall, 'paddles': paddles, 'curseforge': curseforge_cmd, 'setup': setup, 'battlenet': battlenet_cmd, 'hub': hub, 'help': help_cmd, 'finish': finish}[args.cmd](args)
