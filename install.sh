#!/bin/bash
# wow-deck one-line installer for SteamOS (run in Desktop Mode):
#   curl -fsSL <release-url>/install.sh | bash
# or from a local checkout/tarball:  WOW_DECK_SRC=/path/to/wow-deck ./install.sh
set -euo pipefail
DEST="$HOME/.local/share/wow-deck/app"
BIN="$HOME/.local/bin"
SRC="${WOW_DECK_SRC:-}"
URL="${WOW_DECK_URL:-https://github.com/seblindfors/wow-deck/releases/latest/download/wow-deck.tar.gz}"

mkdir -p "$DEST" "$BIN"
if [ -n "$SRC" ]; then
  echo "Installing from $SRC"
  rm -rf "$DEST"; mkdir -p "$DEST"
  tar --exclude=.git --exclude=tests -cf - -C "$SRC" . | tar xf - -C "$DEST"
else
  echo "Downloading $URL"
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "$URL" -o "$tmp/wow-deck.tar.gz"
  rm -rf "$DEST"; mkdir -p "$DEST"
  tar xzf "$tmp/wow-deck.tar.gz" -C "$DEST" --strip-components=1
fi
chmod +x "$DEST/bin/wow-deck"
ln -sfn "$DEST/bin/wow-deck" "$BIN/wow-deck"
# Desktop launcher (application menu + Desktop icon). The file is named after the GTK
# application id so KDE/Wayland can match the running window to it (window/taskbar icon).
APPID=org.consoleport.wowdeck
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
# Icon: absolute path (KDE loads it directly; a themed name can sit in Plasma's stale icon
# cache after a fresh install) plus a themed copy for anything that looks the app id up.
if [ -f "$DEST/share/branding/logo.png" ]; then
  cp "$DEST/share/branding/logo.png" "$HOME/.local/share/icons/hicolor/256x256/apps/$APPID.png"; ICON="$DEST/share/branding/logo.png"
else
  ICON=input-gaming
fi
sed -e "s|__BIN__|$BIN/wow-deck|" -e "s|__ICON__|$ICON|" "$DEST/share/wow-deck-setup.desktop" > "$HOME/.local/share/applications/$APPID.desktop"
rm -f "$HOME/.local/share/applications"/wow-deck{,-setup,-keyboard}.desktop "$HOME/Desktop"/wow-deck{,-setup,-keyboard}.desktop   # older names
[ -d "$HOME/Desktop" ] && cp "$HOME/.local/share/applications/$APPID.desktop" "$HOME/Desktop/" && chmod +x "$HOME/Desktop/$APPID.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: add $BIN to your PATH (SteamOS usually has it)";; esac
echo "wow-deck installed to $DEST (launcher: WoW Deck)"
echo
# With arguments: run the CLI verb given. Without: open the guided setup.
if [ $# -gt 0 ]; then exec "$BIN/wow-deck" "$@"; else exec "$BIN/wow-deck" hub; fi
