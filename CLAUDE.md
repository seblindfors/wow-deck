# wow-deck

One-button setup of World of Warcraft on a Steam Deck running stock SteamOS: Battle.net and the
Steam shortcut, native paddle (back grip) buttons via InputPlumber's DualSense Edge target,
ConsolePort and friends, CurseForge. Technical background lives in `docs/`
(`controller-stack.md`, `steamos-integration.md`, `architecture.md`, `addons-and-curseforge.md`).

## Conventions

- Python 3.11+ (SteamOS ships python3), **standard library only** on the Deck side. Steam's
  VDF formats are handled by the vendored `wowdeck/vdf.py`; no pip on the target.
- One entry point: `bin/wow-deck` (`hub`, `setup`, `doctor`, `install`, `uninstall [--all]`,
  `paddles on|off`, `curseforge`, `help`). Everything idempotent; every write prints what it did.
- Root writes go through a single `sudo` invocation of the same script (`--root-phase`), so
  the user sees one password prompt and the privileged code path stays small.
- Steam-owned files (`shortcuts.vdf`, `localconfig.vdf`, `config.vdf`) are only written with
  Steam closed; reading is always allowed. Never edit them from Game Mode.
- Never hot-swap the InputPlumber target while a Proton game is running.
- Never launch a live hub window on a user's Deck for screenshots without warning: its buttons
  are real.
- Tests: `python3 -m pytest tests` (fixtures are copies of real Steam files).
- Documentation in `docs/` is technical and impersonal: mechanisms, constraints and file
  formats, no iteration history or names.
