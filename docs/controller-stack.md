# Controller stack: how the back grips reach World of Warcraft

This document explains why the Steam Deck's back grips (L4, L5, R4, R5) cannot reach WoW as
gamepad buttons on a stock SteamOS installation, and how wow-deck makes them arrive as native
`PADPADDLE1-4` without modifying the game, Proton or Steam.

## How WoW reads gamepads

WoW's gamepad layer is a statically linked SDL2 (fingerprint 2.26 to 2.28, inferred from the
hint strings present in `Wow.exe`). Relevant properties of that build:

- HIDAPI drivers present: PS3, PS4, PS5 (including the DualSense Edge), Xbox 360, Xbox One,
  Switch, Wii, Luna, Stadia, Shield, Steam Controller. There is **no Steam Deck HIDAPI driver**
  (`SDL_JOYSTICK_HIDAPI_STEAMDECK` arrived in SDL 2.30).
- SDL hints are read from the environment; Wine copies Linux `SDL_*` variables into the Win32
  environment verbatim, so `SDL_GAMECONTROLLER_IGNORE_DEVICES` and friends reach the game.
- Two mapping layers are exposed to Lua (`GamePadDocumentation.lua`): an SDL mapping layer
  (`C_GamePad.AddSDLMapping`) and WoW's own config layer (`C_GamePad.GetConfig / SetConfig /
  ApplyConfigs`, keyed by vendor and product id, with `rawButtonMappings[rawIndex] ->
  'PADPADDLE1'` etc.). `GetDeviceRawState` exposes every raw button regardless of mapping.
- Binding names include `PADPADDLE1-4`, `PADSYSTEM` (Guide), `PADSOCIAL`, and the usual face,
  shoulder, trigger and stick names. The console command `GamePadListDevices` lists devices
  with vendor/product ids and raw counts.
- SDL2's HIDAPI PS5 driver exposes the Edge paddles as controller slots 16 to 19 and WoW's
  built-in mapping binds them to `PADPADDLE1-4`. In SDL's order slot 16 is R5, 17 is L5, 18 is
  R4 and 19 is L4.

A DualSense Edge on Windows therefore delivers all four paddles to WoW natively. The task is
to make the Deck look like one to the game.

## Where the grips are lost on a stock Deck

```
Deck controller (hidraw 28DE:1205, interface 2)
  -> Steam (owns the hidraw node, lizard mode off)
  -> uinput "Microsoft X-Box 360 pad" 28DE:11FF          (11 buttons, hard cap)
  -> winebus evdev backend -> fixed 11-button HID -> xinput1_3
  -> WoW SDL2 XInput/RawInput -> "Steam Virtual Gamepad"
  -> PAD1..PADRSTICK only; the grips can only be emulated keyboard keys
```

Steam Input always emulates an Xbox controller on Linux (Steamworks documentation), and the
kernel `hid-steam` driver removes the controller's own evdev node while Steam holds the hidraw
interface. Disabling Steam Input per shortcut does not help: the controller then looks
disconnected to the game.

### Proton / Wine input backends

`winebus.sys` presents Linux input devices to Windows through one of three backends. The
backend decides how many buttons survive.

| Backend | When used | What WoW's SDL sees | Paddles |
|---|---|---|---|
| hidraw passthrough | Device on the default allowlist (DS4, DualSense 054C:0CE6, **DualSense Edge 054C:0DF2**, Steam Controller, sim hardware), or `PROTON_ENABLE_HIDRAW`, or any non-gamepad HID usage | The real HID report descriptor, verbatim | Yes |
| SDL backend, `Map Controllers=1` (default) | Any device SDL calls a game controller, when hidraw is refused | Fixed Xbox-style descriptor: 6 axes, 1 hat, 11 wired buttons; MISC1, PADDLE1-4 and TOUCHPAD are dropped | No |
| SDL backend, `Map Controllers=0` | Registry `HKLM\System\CurrentControlSet\Services\winebus` | Generic joystick with every raw SDL button, DirectInput-shaped | Raw only |
| evdev | The Steam Input virtual pad 28DE:11FF; other evdev devices only when the SDL backend is off | Same fixed descriptor, capped to 11 buttons when a hat exists | No |

Further constraints found while testing:

- Steam writes the vendor/product ids of every controller it handles into
  `SDL_GAMECONTROLLER_IGNORE_DEVICES` for the game; winebus honours that list for hidraw too, so
  a device Steam manages vanishes from Wine entirely.
- Wine's `winexinput.sys` splits any device with six axes and at least fourteen buttons into an
  XInput-shaped `&IG_` child and an `&XI_` child; dinput hands games the `IG_` child, which
  carries no paddle data. Even with the `override` registry switch the extra buttons of the
  Xbox 360 / Xbox Elite uinput targets never toggled in WoW.
- `hidclass.sys` (Proton 10.0-4b) crashes on the HORIPAD Steam descriptor when it arrives over
  hidraw, taking winebus down with it.
- pressure-vessel (the Steam Linux Runtime container) bind-mounts `/dev` and `/run/udev`, so
  hidraw, uinput and uhid are reachable with host permissions.

## The design

```
Deck controller (hidraw 28DE:1205, interface 2)
  -> InputPlumber (root; hides the physical nodes, lizard mode off)
     +-> /dev/uhid "Steam Deck controller" 28DE:1205  -> Steam       (Steam button, "..." menu,
     |                                                                Steam+X, trackpad layout)
     +-> /dev/uhid "DualSense Edge" 054C:0DF2          -> winebus hidraw passthrough
                                                       -> WoW SDL2 HIDAPI PS5 driver
                                                       -> PADPADDLE1-4 native
