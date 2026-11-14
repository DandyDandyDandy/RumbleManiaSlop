# RumbleManiaSlop: things wanted later

Notes on work that is planned but not started, so the reasons are not lost. Nothing here exists yet.

## A level viewer / editor for the imported stages (low priority)

Banana Mania's stages come without several things Rumble's stages have, and the import can only guess or leave
them out. A quick and easy tool should let a person set them per stage and per world:

* **Challenge / bonus bananas.** Rumble's stages have the special bananas of its missions; Mania's have none. The
  tool shows a stage (top view and a free camera are enough) and lets them be placed.
* **Challenge time and clear time** of each stage (Rumble's time missions; today every imported stage has 60 or 30
  seconds and no missions).
* **Stage thumbnails** for *Select Stage* (today: "no image").
* **World icons**: an image per imported world, uploaded by the user.
* **The Rumble theme of a world**: not the sky box, but the graphics around a world and a stage when they load
  (the world's title card, the stage intro banner, the brochure picture in *Select World*). Mania has nothing of
  the kind, so each imported world has to reuse one of Rumble's sets or hide them.
* **Intro cameras.** The fly-over before a stage is one box and two camera points per stage
  (`BeginningBounds`, see `docs\MANIA.md`); the import derives the box from the stage's size. Stages where that
  looks wrong need a way to move the two points by hand.

Shape (a suggestion): one HTML file written by a script, like the classic characters' hand poser
(`mania\classic\make_hand_poser.py`), reading the stage geometry the import already has, and saving one JSON file
of overrides that `mania\build.py` reads (`mania\overrides.json`: per stage bananas, times, thumbnail, intro
points; per world icon and theme). Whatever per-stage data the import gains before the tool exists should already
come from such a file, so the tool only has to write it.

## Smaller things

* Wormholes (17 stages), the two stages with sliding blocks: still without function.
* Banana Mania's particle effects in backgrounds (rain, snow, sparks) and its screen effects.
* The belt texture of conveyors does not scroll; the switch models do not move when pressed.
* Goal colours: Mania's green and red goals skip stages; here every goal ends the stage.
