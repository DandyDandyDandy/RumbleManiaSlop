# RumbleManiaSlop

Super Monkey Ball Banana Rumble as a native Windows game, built on your PC from your own Switch copy, with the
stages, music and classic characters of Super Monkey Ball Banana Mania imported from your own Steam copy.

This is a fork of RumbleSlop, which is the PC port on its own. It is called Slop because it is vibecoded slop: the
port and the importer were written by an AI coding agent. Expect rough edges.

> **No game files are in this repository, and none may be added.** You need your own copy of Banana Rumble,
> dumped from your own console (the base game and the 2.0.0 update), and, for the import, your own Steam install of
> Banana Mania. The setup builds the game on your machine from your files, so the result contains both games'
> content. It is for your own use. Do not share it.
>
> Not affiliated with or endorsed by SEGA, Nintendo, Valve, Unity or CRI Middleware.

## What the fork adds

Everything RumbleSlop does (display options, wide screens, keyboard and mouse, controller glyphs, online play by
room code), plus, when Banana Mania is installed:

- **All 410 Banana Mania stages in Adventure mode**, as 29 extra worlds after Rumble's own in *Select World*:
  Super Monkey Ball 1 (Beginner, Advanced, Expert, their Extra floors, Master), the ten story worlds of Super
  Monkey Ball 2, its challenge difficulties, Deluxe, Original Stage Mode, Reverse Mode and the remaining special
  stages. They are played with Rumble's ball, physics, goal, camera and rules; every stage is open from the start.
- **Banana Mania's stage music** on those stages.
- **The classic monkeys** of the Classic Character Pack as the "Classic Outfit" in *Style > Outfit*, for AiAi,
  MeeMee, Baby, GonGon, YanYan and Doctor (needs that pack in your Banana Mania).
- Co-op with the imported worlds. Online, a room only accepts players whose game has the same imported worlds:
  everyone needs RumbleManiaSlop with the import. A RumbleManiaSlop without imported stages plays with RumbleSlop.

Each part can be left out (see `input\README.txt`), and without Banana Mania the fork builds the same game as
RumbleSlop.

## What you need

- Everything RumbleSlop needs: Windows 10 or 11 (64-bit), a CPU with AVX2, a GPU with Vulkan,
  [Python](https://www.python.org/downloads/windows/) 3.10 or newer, about 25 GB free while the setup runs, and
  your own `prod.keys`, base game (`.xci` or `.nsp`) and 2.0.0 update (`.nsp`).
- Super Monkey Ball Banana Mania installed through Steam (about 1 GB more disk space for the import). The setup
  finds it by itself; if it does not, name its folder in `input\mania.txt`.

## Setup (once)

1. Download or clone this repository.
2. Put your Banana Rumble files into the `input` folder.
3. Double-click `setup.cmd`. It builds the game (30 to 60 minutes) and then imports Banana Mania (a few minutes).
4. Start `game\RumbleManiaSlop.exe`.

Afterwards `build` and the files in `input` are not needed (`setup.cmd --clean`). Banana Mania can be uninstalled
too: the imported stages are in `game\mania`. Deleting that folder turns the game back into plain Banana Rumble;
`setup.cmd --only mania` makes it again.

## Known problems

Those of RumbleSlop, and for the imported stages:

- Wormholes do not teleport (17 stages), the two stages with sliding blocks ("jamabars") have them standing
  still, and the wave bonus stage does not wave. Switches, bumpers, seesaws, conveyors and moving parts work.
- Every goal is Rumble's goal and ends the stage; green and red warp goals do not skip stages.
- Stages borrow the scenery, lighting and sky of a Rumble world, not Banana Mania's backgrounds, and are drawn
  with Rumble's stage shaders: colours and materials differ from the original, vertex colouring is lost.
- No stage pictures in *Select Stage*, no missions, no rankings for the imported worlds.
- Only a sample of the 410 stages has been started in the game; see `docs\MANIA.md` for what was checked.
- The Classic Outfit's face does not blink, and other body items do not show while it is worn.

## For developers

- [docs/TECHNICAL.md](docs/TECHNICAL.md): how the port works (shared with RumbleSlop).
- [docs/MANIA.md](docs/MANIA.md): both games' stage data, the conversion, the hooks, the test tool.
- [docs/COSTUMES.md](docs/COSTUMES.md): characters and costumes, the Classic Outfit.

`upstream` in this clone is RumbleSlop; port fixes belong there and are merged here.

## Credits and licences

As RumbleSlop: MIT for this repository's own code ([LICENSE](LICENSE)), third-party parts in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Super Monkey Ball Banana Rumble and Banana Mania are (c) SEGA;
nothing of either is in this repository.
That the characters which can no longer be bought or earned only need
their unlock rule changed was found by iswimfly ([Delisted Character Fix](https://gamebanana.com/mods/690229));
the port gives them to every save in its own way and includes nothing of that mod.
