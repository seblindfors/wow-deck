# SteamOS integration

Facts about SteamOS, Steam and Proton that wow-deck relies on, and how each piece is placed
so that it survives reboots and OS updates.

## File system and persistence

| Location | Survives updates | Used for |
|---|---|---|
| `/home` (`~/.local`, `~/.config`) | Yes | App, launch wrapper, InputPlumber profile, environment.d, launcher |
| `/etc` | Only keep-listed files | InputPlumber device override |
| Root file system | No (`steamos-readonly disable` + pacman is wiped by the next update) | Not used; InputPlumber is already part of the image |

Since SteamOS 3.6 the atomic updater applies a keep-list to `/etc`: any file matched by a
`.conf` in `/etc/atomic-update.conf.d/` is carried over. wow-deck ships
`/etc/atomic-update.conf.d/wow-deck.conf` covering `/etc/inputplumber/**`, the
`inputplumber.service` enablement symlink and itself.

### InputPlumber override

`/etc/inputplumber/devices.d/50-steam_deck.yaml` overrides the shipped configuration of the
same name (same file name wins by directory priority). The override enables automatic
management, lists only the controller hidraw interface as a source (not the internal keyboard),
and sets the idle target to `deck-uhid`. `inputplumber.service` is enabled and restarted only
when no Proton game is running.

### Root actions

All privileged writes run as one `sudo wow-deck --root-phase install|uninstall` call of the
same script: one password prompt, a small auditable code path, and the same code performs the
uninstall. When there is no terminal, the password is requested through a dialog and passed
to `sudo -S`. A Deck without a user password is offered a dialog that drives `passwd`.

## systemd user environment

SteamOS runs both Steam sessions as systemd user units: Desktop Mode Steam under
`steam-launcher.service` and Game Mode under `gamescope-session.service`. Both inherit the
user manager's environment, which is the only place from which a variable reliably reaches
Steam itself in both modes.

wow-deck places `SDL_GAMECONTROLLER_IGNORE_DEVICES=0x054c/0x0df2` in
`~/.config/environment.d/50-wow-deck.conf` (read by `systemd-environment-d-generator` at
login and on `systemctl --user daemon-reload`) and also applies it live with
`systemctl --user set-environment`. Steam reads its environment at start, so one Steam restart
is required after installation. `steam -shutdown` in Desktop Mode is followed by an automatic
relaunch under `steam-launcher.service`, so a tool that shuts Steam down to edit its files will
usually find it running again shortly after.

Steam passes its environment on to games. The launch wrapper rewrites the ignore list for the
game (see [controller-stack.md](controller-stack.md)), so the Steam-side entry never hides the
Edge from WoW.

## Steam client files

Steam rewrites its configuration files while running; every write below happens with Steam
closed and Steam is relaunched afterwards. Reading is always safe. Nothing is written from
Game Mode.

| File | Format | Used for |
|---|---|---|
| `userdata/<id>/config/shortcuts.vdf` | Binary VDF | The Battle.net shortcut: `Exe`, `StartDir`, `LaunchOptions`, `icon`, tags, `appid` |
| `userdata/<id>/config/localconfig.vdf` | Text VDF | Per-app Steam Input flag `UserLocalConfigStore/apps/<appid>/UseSteamControllerConfig` (0 off, 1 default, 2 forced) |
| `config/config.vdf` | Text VDF | Proton selection `InstallConfigStore/Software/Valve/Steam/CompatToolMapping/<appid>` |
| `userdata/<id>/config/grid/<appid>{.jpg,p.jpg,_hero.jpg,_icon.png}` | Images | Shortcut artwork (landscape, portrait, hero, icon) |

Both VDF formats are handled by a vendored codec with byte-exact round trips. Steam assigns
shortcut app ids itself when the user adds a shortcut; wow-deck creates its shortcut with a
stable id (`crc32("wow-deck:Battle.net") | 0x80000000`) so the Proton prefix
(`steamapps/compatdata/<appid>`) and artwork paths are predictable.

The shortcut keeps Steam Input at its default ("Use default settings"). Steam's on-screen
keyboard types only into windows Steam launched with Steam Input active, and it is the
keyboard end users can rely on for the Battle.net login. The paddle path compensates with the
ignore-list rewrite in the launch wrapper.

## Proton

The Battle.net installer is run under Steam's own Proton without Steam involvement, through the
Steam Linux Runtime entry point:

```
<SLR sniper>/_v2-entry-point --verb=waitforexitandrun -- <Proton>/proton waitforexitandrun <exe>
```

with `STEAM_COMPAT_DATA_PATH` pointing at the shortcut's prefix and
`STEAM_COMPAT_CLIENT_INSTALL_PATH` at the Steam root. Proton 10 is preferred; under Proton
Experimental 11 the Battle.net installer fails its version download
(`BLZBNTBTS00000028`), and Proton 10.0-1 and 10.0-2 are excluded because they shipped the
hidraw toggles inverted. The shortcut is mapped to the same Proton version that ran the
installer.

Battle.net writes `Wow.exe` early in the download; `WTF/` and `Interface/AddOns` appear only
after the game's first launch. Installation discovery is therefore keyed off
`<flavour>/Wow.exe`, and folders are created on write.

## Game Mode hand-off

Logging in to Battle.net needs a keyboard, and in Game Mode Steam's keyboard is the session
keyboard and works for every launched title. In Desktop Mode it is unreliable, and KDE's
virtual keyboard hides whenever focus moves to a window without text-input support, which is
every Wine window. The setup therefore splits:

1. Desktop Mode: checklist, privileged preparation, Battle.net installation, Steam shortcut,
   Steam relaunch.
2. A background finisher is started as a transient systemd **user** unit (`systemd-run --user`),
   so it survives the session switch. The user is switched to Game Mode
   (`steamosctl switch-to-game-mode`).
3. In Game Mode the finisher asks Steam to open the Battle.net shortcut
   (`steam steam://rungameid/<appid>`) whenever Battle.net is not running, watches
   `Battle.net.config` (`Client.SavedAccountNames` indicates a completed login) and waits for
   `Wow.exe`.
4. Once WoW exists, the finisher installs the remaining components headlessly (paddle config,
   addons, CurseForge) and records the result; the hub shows that status.

Processes started from an SSH or terminal session are killed by logind when the session ends;
anything that must outlive the caller (Steam relaunch, the finisher, Battle.net) is started as
a transient user unit.

## Desktop integration

KDE on Wayland matches a window to its launcher through the application id
(`org.consoleport.wowdeck`), so the desktop entry is named
`org.consoleport.wowdeck.desktop`, carries `StartupWMClass`, and references the icon by absolute
path (a themed name can be cached as missing by Plasma right after installation); a themed copy
is installed under `~/.local/share/icons/hicolor/256x256/apps/` as well.
