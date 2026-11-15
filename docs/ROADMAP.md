# RumbleManiaSlop: things wanted later

Notes on work that is planned but not started, so the reasons are not lost.

## The level editor: what it does not do yet

The editor exists (`editor.cmd`; `docs\MANIA.md`, "Missions, menu pictures and the editor"): per stage the Golden
Banana, the mission time and banana count; per world the missions switch and the Rumble world whose graphics it
borrows; stage and world thumbnails come from Banana Mania by themselves. Still wished for:

* **Placing a banana anywhere**, not only turning one of the stage's own into the golden one (every imported
  stage has at least one banana, so each can have a Golden Banana today).
* **A title card of one's own.** Uploaded pictures exist for the stage thumbnail and a world's small picture,
  big picture and icon; the title card when a stage loads is a timeline asset of a Rumble world
  (`Course.BeginningTitle`), not a picture, and can only be borrowed or left out.
* **Intro cameras.** Imported stages now open with Banana Mania's own intro camera, computed from the stage as
  Mania does (`docs\MANIA.md` "The intro"). Still possible: a per-stage override in the editor (start distance,
  heading) for stages where Mania's formula starts outside the scenery (Wormhole).
* Moving stage parts are shown at rest, and the view has no collision or play test.

## Smaller things

* A seesaw inside another seesaw (three stages) is left out; green and red goals do not skip stages.
* Banana Mania's particle effects in backgrounds (rain, snow, sparks) and its screen effects.
* The belt texture of conveyors does not scroll; the switch models do not move when pressed.
* Goal colours: Mania's green and red goals skip stages; here every goal ends the stage.