```

[InputPlumber](https://github.com/ShadowBlip/InputPlumber) ships with SteamOS 3.7 and newer
(disabled by default). It reads the Deck controller from hidraw, hides the physical
`js*|event*|hidraw*` nodes from everyone else via generated udev rules, and emits one or more
virtual *target* devices. wow-deck enables it with an override configuration whose idle target
is `deck-uhid`, a virtual Steam Deck controller that Steam treats as the real thing.

While WoW runs, the launch wrapper switches the composite device to two targets, `ds5-edge`
and `deck-uhid`. InputPlumber writes every input event to every target that declares the
capability, so both virtual controllers carry the full input. Each consumer then reads the one
it understands:

- **Steam** reads the virtual Deck controller. Its own chords, menus, keyboard and the game's
  Steam Input layout (trackpads as mouse, for example) behave exactly as stock.
- **WoW** reads the Edge over hidraw. Every button plus the four paddles arrive natively.

Two ignore lists keep the consumers apart:

- The game must ignore Steam's virtual Xbox pad. The wrapper rewrites
  `SDL_GAMECONTROLLER_IGNORE_DEVICES` for the game: it removes the Edge (Steam may have listed it)
  and adds Steam's virtual pad, `0x28de/0x11ff`. Both winebus and WoW's SDL honour the list.
- Steam must not open the Edge, otherwise it sees two controllers and every Steam-side input
  fires twice. Steam's `controller_blacklist` key and its PlayStation-support settings do not
  achieve this (Steam still opens the device for its own UI). What works is
  `SDL_GAMECONTROLLER_IGNORE_DEVICES=0x054c/0x0df2` in **Steam's own environment**: Steam's
  SDL layer still enumerates the device but Steam Input never opens it, and the hidraw node stays
  available to Wine. See [steamos-integration.md](steamos-integration.md) for where that
  variable lives.

Target switches happen only at launch and after exit. Changing InputPlumber targets under a
running Proton game crashes winebus (`winexinput` invalid handle), so any configuration change
takes effect at the next launch.

## WoW-side configuration

WoW loads `WTF/GamePadConfig_*.json` at startup (alphabetically, after `_Default`, before
`_Addons`). wow-deck writes `GamePadConfig_SteamDeck.json` for vendor 1356 / product 3570:

- Raw buttons 19, 18, 17, 16 map to `PADPADDLE1..4`, giving Deck order L4 = 1, R4 = 2,
  L5 = 3, R5 = 4 instead of SDL's Edge order.
- Raw button 5 (the PS button, i.e. the Steam button) is left unbound so it does not reach the
  game as `PADSYSTEM`.
- Label style is `Letters`.

Mappings from the file layer are honoured. The device *name* from the file is not: the mapped
name stays SDL's "DualSense Edge Wireless Controller", and `C_GamePad.GetConfig` returns nil
for file-layer configs. Renaming needs a runtime `C_GamePad.SetConfig` call from an addon.

## Why the DualSense Edge, and not an honest device

Every non-Sony route was tried and each fails inside a layer wow-deck does not own:

| Candidate | Outcome |
|---|---|
| InputPlumber `unified-gamepad`, `8bitdo-u2` | Vendor-opaque HID reports; WoW's SDL has no driver for them |
| InputPlumber `xbox-elite`, `xb360` (uinput) | All buttons declared, but the paddle bits never toggle in WoW: Wine's winexinput/dinput split strips them |
| InputPlumber `hori-steam` over hidraw | Wine's `hidclass.sys` crashes on the descriptor; winebus goes down |
| `hori-steam` without hidraw, `Map Controllers=0` | winebus's own SDL HIDAPI driver claims the device; only slots 0 to 14 arrive, and Steam treats it as a Steam Controller |
| Steam Input | Xbox-only emulation, 11-button cap by design |
| Keyboard emulation (F1-F4) | Works, but not native: collides with keyboard chords and offers no modifiers on the grips |

The Edge is the one device that WoW's own SDL has a driver for *and* that Proton passes through
raw by default, which sidesteps Wine's gamepad rewrite entirely and mirrors how a real Edge
works on Windows. The truly correct fix would be an SDL 2.30+ build of the client (direct Steam
Deck support over hidraw, no emulation), or per-target profiles in InputPlumber (see below).

## Known limitations

- **Chord leakage.** WoW reads the Edge as raw hardware, so the second key of a Steam chord
  (the X in Steam+X) also reaches the game as a tap. InputPlumber's DualSense target hard-codes
  the Deck's Quick Access button ("...") as PS+Cross, so it reaches WoW as an A tap. Profiles
  apply before the fan-out to targets and cannot drop an event for one target only; the
  InputPlumber source carries a TODO for "target device profiles" that would allow this.
- **Right trackpad touches also reach the Edge touchpad.** Harmless unless WoW's touchpad cursor
  is enabled (`GamePadTouchCursorEnable`, off by default).
- **Real DualSense Edge controllers** are ignored by Steam Input while the paddle mapping is
  installed, because the ignore list matches on vendor/product id.
- **Motion sensors.** Managing the Deck with InputPlumber removes the "Steam Deck Motion
  Sensors" evdev device and does not re-expose the IMU (InputPlumber issue #433).
- **Keyboard source.** InputPlumber's shipped Deck configuration also claims the internal AT
  keyboard, which interferes with `steamos-powerbuttond`; the override drops that source.
