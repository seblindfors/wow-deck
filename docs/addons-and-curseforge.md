# Addons and CurseForge

## Addon sources

Addons are installed from their public release channels and recorded so they can be removed
exactly:

| Addon | Source |
|---|---|
| ConsolePort (all modules) | Latest GitHub release asset |
| BugSack | Latest GitHub release asset |
| !BugGrabber | CurseForge public download endpoint (`/api/v1/mods/<id>/files/<fileId>/download`), file id resolved via cfwidget |

Archives are extracted into `Interface/AddOns` of every WoW flavour found, with path
traversal ("zip-slip") rejected. The top-level folders created by each archive are written to
`state.json`, and removal deletes exactly those folders.

## CurseForge desktop app

The CurseForge app is delivered as an AppImage (`curseforge-latest-linux.zip` from Overwolf).
That archive can lag behind the current release; the app updates itself in place on first
launch through its embedded updater, so the AppImage must live in a writable user path
(`~/Applications/CurseForge.AppImage`). A desktop entry is written next to it.

The app finds game installations through
`~/.config/CurseForge/agent/GameInstances/AddonGameInstance.json`. wow-deck pre-registers
each WoW flavour it finds (retail `gameVersionTypeId` 517, Classic Era 67408), pointing at a
`~/World of Warcraft` symlink into the Proton prefix, so the app knows the game on first launch
and can manage the addons installed above. Registration is skipped while the app is running,
because it rewrites the file on exit.
