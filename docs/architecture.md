# Architecture

wow-deck is a dependency-free Python 3 application for SteamOS (standard library plus the
PyGObject/GTK4 bindings that SteamOS ships). It lives entirely under the user's home
directory, with two keep-listed files under `/etc`, and every action it takes is idempotent
and reversible.

## Layout

```
bin/wow-deck              entry point (thin launcher for the package)
wowdeck/
  cli.py                  verbs: hub, setup, finish, doctor, install, uninstall, paddles,
                          curseforge, help; argument parsing and the dialog-menu hub
  components.py           the opt-in component model (detect / prepare / install / remove)
  battlenet.py            Battle.net installer under Proton, Steam shortcut, WoW detection
  steam.py                Steam root and user data, shortcuts, per-app flags, compat tool,
                          artwork, shutdown / relaunch, environment for launching from a unit
  vdf.py                  text and binary VDF codec (byte-exact round trip)
  deck.py                 SteamOS facts: version, session type, InputPlumber state and
                          targets, Proton versions, WoW install discovery, Game Mode switch
  files.py                payload placement: user files, WoW config, environment.d, root phase
  addons.py               addon manifest, download, zip-slip-safe extraction, state for removal
  curseforge.py           CurseForge AppImage, desktop entry, game-instance registration
  selfupdate.py           update check and in-place update from GitHub releases
  gtkui.py                GTK4 touch front end (hub window, dialogs) replacing ui.*
  ui.py                   kdialog / zenity / plain-text dialog fallback
  help.py                 structured help content rendered by every front end
share/
  wow-deck-launch.sh      Steam launch-option wrapper (controller switch around the game)
  wow-deck-edge.yaml      InputPlumber profile: targets ds5-edge + deck-uhid, no remaps
  50-steam_deck.yaml      InputPlumber device override for the Deck (root)
  wow-deck.conf           /etc keep-list entries (root)
  GamePadConfig_SteamDeck.json   WoW config: paddle order, Steam button unbound
  art/                    Steam shortcut artwork; branding/ the app logo
  wow-deck-setup.desktop  launcher template (app id org.consoleport.wowdeck)
install.sh                one-line installer; release.sh builds the release tarball
tests/                    pytest suite over fixture copies of real Steam files
```

## Component model

Each optional piece is a `Component` with four operations:

| Operation | Runs | Purpose |
|---|---|---|
| `detect` | Always | Is the component fully installed? Pre-ticks the checklist |
| `prepare` | Desktop Mode, before Battle.net | Steps that need dialogs or sudo (launch wrapper, InputPlumber, environment) |
| `install` | Desktop Mode or the headless finisher | Everything that needs WoW to exist (addons, WoW config, shortcut launch options) |
| `remove` | Desktop Mode | Exact inverse of install and prepare |

Components, in checklist order: Battle.net + World of Warcraft (required), gamepad mapping
with native paddle support, ConsolePort, BugGrabber + BugSack, CurseForge. Ticked items that
are not installed get installed; installed items that are unticked get removed.

A shared context carries the Steam root, the WoW installations found, the Battle.net
shortcuts, a logger, and a single flag recording whether Steam was closed by the run, so Steam
is shut down at most once per run and relaunched at the end.

## Setup flow

```
checklist
  -> prepare (paddles: wrapper, InputPlumber via sudo, Steam environment)
  -> Battle.net: installer under Proton, wait for Battle.net.exe,
     Steam closed -> shortcut + artwork + Proton mapping -> Steam relaunched
  -> WoW already installed?  yes: install the remaining components now
                             no:  start the background finisher, switch to Game Mode
finisher (transient user unit)
  -> ask Steam to open Battle.net in Game Mode, wait for login and Wow.exe
  -> install the remaining components, record the result
```

See [steamos-integration.md](steamos-integration.md) for the reasoning behind the Game Mode
hand-off and the transient unit.

## Launch wrapper

The Steam shortcut's launch options are `~/.local/bin/wow-deck-launch.sh %command%`. At
launch the wrapper makes sure InputPlumber manages the controller, sets the targets to
`ds5-edge` and `deck-uhid`, loads the profile, waits for the Edge hidraw node to appear,
rewrites `SDL_GAMECONTROLLER_IGNORE_DEVICES` for the game, sources optional overrides from
`~/.local/share/wow-deck/env.conf`, runs the game, and restores the idle target on exit
(also on signals). It logs to `~/.local/share/wow-deck/launch.log`. Behaviour is tunable
through `WOW_DECK_GAME_TARGET`, `WOW_DECK_EXTRA_TARGETS`, `WOW_DECK_IDLE_TARGET` and
`WOW_DECK_PROFILE`.

## Files written

| Path | Owner | Content |
|---|---|---|
| `~/.local/share/wow-deck/app/` | user | The application |
| `~/.local/bin/wow-deck` | user | Symlink to the entry point |
| `~/.local/bin/wow-deck-launch.sh` | user | Launch wrapper |
| `~/.local/share/wow-deck/wow-deck-edge.yaml` | user | InputPlumber profile |
| `~/.local/share/wow-deck/env.conf` | user | Optional overrides for the wrapper |
| `~/.config/environment.d/50-wow-deck.conf` | user | Steam-side SDL ignore list |
| `~/.local/share/applications/org.consoleport.wowdeck.desktop` (+ Desktop copy) | user | Launcher |
| `~/.local/share/icons/hicolor/256x256/apps/org.consoleport.wowdeck.png` | user | Icon |
| `<WoW>/WTF/GamePadConfig_SteamDeck.json` | user | Paddle order, Steam button unbound |
| `<WoW>/Interface/AddOns/*` | user | Addons, recorded in `state.json` for exact removal |
| `~/Applications/CurseForge.AppImage`, `~/.local/share/applications/curseforge.desktop`, `~/World of Warcraft` symlink | user | CurseForge |
| `/etc/inputplumber/devices.d/50-steam_deck.yaml` | root | InputPlumber Deck override |
| `/etc/atomic-update.conf.d/wow-deck.conf` | root | Keep-list |
| Steam: `shortcuts.vdf`, `config.vdf`, `grid/` | user, Steam closed | Shortcut, Proton mapping, artwork |

Uninstall removes all of the above (`uninstall --all`, or the hub's Uninstall button) except
Battle.net, its Steam shortcut and the game itself.

## Front ends

The flow code calls a small dialog interface (`info`, `error`, `yesno`, `password`,
`checklist`, `menu`, `note`, `textbox`). `gtkui.py` replaces those functions with GTK4
dialogs that are safe to call from a worker thread, so the same flow runs under the touch UI
and under the kdialog/zenity fallback (`wow-deck hub --text`) without changes. The hub window
runs long operations in a worker thread and streams their output into a log view.

## Verification

`wow-deck doctor` checks every layer: SteamOS version, session type, InputPlumber state and
current targets, root files, wrapper, Proton versions, the Battle.net shortcut (launch options,
Steam Input flag, Proton mapping), whether the running Steam ignores the emulated Edge, and
the WoW config in every installation.

Tests (`python3 -m pytest tests`) cover the VDF codec, shortcut and flag round trips on fixture
copies of real Steam files, addon extraction safety, CurseForge registration, the self-update
version logic and CLI dispatch.
