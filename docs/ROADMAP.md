# RumbleManiaSlop: things wanted later

Notes on work that is planned but not started, so the reasons are not lost.

## The level editor: what it does not do yet

The editor exists (`editor.cmd`; `docs\MANIA.md`, "Missions, menu pictures and the editor"): per stage the Golden
Banana, the mission time and banana count; per world the missions switch and the Rumble world whose graphics it
borrows; stage and world thumbnails come from Banana Mania by themselves. Still wished for:

* **Placing a banana anywhere**, not only turning one of the stage's own into the golden one (every imported
  stage has at least one banana, so each can have a Golden Banana today).
* **Pictures of one's own**: a stage thumbnail taken from the editor's view, an uploaded world picture or icon
  (`mania\sprites.py` can already add a picture to the game; they would have to live outside the repository).
* **Intro cameras.** The fly-over before a stage is one box and two camera points per stage
  (`BeginningBounds`, see `docs\MANIA.md`); the import derives the box from the stage's size. Stages where that
  looks wrong need a way to move the two points by hand.
* Moving stage parts are shown at rest, and the view has no collision or play test.

## Smaller things

* A seesaw inside another seesaw (three stages) is left out; green and red goals do not skip stages.
* Banana Mania's particle effects in backgrounds (rain, snow, sparks) and its screen effects.
* The belt texture of conveyors does not scroll; the switch models do not move when pressed.
* Goal colours: Mania's green and red goals skip stages; here every goal ends the stage.
