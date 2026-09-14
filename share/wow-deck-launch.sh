#!/bin/bash
# wow-deck-launch.sh — Steam launch-option wrapper for the Battle.net/WoW shortcut.
#   Launch options:  /home/deck/.local/bin/wow-deck-launch.sh %command%
#
# While the game runs, InputPlumber presents the Deck controller twice: as a DualSense Edge
# (ds5-edge) that WoW reads directly over hidraw for native PADPADDLE1-4, and as a virtual
# Steam Deck controller (deck-uhid) that Steam keeps for its own button, menus, keyboard
# chord and the game's Steam Input layout. Steam ignores the Edge because the paddles component
# puts it in Steam's own SDL_GAMECONTROLLER_IGNORE_DEVICES (~/.config/environment.d); the game
# ignores Steam's virtual Xbox pad via the rewritten ignore list below. When the game exits only the Steam Deck target remains.
# Requires: InputPlumber managing the Deck (see /etc/inputplumber/devices.d).

BASE=/home/deck/.local/share/wow-deck
LOG=$BASE/launch.log
CONF=$BASE/env.conf
GAME_TARGET="${WOW_DECK_GAME_TARGET:-ds5-edge}"     # plus WOW_DECK_EXTRA_TARGETS (default: deck-uhid, for Steam)
EXTRA_TARGETS="${WOW_DECK_EXTRA_TARGETS-deck-uhid}"
IDLE_TARGET="${WOW_DECK_IDLE_TARGET:-deck-uhid}"
PROFILE="${WOW_DECK_PROFILE:-$BASE/wow-deck-edge.yaml}"   # InputPlumber profile (targets, no remaps)
DEFAULT_PROFILE=/usr/share/inputplumber/profiles/default.yaml
EDGE_ID="0003:0000054C:00000DF2"

log() { echo "$(date -Is) $*" >> "$LOG"; }
edge_present() { grep -qs "HID_ID=$EDGE_ID" /sys/class/hidraw/hidraw*/device/uevent; }

log "=== launch: $*"

# 1. Make sure InputPlumber is managing a composite device.
dev=$(inputplumber devices list 2>/dev/null | grep -oE "^│ [0-9]+" | head -1 | tr -dc 0-9)
if [ -z "$dev" ]; then
  log "no composite device; enabling management"
  inputplumber devices manage-all --enable >>"$LOG" 2>&1
  for _ in $(seq 1 20); do
    dev=$(inputplumber devices list 2>/dev/null | grep -oE "^│ [0-9]+" | head -1 | tr -dc 0-9)
    [ -n "$dev" ] && break; sleep 0.25
  done
fi
[ -z "$dev" ] && log "WARN: InputPlumber has no device; launching without controller switch"

# 2. Switch to the game target(s), load the game profile, wait for the Edge hidraw node so
#    winebus sees it at boot.
if [ -n "$dev" ]; then
  # shellcheck disable=SC2086
  inputplumber device "$dev" targets set $GAME_TARGET $EXTRA_TARGETS >>"$LOG" 2>&1
  [ -f "$PROFILE" ] && inputplumber device "$dev" profile load "$PROFILE" >>"$LOG" 2>&1 && log "profile loaded: $PROFILE"
  for _ in $(seq 1 40); do edge_present && break; sleep 0.25; done
  edge_present && log "edge present" || log "WARN: edge hidraw not seen after 10s"
  sleep 1  # let udev settle ACLs before Proton enumerates
fi

# 3. Environment. Steam Input stays at its default on this shortcut (Steam keyboard for the
#    Battle.net login and chat; trackpad layouts). Steam lists the controllers it handles in
#    SDL_GAMECONTROLLER_IGNORE_DEVICES and offers a virtual Xbox pad instead; winebus and WoW's
#    SDL both honour that list, so rewrite it: let the Edge (and DualSense) through even if Steam
#    was not told to ignore it, and hide Steam's virtual pad (28de:11ff).
ign="${SDL_GAMECONTROLLER_IGNORE_DEVICES:-}"
ign=$(printf '%s' "$ign" | tr ',' '\n' | grep -v -i -E '^0x054c/0x0df2$|^0x054c/0x0ce6$' | grep -v '^$' | paste -sd, -)
export SDL_GAMECONTROLLER_IGNORE_DEVICES="${ign:+$ign,}0x28de/0x11ff"
log "ignore-after:  $SDL_GAMECONTROLLER_IGNORE_DEVICES"
[ -f "$CONF" ] && set -a && . "$CONF" && set +a
env | grep -E "^(SDL_|PROTON_)" | sort >> "$LOG"

# 4. Run the game (foreground) and restore the idle target afterwards, whatever happens.
restore() {
  [ -n "$dev" ] && [ -f "$DEFAULT_PROFILE" ] && inputplumber device "$dev" profile load "$DEFAULT_PROFILE" >>"$LOG" 2>&1
  [ -n "$dev" ] && inputplumber device "$dev" targets set "$IDLE_TARGET" >>"$LOG" 2>&1
  log "=== exit: restored $IDLE_TARGET"
}
trap restore EXIT INT TERM
"$@"
