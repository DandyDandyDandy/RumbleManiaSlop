# RumbleManiaSlop

Super Monkey Ball Banana Rumble as a native Windows game, built on your PC from your own Switch copy, with the
stages, music and classic characters of Super Monkey Ball Banana Mania imported from your own Steam copy.

**What it adds to [RumbleSlop](https://github.com/DandyDandyDandy/RumbleSlop)** (which already brings the PC
features: any resolution, high frame rates, keyboard and mouse, controllers, online play, your DLC)

- Banana Mania's 365 goal stages as 21 extra Adventure worlds (SMB1, SMB2 story and challenge, Deluxe, Reverse
  and more), all open from the start
- Banana Mania's stage music, or the original games' music with the Classic Soundtrack add-on
- The classic monkeys as a "Classic Outfit" for AiAi, MeeMee, Baby, GonGon, YanYan and Doctor
- Ball physics switchable between Rumble and Mania; Spin Dash can be turned off
- Every world and stage open from the start, Banana Rumble's own too
- Skip Stage in Adventure, also in split screen and online
- Co-op and online play on the imported worlds

This is a fork of RumbleSlop, which is the PC port on its own. It is called Slop because it is vibecoded slop: the
port and the importer were written by an AI coding agent. Expect rough edges.

> **No game files are in this repository, and none may be added.** You need your own copy of Banana Rumble,
> dumped from your own console (the base game and the 2.2.0 update), and, for the import, your own Steam install of
> Banana Mania. The setup builds the game on your machine from your files, so the result contains both games'
> content. It is for your own use. Do not share it.
>
> Not affiliated with or endorsed by SEGA, Nintendo, Valve, Unity or CRI Middleware.

## The additions in detail

Everything RumbleSlop does (display options, wide screens, keyboard and mouse, controller glyphs, online play by
room code, also over Steam's relay network), plus, when Banana Mania is installed:

- **Banana Mania's 365 goal stages in Adventure mode**, as 21 extra worlds under a *Mania* tab of *Select World*:
  Super Monkey Ball 1 (Beginner, Advanced, Expert, each followed by its Extra floors, Master), the ten story worlds of Super
  Monkey Ball 2, its challenge difficulties, Deluxe, Original Stage Mode and Reverse Mode. They are played with Rumble's ball, physics, goal, camera and rules; every stage is open from the start.
- **Banana Mania's stage music** on those stages, and the original games' music when your Banana Mania has the
  Classic Soundtrack add-on (*Options > Audio > Imported Stage Music*).
- **Skip Stage.** In Adventure the pause menu can leave a stage for the next one: *Help Menu > Skip Stage* in
  single player (straight to the next stage, nothing recorded), *Skip Stage* in the menu of split screen and of
  an online room (the host's choice; the stage ends for everybody and the result screen follows).
- **Spin Dash on or off.** Banana Mania's stages were made for a ball without it: *Options > General > Spin Dash
  (Single Player)* for single player, and a *Spin Dash* choice under *Ball Collision* on the game settings screen
  of multiplayer Adventure (split screen and online; online the host's choice holds for the room). Battle modes
  always have it.
- **Ball Physics: Rumble or Mania.** Mania gives the ball Banana Mania's gravity, bounce, friction and tilt values
  and no top speed, so it rolls and speeds up as in Mania (Coaster: about 375 km/h before the ball leaves the track,
  as in Mania; Rumble's physics stop at 144). Rows in the same places as Spin Dash (*Options > General > Ball Physics
  (Single Player)*, a *Ball Physics* choice on the multiplayer game settings screen). Battle modes keep Rumble's.
- **The classic monkeys** of the Classic Character Pack as the "Classic Outfit" in *Style > Outfit*, for AiAi,
  MeeMee, Baby, GonGon, YanYan and Doctor (needs that pack in your Banana Mania).
- Co-op with the imported worlds. Online, a room only accepts players whose game has the same imported worlds:
  everyone needs RumbleManiaSlop with the import. A RumbleManiaSlop without imported stages plays with RumbleSlop.

Each part can be left out (see `input\README.txt`), and without Banana Mania the fork builds the same game as
RumbleSlop.

## What you need

- Everything RumbleSlop needs: Windows 10 or 11 (64-bit), a CPU with AVX2, a GPU with Vulkan,
  [Python](https://www.python.org/downloads/windows/) 3.10 or newer, about 15 GB free besides your game files (6 GB after `setup.cmd --clean`), and
  your own `prod.keys`, base game (`.xci` or `.nsp`) and 2.2.0 update (`.nsp`), and optionally your add-on
  content (DLC) as `.nsp` files.
- Super Monkey Ball Banana Mania installed through Steam (about 1 GB more disk space for the import). The setup
  finds it by itself; if it does not, name its folder in `input\mania.txt`.

## Setup (once)

1. Download or clone this repository.
2. Put your Banana Rumble files into the `input` folder: `prod.keys`, the base game, the 2.2.0 update and any
   add-on content `.nsp` files. The file names do not matter.
3. Double-click `setup.cmd`. It builds the game (15 to 30 minutes) and then imports Banana Mania (a few minutes).
4. Start `game\RumbleManiaSlop.exe`.

Afterwards `build` and the files in `input` are not needed (`setup.cmd --clean`). Banana Mania can be uninstalled
too: the imported stages are in `game\mania`. Deleting that folder turns the game back into plain Banana Rumble;
`setup.cmd --only mania` makes it again.

Add-on content bought later: put its `.nsp` files and `prod.keys` into `input` and run `setup.cmd --only dlc`
(the base game and update are not needed for this).

## Logs

The game writes no log files when playing. If it does not start or misbehaves, run `RumbleManiaSlop.exe --log`
(from a command prompt in the `game` folder, or add `--log` to a shortcut's launch options): it then writes
`game\port.log` and `game\player.log`. If the game stops with an error or freezes, it always leaves `port.log`
with a report.
## For developers

- [docs/TECHNICAL.md](docs/TECHNICAL.md): how the port works (shared with RumbleSlop).
- [docs/MANIA.md](docs/MANIA.md): both games' stage data, the conversion, the hooks, the test tool.
- [docs/COSTUMES.md](docs/COSTUMES.md): characters and costumes, the Classic Outfit.
- `editor.cmd`: the level editor the mod's Golden Bananas, world looks and stage pictures were made with
  (`mania\overrides.json`, `mania\pictures`); see docs/MANIA.md, "Missions, menu pictures and the editor".

`upstream` in this clone is RumbleSlop; port fixes belong there and are merged here.

## Credits and licences

As RumbleSlop: MIT for this repository's own code ([LICENSE](LICENSE)), third-party parts in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Super Monkey Ball Banana Rumble and Banana Mania are (c) SEGA;
nothing of either is in this repository.
That the characters which can no longer be bought or earned only need
their unlock rule changed was found by iswimfly ([Delisted Character Fix](https://gamebanana.com/mods/690229));
the port gives them to every save in its own way and includes nothing of that mod.
