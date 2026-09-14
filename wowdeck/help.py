"""Help content for the hub, as structure rather than pre-wrapped text so each front end can
lay it out itself: the GTK hub renders headings and wrapping labels, the dialog fallback and
`wow-deck help` wrap it to the terminal width.

SECTIONS: list of (heading, intro, items). `intro` is a paragraph or ''. Each item is either
a plain paragraph (str, rendered as a bullet) or a (term, description) pair."""
from __future__ import annotations
import textwrap

Item = "str | tuple[str, str]"

SECTIONS: list[tuple[str, str, list]] = [
    ('What WoW Deck is',
     'WoW Deck turns a stock Steam Deck into a ready-to-play World of Warcraft handheld with '
     'ConsolePort. Pick the parts you want, press one button, log in to Battle.net in Game Mode, '
     'and the rest finishes on its own in the background. No terminal, no manual Steam edits, '
     'and everything it does can be undone.',
     []),
    ('The components',
     'These are the items on the "Set up / change components" checklist. Only Battle.net + WoW is '
     'required; everything else, including all addons, is optional. Ticked items get installed, '
     'unticked items get removed, so you can come back and change your mind.',
     [('Battle.net + World of Warcraft (required)',
       'Downloads the Battle.net installer, runs it under Proton in its own prefix and adds a '
       '"Battle.net" shortcut to Steam with artwork and a working Proton version. Then it hands '
       'you over to Game Mode, where Steam\'s on-screen keyboard works, to log in and install WoW. '
       'A background helper notices when WoW is installed and finishes the other components you ticked.'),
      ('Gamepad mapping with native paddle support',
       'Makes the four back grips (L4, L5, R4, R5) real, separately bindable buttons in WoW, '
       'without Steam Input tricks. While WoW runs, the Deck controller is presented twice: as a '
       'virtual Steam Deck controller for Steam, so the Steam button, the "..." menu, Steam+X and '
       'your trackpad layout keep working, and as a DualSense Edge that WoW reads directly for every '
       'button plus the paddles. In WoW the device is called "Steam Deck" and the grips map to '
       'L4 = Paddle 1, R4 = Paddle 2, L5 = Paddle 3, R5 = Paddle 4. This uses InputPlumber, which '
       'ships with SteamOS 3.7 and newer; enabling it is the one step that asks for your password.'),
      ('ConsolePort (optional addon)',
       'The gamepad interface for WoW, installed from its latest release. Skip it if you prefer to '
       'install addons yourself.'),
      ('BugGrabber + BugSack (optional addons)',
       'Catch Lua errors quietly, so an addon problem never blocks the screen.'),
      ('CurseForge for addon maintenance (optional)',
       'Installs the CurseForge desktop app and registers your WoW install in it, so you can keep '
       'addons updated later from "Open CurseForge". Not needed if you manage addons another way.')]),
    ('The other buttons', '',
     [('Check status', 'Checks every layer (SteamOS, InputPlumber, the Steam shortcut, the WoW config, '
                       'how Steam handles the controller) and reports OK, WARN or FAIL for each.'),
      ('Open CurseForge', 'Starts the CurseForge app if it is installed.'),
      ('Check for WoW Deck updates', 'Downloads and installs a newer WoW Deck release if there is one.'),
      ('Switch to Game Mode', 'Leaves the desktop and returns to the Steam Deck interface.')]),
    ('Good to know', '',
     ['Run the setup from Desktop Mode. The Battle.net login itself happens in Game Mode.',
      'The controller is only switched while WoW runs; the rest of the time the Deck behaves as stock.',
      'The second key of a Steam chord (the X in Steam+X, for example) still reaches WoW as a tap, and '
      'the "..." button reaches WoW as an A tap. That is a limit of the controller emulation.',
      'While the paddle mapping is installed, Steam ignores real DualSense Edge controllers.',
      'Everything can be removed with "wow-deck uninstall" in a terminal. The Steam shortcut and '
      'WoW itself stay.',
      'WoW Deck is part of the ConsolePort project: github.com/seblindfors/wow-deck']),
]


def render_text(width: int = 78) -> str:
    out = []
    for heading, intro, items in SECTIONS:
        out.append(heading.upper()); out.append('')
        if intro:
            out.append(textwrap.fill(intro, width)); out.append('')
        for it in items:
            if isinstance(it, tuple):
                term, desc = it
                out.append(f'  {term}')
                out.append(textwrap.fill(desc, width, initial_indent='      ', subsequent_indent='      '))
            else:
                out.append(textwrap.fill(it, width, initial_indent='  * ', subsequent_indent='    '))
            out.append('')
    return '\n'.join(out).rstrip() + '\n'
