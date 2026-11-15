# Importing Banana Mania into Banana Rumble: technical notes

RumbleManiaSlop is RumbleSlop plus an importer that takes two things out of a Steam install of Super Monkey Ball
Banana Mania and puts them into the built game:

* its stages, with their music, as extra courses of Adventure mode;
* the classic-style monkeys of its Classic Character Pack, as the "Classic Outfit" in the Style menu
  (`docs\COSTUMES.md` has that part's notes).

Nothing of Banana Mania is in this repository. The importer reads the user's own install at setup time and writes
into `game\mania\`, an override folder the port's runtime reads before the game's own asset folder. The game's
files are never changed; deleting `game\mania\` removes everything.

This file records what was found out about both games' stage data and how one is turned into the other. The
general description of the port is `docs\TECHNICAL.md`.

## Why this works at all

Banana Rumble's stage code is a descendant of Banana Mania's. Both have a stage root with a `MainGameStage`
component, collision as `CollisionStagePart` components pointing at `CollisionStageData` triangle sets, bananas
as empty transforms, a start transform, goals with `MgGoalColi`, and stage motion as an Animator whose states
are named `class<N>_<A>to<B>_<mode>`. Rumble's sound table even still lists Mania's cue `w01_jungle`. The
classes differ in their fields and in how a stage is packaged, but a Mania stage can be rewritten object by
object, and Rumble's own code then plays it: ball physics, collision, fall-out, goal, results, replays of the
stage clock. Nothing of Mania's code runs.

## Banana Mania's side

Unity 2020.2.7f1, Windows, IL2CPP. Asset bundles are in
`smbbm_Data\StreamingAssets\StandaloneWindows64\AssetBundles\` (1198 bundles, dependencies in
`asset_bundle_manifest.json` under `assetBundleInfoList`). **The bundles carry type trees**, so every object,
including the game's own MonoBehaviours, reads as a dict with UnityPy (`read_typetree`). The script classes are
not in the bundles; `mania\maniastage.py` recognises each by a field name only that class has (`SIGNATURES`).

### Tables (`mania\maniadata.py`)

The stage and course tables are MonoBehaviours **without** type trees in the player file
`smbbm_Data\sharedassets0.assets`; their classes are found through the MonoScript objects of
`globalgamemanagers.assets`. Strings are int length + bytes padded to four, lists an int count + elements, a bool
one byte padded to four. Each decoder stops exactly at the end of its object.

| Object | Content |
|---|---|
| `MgStageData` | 410 entries: `stageId`, prefab path, background name (`Smb1_Jungle`, ...), background-root path, kind (`Normal` / `Bonus`), `limitTimes` (empty, or 8 ints indexed by game mode), special light path, special BGM cue (`invalid` everywhere), thumbnail path, three guide-asset paths, `StageAnimationStartKindStr`, `ShiftAnimationStartFrame` |
| `MgCourseDatum` (42) | game kind, course name (`Smb1Org_Shokyu`, `Smb2_StoryWorld01`, ...), text reference (PPtr + key), thumbnail path, start / end movie ids, next course, then the stages: `{stageId, calibratedStageId, isHalfTime, isCheckPoint, [{goalKind, nextStep}]}` |
| `MgBgData` (21) | background name, background prefab, light prefab, light scene id, **BGM cue**, shimmer and screen-effect assets |

Stage names are in the bundle `text_common_<lang>` (de en es fr it ja ko zh zhs), asset `stagename_<lang>`, keys
`stagename_st<ID>`; course names in asset `maingame_<lang>` under the course's text key.

Stage ids: 1xxx Super Monkey Ball 1 (109), 2xxx Super Monkey Ball 2 (218), 3xxx Deluxe (46), 4xxx-9xxx special
and reverse-mode variants (37). Stages without `limitTimes` have 60 seconds; 54 stages carry 30.

### A stage bundle

`stage_<smb1|smb2>_<background>_st<ID>` holds the prefab `st<ID>` (plus a `BgRoot` prefab and three guide
assets). Textures are shared per background in `stage_<game>_<bg>_textures`; shaders are in the bundle `shader`.

```
st1001                      MainGameStage, StageGravity, StageMovObjManager [, MgStageSwitchManager, ...]
  Behavior                  GravityTilt. What is drawn:
    NOCOLI_STAGE1001/stage/st1001_01 ...   MeshFilter + MeshRenderer
    GOAL01                  MgGoalModel: the goal's model (party ball, tape)
  Collision                 Animator. What is played on, and the tree that is animated:
    NODISP_STAGE1001/colN   MeshFilter (a collision mesh) + CollisionStagePart -> CollisionStageData
    bananaset/bananaNN      BananaPos (m_Kind: 0 single, 1 bunch, 2 rotten, 3 golden)
    START                   empty transform: the ball's centre at the start (0.5 above the floor)
    GOAL01                  MgGoalColi (m_GoalKind: 1 blue, 2 green, 3 red) and the goal's own collision
    NODISP_FALL, RINGOUT    markers
    MOT_*                   animated groups
```

`MainGameStage` holds `m_behaviorTransform`, `m_collisionTransform`, `m_start`, `m_ringoutY` (the height below
which the ball has fallen out, -6 on stage 1001), `m_FalloutBounds` (a box), and lists of goals, bananas,
wormholes, seesaws, jamabars, collision parts.

There are no Unity colliders, rigid bodies or lights in a stage. Stage objects are on layer 17. The stage faces
the other way round from Rumble: the start and the goals face -Z.

### Collision

`CollisionStageData.part`:

```
triangle[]          pos, normal, rot (quaternion), flag, lpos[2] (Vector2), lnml[2] (Vector2), edgeIndices[3],
                    culling {pos, rad}
gridTriangleList    X[].Y[].Z[].indexList[]: the triangles near each cell of a regular grid
gridMin, intervalX/Y/Z, gridSizeX/Y/Z, culling {pos, rad}
```

A triangle is stored in a frame of its own: `pos` is the first corner, `rot` turns the frame into the stage
(z = the normal, x along the first edge), and `lpos` are the other two corners in that frame, so
corner 1 = `pos + rot * (lpos[0].x, 0, 0)` and corner 2 = `pos + rot * (lpos[1].x, lpos[1].y, 0)`. `lnml` are the
2D normals, in the frame, of the edge from corner 1 to corner 2 and of the edge from corner 2 back to `pos`.
`edgeIndices` gives each of the three edges an id, the same on both triangles that share it, and -1 where the
edge needs no collision test of its own (the two triangles are coplanar, or the edge is concave). The grid lists,
per cell, every triangle whose box reaches into the cell or comes within about two units of it.

The numbers were checked against the collision meshes (triangle i of the data is triangle i of the `colN` mesh)
and, for the meaning of each field, against Rumble's own stages, whose data has the same shape.

### Motion

The `Collision` object has an Animator with an AnimatorController named `st<ID>` or `st<ID>_classify`. 222 of
the 410 stages have real motion (the rest carry an empty one-second clip). A controller has **one layer and one
state per clip**, without transitions; the state's speed is a float parameter with the state's name (default 1
for the `play_*` clips). Clip names are `class<C>_<A>to<B>_<mode>` with mode `play_loop`, `play_once`,
`stop_loop`, `stop_once`; the class number is the switch class that controls the clip (`MgStageSwitch.m_ClassId`).

Clips are generic clips in muscle-clip form (`m_MuscleClip`, streamed curves baked at 30 keys a second), bound by
path hash: `genericBindings[].path` is the CRC-32 of the node's path below the Animator
(`MOT_STAGE005/merged_obj`), `attribute` 1 position, 2 rotation, 3 scale, 4 Euler angles.

Only the `Collision` tree is animated. Each animated node has a drawn twin at the same path under `Behavior`,
and the game copies the motion over at run time (`StageMovObjManager.m_info`, `MgTRSSync`).

### Music

`smbbm_Data\StreamingAssets\Sound\`: CRIWARE cue sheets, `<name>.acb` plus the streamed data `<name>.awb`
(HCA, 48 kHz stereo, not encrypted). A stage's BGM is its background's `bgmCueStr`, written
`<cue sheet>_<cue>`: `bgm_smb1_st1_st1` is cue `st1` of `bgm_smb1_st1.acb`. Sheets: `bgm_smb1_st1`..`st8`,
`bgm_smb1_stm`, `bgm_world1`..`world10`, `bgm_bonus`.

## Banana Rumble's side

Unity 2022.3.30f1. What follows was read from the game's files and code (`tools\cs.py`); offsets are NSO offsets
of game version 2.2.0.

### A stage is a scene

`aa\Switch\scene_<name>_scenes_all.bundle` holds two serialized files: the scene (`CAB-<hash>`) and its
`CAB-<hash>.sharedAssets` (meshes, materials, textures, clips, collision data), plus a `.resS` with mesh and
texture data. **The stage scene bundles carry type trees** (the database bundles do not), so the game's own
MonoBehaviours in them read and write as dicts.

World 1 Stage 1 (`bg_stg_w01_001`), the template the importer builds on:

```
bg_stg_w01_001                  MainGameStage
  bg_stg_w01_001
    bananaset/BANANA_001 ...    empty transforms (also FUSA_ = bunch, GOLDBANANA_)
    nocoli_st_w01_001/...       MeshFilter + MeshRenderer (materials from the world's material bundle)
    nodisp_st_w01_001/cam_h_col1   CollisionStagePart -> CollisionStageData (in sharedAssets)
  GuideArrows                   MgGuideArrowObject, arrow models
  bg_stg_w01_001_BeginningBounds/bounds   BeginningBounds: the box the intro camera flies around
  goal_arch                     CollisionSquare (the trigger), MgGoalColi, BoxCollider, CollisionGlobe
    obj_com_goal_arch_a         Animator, ReplayTracker, the arch's meshes and its own collision part
  START_NULL0                   empty transform on the ground, facing +Z
  checkpoint01                  MgCheckPointColi, CollisionBox
MainGameInitializer             MainGameInitializer
```

`MainGameStage` fields: `m_GoalColiList` (the `MgGoalColi` of each goal), `m_StartGO` (`{m_EntryList: [{m_Key:
"NULL", m_Value: [start objects]}]}`), `m_StageAnimators`, `m_StageSwitchControllers`, `m_JamabarList`,
`m_MeshColliders`, `m_UseRigidbody`, `m_MgGuideArrowObject`, `m_BeginningCameraBoundsArr`, `m_SafeBoxes`,
`m_GoalHuntEnableGoalArea`, `m_MeshBounds`, `m_FalloutBounds` (boxes: centre and half size), `m_RingoutY` (an
absolute height: -5 where the lowest floor is at -0.8, 5 where it is at 8), `m_BananaTransformList`
(`{transform, kind, isBotIgnore, isNoShadow}`; kind as in Mania).

`CollisionStagePart`: `isPhysical` 1, `isTrigger`, `isDynamic`, `priority` 0, `layerMask` 10, `isItem`,
`m_CollisionStage`, `m_CullingScale` 1. Moving parts are not marked dynamic: a part follows its transform.

`CollisionStageData.part` is Mania's with three changes: each triangle has `bounds {min, max}` in place of the
`culling` sphere, and the part has `bounds {min, max}` and `boundsOrient` (a 4x4 matrix: the box may be turned;
identity with an axis-aligned box is valid).

A stage with moving parts has an Animator (update mode 1, no avatar) and a `ReplayTracker` on each moving group,
and lists the Animators in `m_StageAnimators`. Their controllers have the same shape as Mania's: one state,
its speed a float parameter with the state's name.

The scenery is not in the stage scene: the stage row names four more scenes (far scenery, sky, effects,
lighting) that are loaded with it.

### Stage and course tables

Tables are MonoBehaviours without type trees, one per bundle (`mania\dbtable.py`; the formats and the catalog are
described in `docs\COSTUMES.md`, sections 3 and 4). Those that matter here:

| Table | Record |
|---|---|
| `Stage` (705 rows) | `Name` (text row), `SceneID`, `BaseID`, `BGSceneID`, `TimeLimit`, mission values, `CaptionText`, thumbnail sprites, `LightSceneID`, `MiniMapImageID`, `FarSceneID`, `SkySceneID`, `EffectSceneID`, checkpoint animation values, `ScreenEffectAssetRef`, `GoalCameraID`, `IsRailGround`, `StartCameraID`, the four scene ids and the effect for split screen, `AnimationType`, `AnimationSpeedMultiplier` |
| `Stage_Text_<lang>` | `Name`, `CaptionText` |
| `Stage_DoleDisposition` | per stage id: the sponsor logo under the start (read in `MainGameStage.Start` without a check). Imported stages get a row without a logo (`AssetRef` empty, `Num` 0, as seven of the game's own rows are): Mania's stages have their own start mark; this holds with Options > General > Dole Collaboration On too |
| `Stage_List` (40 rows) | a reference to a `Stage_List_Group_<name>` table |
| `Stage_List_Group_<name>` | the stages of one list: `StageID`, `NextStage[2]`, `StageListID`, `OverrideCourseID` |
| `Course` (27 rows) | `Name`, `StageListID`, `CategoryID`, `NextCourseID`, `PrevCourseID`, `SerialName`, sprites, texts, `BeginningTitle`, `ClearMainMissionID`, `AssistKind`, `IsEnabledCategory[7]`, `IsStageMissionEnabled` |
| `Course_Text_<lang>` | `Name`, `SerialName` ("W1"), `CaptionText`, `AdventureTimerText` |
| `MainGame_Story_Progress` | `CourseID`, `IsDefaultOpen`, `UnlockProgress[2]`, `StageIndex`, movie ids |
| `Sound_CueSheet`, `Sound_Cue` | cue sheet files; cue -> cue sheet and inner cue name |

How the game uses them (static analysis; the parts used by the importer were then confirmed in the game):

* **Select World** (`FlowCourseSelect.<SetupCourseSelect>d__19.MoveNext`, 0x46a17d0) lists the `Course` rows in
  display order whose `CategoryID` is 1, 4 or 6, that are unlocked (`PrevCourseID` 0 or its course cleared), under
  every game category whose `IsEnabledCategory` entry is set. Lists are `List<>`: no fixed count.
* **Select Stage** (`UIStateMainGameSelect.<SetupStageListFromCourse>d__5.MoveNext`, 0x46a7050) lists the
  course's stage list; numbering is `"{SerialName}-{index:00}"`; a missing thumbnail sprite (0) shows "no image".
* Record lists are as long as the data (`TableInstanceBase.ImportRecord`, 0x28c6bf0): course ids past 26 and
  stage ids past 704 work, and `GetRecord` of an unknown id returns an empty record instead of failing.
* **Save data** is a list of entries per course, made on first use (`AdventureParam.GetCourseParam`, 0x43c2d60),
  one stage entry per list item, each **locked**. A stage is opened by a `MainGame_Story_Progress` row with
  `IsDefaultOpen`. When a course's stage list changes, its save entry is reset on the next load.
* **Starting a stage** (`Util.GameScene.changeReqMainGameCore`, 0x4417780): the stage row's `SceneID` string
  becomes a value of the compiled enum `AppScene.eID` through a name dictionary
  (`EnumRuntimeHelper<T>.GetValue`, 0x2e6be10); the value's name is the Addressables key and must also be the
  scene's name. The far, effect, sky and light scenes of the row are loaded first.
* **Music** (`MainGameBg.calcBgCue`, 0x426a180) is the cue the background table names for the stage's far scene,
  by compiled cue name. Cue sheets are loaded by path (`Sound/x.acb`) from the `Sound_CueSheet` row.
* **Co-op** sends the course id and the index in the stage list; both sides resolve them with their own tables.

Two places are closed, and are what `port\runtime\mania.c` opens:

1. **Scene names** must be names of `AppScene.eID`. The hook on `EnumRuntimeHelper<T>.GetValue(string, default)`
   answers a name of six to nine digits with that number; `Enum.ToString` of a value without a name gives the
   digits back. Imported scenes are named `100000 + Mania stage id`.
2. **Stage lists**: the group tables are held in an array with one slot per compiled `Stage.List.eID` value
   (`IDTableInstance.SetObject`, 0x28b7eb0), 40 of them, and an id past the array has no table
   (`StageList.Setup`, 0x43287d0, would fail on null). All imported courses share one real list, the unused test
   list 12 (`Stage_List_Group_wld97_wldtst`), and each has a virtual list id (1000 + n) that only
   `StageList.Setup` ever sees: the hook builds list 12 and keeps the course's range of it
   (`game\mania\mania_courses.txt`).

## The conversion (`mania\stage.py`)

There is no Unity editor in the loop. A new stage bundle is a copy of World 1 Stage 1's bundle, rewritten with
UnityPy (`mania\unityfile.py`):

* UnityPy has no call to add an object, but a serialized file is a dictionary of object records. A new object is
  a copy of an existing record of the same class (for a MonoBehaviour: of the same script) with a new id, and its
  contents are written through the type tree. After an object is rewritten UnityPy still *reads* its old bytes,
  so the editor keeps every object it touched as a dict and writes them all at the end.
* Built-in objects of the older engine fit the newer one's type trees almost unchanged. `overlay` lays a 2020
  dict over a 2022 one: fields only the newer engine has keep the template's value (`Mesh.m_CookingOptions`,
  `Texture2D.m_MipmapLimitGroupName`, `MeshRenderer.m_StaticShadowCaster`, clip bindings'
  `isSerializeReferenceCurve`, ...), fields it dropped are left out. Meshes, textures, clips and animator
  controllers are carried over this way, with their data moved from the resource file into the object.
* The bundle gets names of its own (two loaded bundles may not hold a file of the same internal name): the
  `AssetBundle` object's name, container path and scene hash, the internal file names, the references between
  the two files, and the `m_StreamData.path` of the objects that keep their data in the resource file.

What is built:

| Mania | Rumble |
|---|---|
| the `Behavior` tree | the same hierarchy under a new object `mania`, each drawn node with a MeshFilter and MeshRenderer |
| meshes | new Mesh objects, vertex data unchanged (Rumble's player takes any vertex layout) |
| materials | new materials of Rumble's stage shaders, modelled on three materials of World 1: `Shader Graphs/bg_lit_abd1n` (opaque), `Shader Graphs/bg_sad_abd` with alpha test (cut-out) or blending (transparent); `_MainTex` becomes `_Albedo`, `_Color` is kept, culling is kept |
| textures (DXT1 / DXT5) | new Texture2D objects, data inline |
| the `Collision` tree | the same hierarchy; each `CollisionStagePart` becomes Rumble's, with a new `CollisionStageData` (frames recomputed from the corners, boxes added, grid kept) |
| `BananaPos` | the node's transform in `m_BananaTransformList` (single and bunch) |
| `START` | the template's `START_NULL0`, moved there, turned by 180 degrees, lowered by the ball's radius |
| `GOALnn` (`MgGoalColi`, and its `MgGoalModel` twin in the `Behavior` tree) | the template's goal object (first goal) or a copy of it under a new object with the Mania node's name and place, turned by 180 degrees; drawn and colliding as Mania's goal (below) |
| the Animator of `Collision` | an Animator (update mode 1) and a ReplayTracker on the `Collision` copy, with the carried-over controller and clips, listed in `m_StageAnimators` |
| `StageMovObjManager.m_info` (moving node -> its drawn twin), `MgTRSSync` (source -> targets) | Mania copies transforms every frame; here each target is hung **under** its source, keeping its place, so the one Animator moves the drawn parts and whatever rides on a moving part |
| nothing (Mania moves every collision part it finds under an animated node) | the tag `StgMot` on every object the clips move and on everything below it (below) |
| `CollisionBumper` (+ the model under the root's `bumpers`) | Rumble's `CollisionBumper` (same sphere, same push) and `MgBumper` |
| `MgStageSwitchManager`, `MgStageSwitch`, `CollisionSwitchUpper` | `MgStageSwitchController` on the `Collision` copy, `MgSwitch` and `CollisionSwitchUpper` on each switch (below) |
| `MgSeesaw {momentFactor, frictionFactor, restoreFactor, seeSawModel}` on a node above the seesaw's collision parts | `MgSeesaw` (same three factors), one merged `CollisionStagePart` and a `ReplayTracker` on that node (below) |
| `MgConveyer {m_StaticSpeed}` next to a `CollisionStagePart` | `MgConveyer` with the same speed vector next to the converted part |
| `MgConveyManager {m_conveyParamArray}` on the stage root | the belt's material on Rumble's belt shader with the scroll speed (below) |
| `CollisionJamabar {m_OriginalMatrix}`, `MgJamabar {JamabarModel}` | Rumble's `CollisionJamabar`, listed in `m_JamabarList`; the model hung under it (below) |
| `MgWormholeColi {m_PairedWormhole}` with its model, camera and collision | a copy of Rumble's wormhole object (below) |
| `MgBlurFloor {m_LeadingFloor, m_CollisionHead, m_CollisionTail}` | its model under the head piece and a copy under the tail piece (below) |
| `MainGameStageArea {m_AttributeToAreaList}` | `area` lines of `mania_courses.txt` (below) |
| `LODGroup` | only the nearest detail level is drawn |
| fall-out height and box | `m_RingoutY`, `m_FalloutBounds` |

**Moving collision needs a tag.** Rumble decides once, when a collision shape wakes, whether the shape can move:
`CollisionShapeBase.Awake` (0x4280d90) walks the shape's parents and sets `m_IsAnimated` when one of them has
the tag `StgMot` (tag number 20000, the first tag of the game's own; the game's stages put it on each animated
`..._mot` object and all its children). A shape without it is a still one: its world matrix and culling sphere
are taken at load and never again, so the drawn part moves and the ball keeps hitting (or falling through) the
place where the part was. `isDynamic` on the shape has the same effect and is what scripted movers use. The
converter hashes every object path under the `Collision` copy (CRC-32 of the path, as clip bindings store it),
and tags the objects the carried-over clips are bound to, with their subtrees (`moving_objects` in the report).

**Seesaws.** Rumble's `MgSeesaw` turns its own object (`Move`, 0x4306810) and learns about a ball from
`OnPostCollide(GameObject)` (0x4305d30), which goes through the ball's hit list and takes only hits whose
shape sits on the seesaw's **own** GameObject; `Awake` also wants a `ReplayTracker` there. The game's seesaws
are therefore one object with a mesh, a `CollisionStagePart`, the `MgSeesaw` and a tracker. Mania's seesaw is
an empty node with the script and two children that carry the collision (the plank and the axle), each in a
frame of its own. `merged_part` carries the children's triangles into the node's frame, renumbers the edge ids
of the second part past those of the first, and stores a grid of one cell that lists every triangle (which is
what Mania itself stores for parts this small); the children keep no part. The drawn plank already hangs under
its collision twin, so it turns with the node. A seesaw script on a node with no collision under it (three
stages have one inside another seesaw) is left out. With `BR_MANIA_LOG` the port logs every fifteenth touch
with the seesaw's angle.

**Conveyors.** `MgConveyer.Awake` takes the `CollisionShapeBase` of its own object, and `FixedUpdate`
(0x4300070) gives that shape a fake displacement of `m_StaticSpeed * kGimmickSkipFrame * kFpsMultiplier / 60`
per step in the part's frame, so the ball is carried as if the floor had moved. Both games use the same unit
(Rumble's own belts run at 3 to 20, Mania's at 3, 16 and 100). The conveyor object needs the `StgMot` tag like
any moving part. The belt's texture scrolls: Mania's `MgConveyManager` (on the stage root) lists the belts' renderers
with a UV speed each, and a lit material of such a renderer whose Mania shader is a scrolling one
(`Custom/SurfaceVcScr`) goes on the shader of Rumble's own belts, `Shader Graphs/bg_lit_abd1n_fade`, with
`_Speedbelt_X1` / `_Y1` set (UV units a second; the shader adds time x speed, Mania takes it off, so the sign
turns). `BELT_UV_SPEED` is the factor from Mania's number: with 0.0075 the texture of SMB1's Conveyers moves as
fast as the belt carries the ball. The sand belts of one stage (st1069) are unlit materials and keep their own
scroll only.

**Jamabars** (the sliding bars of SMB1's Stoppers and Push, st1024 and st1035). In both games the bar is a collision
part that moves its own object: `CollisionJamabar`, a `CollisionStagePart` with the matrix of the bar's resting
frame (`m_OriginalMatrix`). Each step (`move`, 0x4282ca0) it takes the gravity vector of an `MgGravityController`,
turns it into that frame, lets its z part speed the bar up, and keeps the bar between 0 and -2.5 along its own z
axis. Rumble has the class but no stage with a bar, so there is no type entry to copy: `Scene.derived_script`
makes one from the entry of `CollisionStagePart` plus a matrix field (the engine reads a MonoBehaviour through
the stored type tree and matches the fields by name). Rumble also never hands the bar a gravity controller
(the property has no caller left), and without one the bar stands still: the port's hook on `move` gives each
bar a local player's (`mania.c`). The drawn bar hangs under the collision bar (`MgJamabar.JamabarModel`).
Online every machine moves the bars by its own player's tilt, so they stand differently on each machine (measured:
after the host alone tilted, its bars had slid up to 2.3 while the guest's were at rest). That is only seen, as
another player's ball standing in a bar: every ball is simulated on its own machine against its own bars. In
split screen the players share one set of bars, and the hook hands the bar the next local player's controller
each step, so the bars slide with the average of the tilts (each player alone moves them; before, only one
player did). `BR_JAMABAR_LOG=1` logs twice a second where each bar is and whose tilt moved it.

**Wormholes.** Rumble's wormhole is an object tree of its own: the gate model with a see-through surface, its
collision, a trigger square with `MgWormhole` and `CollisionWormholeGate`, a cubemap camera rig and
`MgWormholeCamera`, which draws the view through the gate. `Scene.import_tree` copies that tree from one of the
game's stages (`WORMHOLE_DONOR`) with every asset it uses (meshes and textures are taken out of the other
bundle's resource file), adding the type entries the template stage lacks; the stage then also depends on what
that stage depends on (`stage_extras.json`, `add_scenes`). A copy stands at each Mania gate, turned half round
(Mania's gate is entered from -Z, Rumble's from +Z), under the node the gate follows when that one moves; the two
gates of a pair name each other (`m_PairedWormhole`, `m_WormholeFrom` / `m_WormholeTo`). The surfaces of the two
games' gates have the same size (4.4 wide, 4.5 high); Mania's own gate model is not drawn (the goal's is: below).

**Blur floors** (SMB1's Blur Bridge, st1101). A floor slides to and fro, and two collision pieces follow it a
quarter and half a second later: the floor's trail, which carries the ball too. Mania draws the trail with a
script (`MgBlurFloor`) that stretches one model from the floor to the last piece. The model has the size of one
piece, so it is drawn on each of the two pieces instead; at the speeds the floors reach the pieces always touch.

**Areas.** `MainGameStageArea` on the stage root holds spheres with a meaning. `InactiveGoal` (Factory, st1109:
goals travel on a belt and are parked inside such a sphere): a goal standing inside does not count.
`DisableWormhole` (Conical Slider, st2318): a ball inside is not taken by a wormhole. Both go to
`mania_courses.txt` as `area <stage row> goal|wormhole x y z radius` and are applied by the hooks on
`MgGoalColi.OnTriggerEnterPlayer` and `MgWormhole.OnTriggerEnterPlayer`. `CameraDist` (st1110) is not carried over.

**Goals.** An imported stage has Banana Mania's goal: the ring gate with the star panel, the party ball and the
tape, blue, green or red as in Mania (the model's own materials; `m_GoalKind` is not needed for that). Rumble's own
stages are not touched: the model only exists in converted scenes. What plays the goal is still Rumble's goal
object, a copy of World 1's `goal_arch`: its trigger (`CollisionSquare`), `MgGoalColi` and the goal effect are
the game's, so results, replays and online play work as for any goal. Around it:

* The arch's own meshes stay in the scene (the object's Animator and effect root refer to them) with their
  renderers switched off.
* Mania's model (`MgGoalModel` node: `goal_base`, `goal_glass`, `goal_base_ill`, `goal_tape`, `goal_sphere` with
  its two halves) is converted like any drawn node and hung under the goal in an object `mania_goal`, turned back
  by the 180 degrees the goal object is turned.
* The arch's collision part (`model_col2`) gets a new `CollisionStageData` made from the triangles of Mania's
  collision-side `goal_base` mesh (1320 triangles: the ring and the two posts, 2.35 to each side and 5.55 high,
  the opening between the posts 1.75 wide), carried into that part's frame. `triangles_part()` builds the part:
  every edge gets an id shared by its two triangles, none where they meet flat or in a valley, and the grid is one
  cell. Mania does not use a triangle part for the goal (a script computes it); the party ball and the tape are
  not solid here.
* The goal object hangs under an object that has the Mania node's name. Factory (st1109) animates the goal nodes
  themselves: thirty goals hang upside down from claws that carry them along a rail, and at the end of the rail the
  claws open and the goal falls (the fall is keyframed in the stage's clip, down to y -1000). The clip finds its
  nodes by name, so a goal object called `goal_arch` was never moved by it and stayed in the claws for ever; now
  the goals are released and fall. A falling or parked goal does not count (the `InactiveGoal` areas, above).
* When a ball goes through, the tape goes and the party ball opens: `mania.c` (`goal_entered`, from the hook on
  `MgGoalColi.OnTriggerEnterPlayer`) hides `goal_tape` and swings `goal_sphere01` / `goal_sphere02` apart over
  0.45 s. A retry does not load the scene again, so `goal_tick` closes the ball and brings the tape back when the
  stage sequence returns to PREPARE / INTRO / READY / RETRY.

Not done: what a green or red goal does in Mania (skipping stages; every goal ends the stage), the tape's cloth
motion and the confetti of the party ball (Rumble's own goal effect plays), the party ball as a solid thing.

**Script classes the template does not have.** World 1 Stage 1 has no bumper, switch, seesaw or conveyor. A script class is made
usable in the new scene by copying two things from a stage of the game that uses it (`SCRIPT_DONORS`): the
class's `MonoScript` object into the shared file, and its type entry (with the type tree) into the scene file,
pointing at a new entry of the file's script list. `Scene.import_script` does that; new objects of the class are
then added like any other.

**Switches.** Rumble's switch classes are Mania's under other names, and the data maps field by field:

| Mania | Rumble |
|---|---|
| `MgStageSwitchManager {m_Animator, m_StageSwitchList, m_ClassIdToParamNameDict {list: [{Key, Value}]}}` on the stage root | `MgStageSwitchController {m_Animator, m_SwitchList, m_ClassIdToParamNameDict {m_EntryList: [{m_Key, m_Value}]}}`, listed in `MainGameStage.m_StageSwitchControllers` |
| `MgStageSwitch {m_State, m_ClassId, m_SerialId, m_isTurnOnDefault, m_StageSwitchManager}` | `MgSwitch {m_SwitchType, m_ClassId, m_SerialId, m_isTurnOnDefault, m_StageSwitchController, m_Animators, m_OnClip, m_OffClip, m_TrsFollow}` |
| `CollisionSwitchUpper {m_CylinderRadius, m_CylinderHeight}` | `CollisionSwitchUpper {m_Cylinder {pos, rad, height, rot}}`, a trigger on layer mask 1 |

`m_State` / `m_SwitchType` is `StageAnimation.eState`: 1 fast rewind, 2 reverse, 3 stop, 4 play, 5 fast forward.
The dictionary names, per switch class, the animator float parameters (state speeds) the class drives.
Rumble's controller finds the class of each animator layer by matching the layer's name against
`class(?<classId>\d+).*(?<frameStart>\d+)to(?<endFrame>\d+).*` (`MgStageSwitchController.Awake`, 0x4308950),
which is the shape of Mania's own names, so the carried-over controller needs no renaming. A Mania switch
object has two `MgStageSwitch` components; the one without a manager (the button's body) is left out. The
switch model has an Animator with the states `on`, `off` and `default` (the button sinks, its rim lights up); the
controller is carried over, an override controller's clips put in, and the clips renamed to their states,
because `MgSwitch.TurnOn` plays the state called like `m_OnClip` on each of `m_Animators`. A switch without such
a model gets the game's own clips (`obj_com_switch_on` / `_off`, copied from World 3 Stage 1).

How a press travels, for whoever debugs one: the ball's `CollisionSphere` is tested against the cylinder in
`CollisionSwitchUpper.Collide` (0x428c710) and, on a hit, put into the shape's `m_CollidedObject` set;
`CollisionShapeBase.ResolveTriggers` (0x4283850) sends the Unity message `OnTriggerEnterPlayer` for balls that
are new in the set; `MgSwitch.OnTriggerEnterPlayer` (0x430b0a0) outside battles puts a `request_t {state,
class, serial}` straight into the controller's queue (it does **not** go through either
`MgStageSwitchController.Request`, those are for battles and the network); `ManualUpdate` (0x4307c20) takes it
out, looks up the class's parameter names and sets each to `Util.Stage.GetAnimSpeed(state)` on the Animator.
With `BR_MANIA_LOG` set the port logs each press (`mania: switch pressed: type, class, serial`).

The template's own stage geometry, checkpoint and guide arrows are removed; its goal, start, intro-camera bounds
and initializer stay. Objects of the shared file that nothing refers to any more are dropped.

Each stage keeps its own copies of the textures it uses (about 2 MB a stage, 0.9 GB for the 392 that are imported).

### Courses, tables, catalog (`mania\build.py`)

| Written | Content |
|---|---|
| `Switch\mania\scene_<n>.bundle` | one per stage |
| `Switch\mania\bg_<n>.bundle` | two per Mania background: its scenery scene (200000 + n) and its lighting scene (210000 + n), see "Backgrounds" |
| `Switch\mania\thumb_<name>.bundle` | Banana Mania's thumbnail of each stage and course as a Rumble sprite ("Missions, menu pictures and the editor") |
| `Stage`, `Stage_Text_<lang>`, `Stage_DoleDisposition` | a new row per stage (ids from 705): scene name, name, 60 or 30 seconds, its thumbnail, its mission values, the converted scenery and lighting scenes of its Mania background, the game's empty sky scene `sky05_w05`, no effect scene and no screen effect. Without backgrounds (`--no-backgrounds`, `backgrounds=no` in `input\mania.txt`, or a background that failed to convert): the scenery, sky, lighting and effect scenes of the Rumble world that stands in for the Mania background (`WORLD_OF_BG`) |
| `Stage_List_Group_wld97_wldtst` | every imported course's stages, one after the other |
| `Course`, `Course_Text_<lang>` | a row per course (ids from 27), category 6, always unlocked, missions as `overrides.json` says, hung on the end of the game's chain of Adventure worlds (below) |
| `UI_Sprite` | a row per new picture |
| `MainGame_Story_Progress` | a row per stage that opens it |
| `MainGame_Adventure_Type`, `MainGame_Adventure_Type_Text_<lang>` | a third row, "Mania": the tab of *Select World* that holds the imported courses (below) |
| `Sound_CueSheet`, `Sound_Cue`, `Sound\*.acb`, `*.awb` | Mania's cue sheets, copied unchanged, and a cue row per BGM; with the Classic Soundtrack add-on also its sheets (`<sheet>_dx`, same cue names) and a second cue row per BGM |
| `catalog.json` | the game's catalog plus, per stage, the bundle and the scene (key = the scene number), depending on the bundles the template stage's scene depends on |
| `mania_courses.txt`, `mania_music.txt` | for `port\runtime\mania.c`: course ranges and ids, the placement of the background for the stages that move it (`bgroot` lines), the game's own worlds; per stage row its cue row and its Classic Soundtrack cue row |
| `mania_stages.txt` | course number, stage number, Mania stage, course name, stage name (for people and `try_stage.py`) |
| `import_report.txt` | per stage: counts, and the Mania components that were not converted |

29 courses are made (`COURSES`): Super Monkey Ball 1 Beginner, Advanced, Expert with their Extra floors and
Master; the ten worlds of Super Monkey Ball 2's story; its eight challenge difficulties; Deluxe; Original Stage
Mode; Reverse Mode; and "More Stages" with every stage that is in none of them, so every imported stage is reachable.

**Bonus stages are not imported.** 18 of Mania's 410 stages are bonus stages (stage kind `Bonus`): bananas
against the clock, and for five of them no goal. They do not fit worlds that are about reaching the goal and
clear times, so `plan_courses` leaves them out of every course, which leaves 392 stages. An earlier version
imported them with rules of its own (a clear by taking every banana, by falling out or by the clock, through
hooks on `MainGameSequence.setState` and `updateHurryUp`); that code is gone. A re-import deletes the stage and
background bundles an earlier import left behind.

**The Mania tab.** *Select World* has a tab per row of `MainGame_Adventure_Type` (Story, Special). A tab holds
the `MainGame_Category` rows of its type (Story: the plain game; Special: the time attacks and rule variants),
and each of those the courses whose `IsEnabledCategory` entry is set. The import adds a third row, but no
category of its own: the category id is the game mode to everything that reads it (rules, save slots, arrays
with one entry per category), so a new one would be a new mode. Instead `port\runtime\mania.c` rearranges the
lists the game has built (`tab <row id>` in `mania_courses.txt`):

* A hook on the set-up coroutine (`<SetupCourseSelect>d__19.MoveNext`, 0x46a17d0) lets each step run and then,
  when the lists are new, makes a second list item of the plain category under the new tab and moves the imported
  courses from the Story tab's list into it. A course chosen there starts exactly as it did from the Story tab.
  The tab and row the screen opens on are set from the course last played, so leaving an imported stage returns
  to the Mania tab.
* The tab bar is a prefab with two buttons at fixed places (`ui_PartView_WorldSelect_TabGroup`, a
  `UIPartViewTabGroup_Explicit`). The same hook copies the second button (`Object.Instantiate`), adds it to the
  view's button list before the game builds its tab module from that list, and scales and places the three in
  the room the two had. The copy is registered for mouse clicks like the others.
* `FlowCourseSelectModeBase.onUpdateTabSelectedIdx` (0x46a08b0) starts the plain picker for type 1 and the time
  attack picker for type 2, and for any other type leaves the previous tab's picker running. For the new tab the
  record carries id 1 for the length of that call. The same hook remembers the cursor's row per side (the new
  tab shares no world with the other two, so the game's "same world, else same row" rule would land anywhere).
* A tab's name is an array indexed by the category of the focused course (the first tab reads Story, Extra or
  Ultimate). Imported courses are category 6, so the first tab would read "Ultimate" while the cursor is in the
  Mania tab; `Util.Adventure.GetCourseCategory()` (0x440c2f0) answers 1 for an imported course to the two callers
  that name the tabs (told apart by return address).

The world pickers of co-op and online rooms have no tabs and list the imported worlds after the game's own, as
before.

**The chain of worlds.** `Course.NextCourseID` links the Adventure worlds: 1 .. 10, the EX worlds 12 .. 21, the
two Ultimate EX worlds 25 and 26. World Tour, World Tour EX and the No Miss Challenge are on no chain. The world
picker of local co-op and of online rooms (`UIChoicesItemData_Factory.getUnlockedCourseList`, 0x45605b0) walks
that chain from the first world to the "highest unlocked" one, so the imported courses are hung on its end
(course 26); linking them after the table's last row, as the first version did, put them on no chain and the
picker never offered them.

**The highest unlocked world.** `SaveUserParam.AdventureParam.GetAdvModeHighestUnlockID` (0x43c37d0) answers
with the last course in display order whose previous course is cleared. An imported course has no previous
course, which counts as cleared, so with an import the answer was always the last imported course: every world
of the game was offered in the pickers and reported to the other players of a room as open. The port answers
from the game's own worlds (`own <id> <previous id>` lines of `mania_courses.txt`) when the game's answer is an
imported course, and adds the imported courses to the picker's list itself.

**The end of an imported world.** All imported stages are rows of one real stage list, and each list item
carries the stage that follows it (`StageListItem.m_NextStage`, read by `StageList.GetNextStage` after a
clear). The last stage of a course was therefore followed by the first stage of the next course, and the
game went on into it with the wrong course's list. The virtual list built for a course ends with "no next
stage", like the last stage of one of the game's own worlds: after it the game returns to the menu.

**Fall-out boxes.** Five stages (Steps among them) have no fall-out box in Mania: `m_FalloutBounds` holds
FLT_MAX / 2 on each side. Rumble takes the box literally and its arithmetic overflows: Fall Out on the first
frame. Such a box is replaced by one around the stage, as for stages that have none.

**The intro: Banana Mania's camera** (`port\runtime\mania_intro.c`, `stage.py` `mania_intro`). Rumble opens a
stage with two timelines: the stage timeline (title card, and a generic camera move between two points of a box,
`BeginningBounds`) and, with READY, a player timeline whose camera flies in to the ball from the front. Banana
Mania has no timeline for it: its camera state `MainCameraReady` computes the intro from the stage. Read from
Mania's own code (`GameAssembly.dll` of the PC version, method addresses from the metadata with the LibCpp2IL in
Mania's BepInEx folder; values from the `GameParam` object in `sharedassets0.assets`):

* start: look at the centre of the stage's box, pitch -60.254 degrees (`cameraStartXAng`), heading = the ball's
  start heading - 360, distance 1.6 x half the box's diagonal. The box is `Util.CalcStageBounds`: every object
  under the stage with a mesh adds the two corners of its mesh bounds after its transform; its bottom is raised to
  the fall-out height (`m_ringoutY`, unless that is -FLT_MAX).
* end: look at the ball's start + 0.98 up (`interestOffsetY`), pitch -18.281 (`cameraXAng`), heading = the start
  heading, distance 3.362 (`cameraDist`).
* `r` runs from 1 to 0 in 360 frames of 1/60 s (6 s), eased `s = r^2 (3 - 2r)`; look-at point, angles and
  distance are blended by `s`; the eye is the look-at point + `Euler(pitch, heading, 0) x (0, 0, distance)`,
  looking at the look-at point, field of view 60. The camera turns once round the stage as it comes down.

The import writes `intro <stage row> cx cy cz distance sx sy sz heading` per stage into `mania_courses.txt`. The
port flies it through four entry hooks:

| Hook | What it does there |
|---|---|
| `MgBeginningTimelineController.StageTimelineUpdate` (`442d1e0`) | a pure "is the stage timeline over" question, once a frame in the intro state: answers "not yet" until Mania's 6 s have passed. They count from the moment the loading screen has gone (`UIFadeManager.stateKind` None): the intro state starts under it. A skipped intro (button, or a retry, which the game skips) is left alone |
| `MgBeginningTimelineController.PlayerTimelineUpdate` (`442d600`) | marks that the READY state is on. On its first frame after Mania's intro each player's READY timeline (3.5 s) jumps to its own `m_SkipTimeShort` (1.75 s, the game's shortened READY) with the game's forward-only `PlayableDirectorInterface.SetTime`: its first half is the game camera's fly-in from the front, which Mania's pose replaces, so it was a still picture before the READY text |
| `CinemachineBrain.PushStateToUnityCamera` (`20c7800`) | the stage timeline's camera (`cm_BeginningCameraBounds_Camera`, the only camera drawing then) gets Mania's eye, orientation and field of view |
| `MgCameraStateReady.setPos` (`42aa8f0`) | the game camera's READY state (already on during the intro, it draws once the stage timeline's 6.8 s are over): Mania's pose; in READY the end pose, blended over the last 40 % of READY into the game's own pose (its own `setPos` is run and read back), so GO does not jump. A world with "title card: none" (editor) has no stage timeline and so no timeline camera: the game camera stays off until READY and the intro was black. There the hook switches the game camera's `Camera` component on and it draws the orbit |

The title card, READY, GO, the ball's entrance and Rumble's own stages (no `intro` line) stay the game's.
`BR_MANIA_INTRO=0` turns it off; `BR_MANIA_LOG=1` logs the start, the pose twice a second and the READY blend.
Seen (2026-11-14): Stoppers (st1024) frame by frame against the log, Factory (st1109, 82 units out at the start),
Wormhole (st2028), a fall-out retry on st1101 (skipped, the game's), World 1-1 (unchanged). Not seen: split screen,
online, a replay, Banana Mania itself side by side. Wormhole starts 204 units out (its own meshes run from z -156
to +95), so the first moments look at the background's arena wall from outside; whether Mania shows the same
was not checked.

The old `BeginningBounds` box (the import still sets it to the stage's size, turned half round because Rumble's
stages run towards +Z and Mania's towards -Z) only matters with `BR_MANIA_INTRO=0`.

### Backgrounds (`mania\background.py`)

Each of the 19 Mania backgrounds the imported stages use (all 21 but the two of the bonus stages; `Bg_<name>` prefab, `Light_<name>` prefab, the `RenderSettings` of its lighting
scene) becomes two Rumble scenes, each made from a copy of one of the game's own; the module's docstring has the
details and every number that can be tuned is a named constant at its top (`build.py --bg-option key=value` sets
one for a test import).

* **Scenery** (`bg_2000NN.bundle`, from `wld05_w05_003`): Mania's drawn tree under the root with `MainGameBg`,
  names unchanged, on layer 6, with its Animator when the clip moves something. All materials are on
  `Shader Graphs/bg_unlit_abd` (unlit: texture x colour x vertex colour, blend state and queue from Mania). What
  that shader cannot be told is baked into copies of the meshes: the gamma of vertex colours, constant UV
  transforms, a colour's alpha, and Mania's light on its lit materials (four fifths of the scenery): per vertex,
  Mania's ambient light in the direction of the normal plus its background lights x N.L, multiplied into the
  vertex colour (a white colour channel is added to meshes without one). That is what gives the rocks their lit
  and shadowed sides; without it the scenery looked flat and pale. No cast shadows; moving things keep the
  light of their rest pose.
  The sky is Mania's dome mesh; the skybox cubemap behind it is one flat colour.
* **Lighting** (`bg_2100NN.bundle`, from the lighting scene of the Rumble world in `LIGHT_TEMPLATE_OF_BG`, whose
  post-processing profile and reflection cubemap stay): the three Rumble lights get Mania's colours, directions
  and (scaled) intensities, `RenderSettings` Mania's ambient colours and linear fog.
* **Fog trap**: `RenderSettings.m_FogDensity` must be near zero although the fog is linear. The game's shaders for
  bananas, characters and stage objects apply it as well; with a template's 0.01 everything near the camera was
  hazed in the fog colour (washed-out bananas and player, a white Masters stage).
* **Placement**: 27 imported stages move, turn or scale their background (Mania's `BgRoot` prefab). There is one scenery
  scene per background, made at the origin; `MainGameBg.Awake` (0x426a5b0) is hooked and sets the root's local
  position, rotation and scale from the stage's `bgroot` line.
* **Particle systems** (storm fires, sparks and lightning, waterfall mist and spray, the cloud puffs of Masters,
  drifting ice crystals, meteorites; `PARTICLES`): the two components are carried over into the far scene, on the
  engine's own classes (their type entries come from one of the game's effect scenes, `PARTICLE_TEMPLATE`; modules
  the newer engine added stay off), where the node is in Mania's tree, so they follow a moved background. Their
  materials go on the unlit shader like the rest. A system that starts another (a fire its sparks) keeps the link.
  **Depth test trap**: Unity's particle shaders do not set `ZTest`; written out as 0 the material's `_ZTest` means
  "off" and the particles are drawn over everything (mist and fire in front of the stage). `describe` turns any
  value outside 1..8 into 4. `PARTICLE_CLEARANCE` can leave out systems with large particles near the stages; it
  is 0 (off), because with the depth test right nothing covered the stage any more.
* **Flip books** (the dancing silhouettes in the windows of Night; `FLIPBOOK`): the one shader cannot step through
  a sprite sheet, so a flip book renderer becomes one object per frame (the frame baked into the UVs of a mesh
  copy) under the original object, and an Animator there gives one frame after the other the scale one and all
  others zero. The clip is written by `stepped_clip` (a streamed clip of step keys on scale curves; one clip and
  controller per frame count and step time). Frame = start + floor(time / step) mod (end - start), as in Mania's
  shader.
* **Reflections**: the lighting scene's reflection cubemap (what the ball mirrors, and glossy stage floors) is the
  cubemap that Mania's reflecting materials use with the background (its scenery's, else its stages'; cut down to
  256 px; `REFLECTION_CUBEMAP`); a background without one keeps the Rumble template's. The reflecting scenery
  itself (Electric's batteries, the Whale's metal) is still plain albedo: Rumble's cube shader `bg_sad_abd_cube`
  was tried for it and draws pure black, through whatever is in front (`SCENERY_REFLECTIONS`, off).
* Not converted: camera weather (the `ScreenEffect_*` prefabs), flow-map distortion, toon ramp, rim light,
  specular highlights, mirror images on the scenery, Mania's post-processing, the collision twin of four
  backgrounds.

### Runtime (`port\runtime\mania.c`, `classic.c`)

* the override folder: bundles under `aa\Switch\` are taken from `mania\Switch\` when they exist there, the
  catalog from `mania\catalog.json`, sound files from `mania\Sound\`;
* numeric scene names and virtual stage lists (above);
* `MainGameBg.calcBgCue` answers with the imported cue for an imported stage (`mania_music.txt`): Banana Mania's
  own music, or the Classic Soundtrack's when the import has it and the player chose it (Options > Audio >
  Imported Stage Music, the last row of that page, added in `display_opt.c`; kept in `port_mania.txt`);
* the list of worlds offered in co-op and online rooms keeps the imported courses (they are not "unlocked"
  in the save's sense) and the online protocol number carries a tag made from the imported course ranges, so
  games with different imports do not meet;
* the hooks described above for the highest unlocked world, the end of an imported world and the
  placement of a background;
* play statistics: `Wonder.CRM.AdventureUtil.UpdateMissionStatus`, `UpdateBestTimeStatus`, `StartTimeAttack` and
  `FinishTimeAttack` do nothing for an imported course. They keep flags and counters for the publisher's
  statistics upload in arrays sized by the `Course.eID` enum (27 courses, 270 stages) and index them with
  `course * 10 + stage` unchecked (the game has no array bounds checks), so a new best time on an imported stage
  (course 27 and up) wrote into the object behind the array. The damage showed later and elsewhere: an access
  violation in `il2cpp::vm::Liveness::FromRoot` on an engine worker thread during the next unused-asset sweep.
  **Any other code of the game that indexes a fixed array by course or stage number has the same trap**; the
  stress switch `BR_UNLOAD_EVERY` (`docs\TECHNICAL.md`) makes such damage show within one stage;
* `BR_MANIA_LOG`: log lines for switch presses, seesaw touches, the BGM cue of a stage, the world picker's
  list and dropped statistics calls.

## Spin Dash on or off (`port\runtime\spindash.c`)

Banana Mania's stages were made for a ball without the Spin Dash, so it can be turned off. The choice is not tied
to imported stages: it holds for every Adventure stage of the mode it is set for. Kept in `port_gameplay.txt` next
to the saves (`spindash=`, `spindash_multi=`; both on when there is no file).

* **Single player:** *Options > General > Spin Dash (Single Player)*, the last row of the page (a copy of the
  Screen Mode row object with a role, like the other added rows in `display_opt.c`).
* **Multiplayer Adventure:** a *Spin Dash* picker under *Ball Collision* on the game settings screen, in split
  screen (`UIViewCtrl_AdvMultiSetting_Offline`) and online (`UIViewCtrl_AdvMulti_GameSetting`). That screen is a
  fixed panel with one view per row, so the hook on `setupChoicesItemList` adds a row object (a copy of the Ball
  Collision row; the two functions the screen calls for such a row tell the copy apart) and, the first time, a
  picker view and a heading (copies of Ball Collision's), and spreads the three groups between the World heading
  and the line over Confirm. The two panels differ (the online one has a picker and a heading this screen does
  not use), so headings are found by position, not by name.
* **Online** the host's choice holds for the room. It travels in the "advanced settings" the host sends with every
  stage start (`AdvGameMaster.getAdvancedSettings`: `int[2]` = time limit, ball collision off) as bit 1 of the
  second number; `OnRecvAdvInit` / `setAdvancedSettings` take it out again before the game reads the number. A
  guest whose game lacks this code would read "ball collision off" from a host with Spin Dash off (both games are
  this port, and the room tag already keeps games with different imports apart).
* **What off does:** `PlayerSpinActionModule.getMainActionInput` / `getMainActionDownInput` answer "not pressed"
  for a local player, so no charge starts; `UIMgPlayerViewCtrl_Base.SpinAction_OnUpdateIdle` hides the charge
  gauge of the HUD (the ring around the face; the speedometer stays). Players of other machines are shown as
  their machines report them.
* **Never changed:** Battle modes (told by the class of `RuntimeParam.battle.gameMaster`: only `AdvGameMaster`
  is multiplayer Adventure; no BattleRoyale object = single player), the tutorial (it waits for a Spin Dash),
  replays (they play what was recorded).
* `BR_SPIN_LOG=1` logs which mode applies and what a room was told.

## Skip Stage (`port\runtime\stage_skip.c`)

A row in the pause menu of Adventure that leaves the stage being played for the next one, on the game's own
stages and the imported ones. It asks first ("Skip this stage?", focus on No).

* **Single player:** *Help Menu > Skip Stage* (the last row of that tab, under the game's *Mark as Cleared*; the
  Game Menu tab is full, its view has five buttons). Yes goes straight to the next stage, by the steps of the
  result screen's *Next* (`FlowMaingameResultBase.onDecideNext`): `StageList.IncIndex`, the next stage's save
  condition opened (`SetConditionFromStageIndex`, never lowered), `transitionStageToStage`, then
  `RequestSceneChange` with a `UIStateArgTransitionToMainGameScene_NoParamNextStage`. The stage left is **not**
  marked as cleared and nothing is recorded for it; the next one becomes selectable in Select Stage. *Mark as
  Cleared* (costs points, only on a stage not yet cleared, shows the result screen) is untouched. No row on the
  last stage of a world, in the tutorial, in a replay, or outside stage-by-stage play
  (`SelectorParam.m_MainGameCategoryID` other than 1: the timed runs).
* **Split screen and online:** *Skip Stage* above *Quit* in the multiplayer menu (`UIStateInBattleMenu`). Its view
  has four buttons, which fill the envelope: a fifth is instantiated from the last one and the five take the
  room of the four (each four fifths the size and four fifths of a row apart, around the same middle; a
  guest's menu, without the row, keeps the game's four buttons as they are). A stage of
  several players ends only through the game master every machine runs, and the next stage is started by the
  host from the scene after the result screen (`BattleStarter.RequestStartAdventureOnline`, refused while a
  stage is played), so the stage is ended the way *Mark as Cleared* ends one: every player still playing gets
  `MgPlayer.isGoal` with the time played so far as goal time, which `PlayerStateMainGame.OnUpdate` turns into
  the ordinary goal (`NetworkEvent.Goal` online). The result screen follows and *Next* is chosen there as after
  any stage; the stage counts as cleared by everybody in that time (the multiplayer result flows write no best
  times). Split screen: any player's menu has the row. **Online: the host's only**; the choice goes to the
  guests as a 12-byte message of the port's own (`online_send_port`; `online.c` hands it to
  `stage_skip_message` instead of the game), carrying the stage's index, and each machine flags its own
  players. A guest whose game lacks this code would pass the message to the game as an unknown event.
* How the row gets into the menus: both hand their finished row list to `UIChoicesGroupModule_Vertical..ctor`
  (hooked); the row is a copy of the list's first row object, recognised by its address in the hooks on the
  menus' `onInitSelectableButton` (text) and `onDecide`. The answer is read from the dialog's `UIStateHandle`
  on a later frame (`stage_skip_tick`); the multiplayer menu is closed with `RequestStatePop` once it takes
  requests again.
* `BR_SKIP_LOG=1` logs why a menu did or did not get the row.

## Missions, menu pictures and the editor

Three things of a Rumble world have no counterpart in Banana Mania, and a person decides them: `mania\overrides.json`
(format in `mania\overrides.py`), written by the editor and read by `mania\build.py`. The file is empty to begin
with; without an entry an imported world looks and plays as the import alone makes it.

**Stage missions.** Rumble's Adventure stages each have three (`Stage_Mission`, rows 1 to 3): "Clear within N
seconds" (`Stage.MissionTime`; its perfect mark asks for `MissionTimeMaster`), "Clear and collect N bananas"
(`MissionBanana`; perfect: all of them) and "Clear and collect the Golden Banana". A course shows them when
`Course.IsStageMissionEnabled` is set. What is saved is a dictionary per stage entry of the course
(`SaveParamStageMission`), so an imported course needs nothing more than the flag and the stage values:

* the Golden Banana is an entry of kind 3 in `MainGameStage.m_BananaTransformList`. Mania's stages have none; the
  banana named in the overrides (its path below the stage root, `Collision/bananaset/banana003`) gets that kind
  in place of its own (`stage.py`, `gold`). What the rest are worth (a bunch counts 10) goes into
  `game\mania\stage_extras.json` with the path, so `build.py --no-stages` converts again exactly the stages whose
  Golden Banana changed;
* a course has missions when its entry says so, and without one as soon as one of its stages has a Golden Banana
  or a time. Rumble has no formula for its mission values (they are set by hand per stage), so stages nobody set
  values for get half the time limit, a perfect mark at 45 % of that time and 75 % of the bananas (rounded down to
  a multiple of 5): the medians of Rumble's 200 Adventure and challenge stages. The banana mission's perfect mark
  is always every banana (`MainGame.IsTakenAllBanana`), there is no value for it; without a Golden Banana
  the third mission cannot be completed (the editor shows which stages lack one);
* the game adds up the missions of every course for the percentage of the Missions menu and for the conditions
  that ask for all of them (`Util.Mission.GetStageMissionCompletedNumOnAll`, 0x4450ed0). Imported worlds stay out
  of that sum: the hook on `GetStageMissionCompletedNumOnWorld` (0x4451cd0) answers "none" to that one caller
  (told by the return address). Each world's own count is shown as for any world;
* the play statistics call on a completed mission (`CRM.AdventureUtil.UpdateMissionStatus`) was already dropped
  for imported courses (above).

**Pictures.** A row of `UI_Sprite` names a sprite asset by GUID; the catalog leads to a bundle with one texture
and one sprite. `mania\sprites.py` adds pictures: a copy of the bundle of World 1 Stage 1's thumbnail (512 x 512,
DXT1) with another image, catalog entries under a GUID of its own, and an unused row of the table (it has two
thousand; the Classic Outfit's icon takes the last one, so the table is written after that step, starting from
its result).

* Stage thumbnails (`Stage.ThumbnailSpriteID`, `MiniThumbnailSpriteID`; 0 shows "no image") are Banana Mania's
  own: `MgStageData` names one per stage (`UI/thumbnail/Common/t_tmb_st<id>.tga`, bundle `ui_thumbnail_common`).
  Mania's are slanted cards with a rim on a transparent ground, Rumble's plain squares, so the largest opaque
  centred square is cut out (about two thirds of the card).
* A course's small picture in Select World is Mania's thumbnail of the course where it has one (the story worlds,
  Deluxe, the special modes; the SMB1 and SMB2 difficulty courses borrow that of the matching challenge course,
  `THUMB_COURSE`), else the Rumble world's.
* The rest of a course's look is borrowed from a Rumble world, the "theme" (`Course.BrochureSpriteID`: the big
  picture beside the lists; `BeginningTitle`: the title card when a stage loads; and when asked for
  `IconSpriteID`, which `MgBeginningTimelineController.SetupStageTimeline` reads for that card). Without a choice
  it is the world that stands in for the first stage's background (`WORLD_OF_BG`), as before. A course without a
  title card (an empty `BeginningTitle`, as the game's World Tour has) loads and plays.

* Pictures of one's own go before all of these (`overrides.json`: `picture` of a stage; `picture`, `big_picture`,
  `icon_picture` of a course). They are PNG files in `input\pictures\`, the user's folder, which is not part of
  the repository; the editor writes them there in the shape the game shows (512 x 512 for the small pictures,
  804 x 1004 for the big one, both filled from the middle of the upload; 132 x 132 with transparency for the
  icon, fitted whole). The big picture and the icon are copies of World 1's sprites with another image
  (`Sprites.add(..., template=)`), which gives them size and texture format; the sprite's name holds a hash of
  the picture, so a changed picture is another asset. A file that is missing is passed over with a line in the
  import's output.

* **A stage picture "From the view" is taken in the game.** The editor's button keeps its own drawing of the
  stage as a preview (`picture`) and, with it, where the view was (`view` in `overrides.json`: eye, point looked
  at, both in stage coordinates, and the vertical field of view of the square, 45.8 degrees for a view wider
  than high). The import (`mania\thumbshot.py`, called by `build.py`) then starts the built game for each new
  view on the test save (profile `T`; the real save is not touched; no sound, the real keyboard and controllers
  ignored), walks the menus into the stage as `try_stage.py` does and sets `BR_THUMB_VIEW` (`port\runtime\thumb.c`):
  once the stage has started, the port begins the game's own free camera, View Stage of the pause menu
  (`MgViewStageController.Begin`), without the menu; a hook on `MgViewStageCamera.updateTRS` sets its orbit
  values (point looked at, distance, pitch, turn: the editor's orbit is the same construction, mirrored in x)
  every frame and gives its cameras the field of view; the mode's markers and the players are switched off, and
  so is every UI canvas (`rt_hide_ui` in `ultrawide.c`, through the CanvasScaler hook). "thumb: ready" in
  `port.log` tells the importer to photograph the window (`PrintWindow`, so windows in front do not matter; the
  middle square of the client area, scaled to 512). So the picture has the game's lighting, the stage's Mania
  background and goal, and no ball or HUD. It is kept as `build\mania_views\st<id>_<hash of the view>.png` and
  taken again only for another view (or `build.py --retake`); `--no-views` leaves the step out. Up to three
  copies of the game take pictures at the same time (`thumbshot.INSTANCES`), each with its own test save
  (`T`, `T1`, `T2`), log (`BR_LOG=port<n>.log`, `player<n>.log`) and input file; one picture takes about 75
  seconds whether one copy runs or three (measured: 4 pictures in 151 s instead of about 300). Going on from
  stage to stage inside one running copy was tried and does not work yet. During play the UI state manager
  holds no state to ask a scene change of. In the View Stage mode PLUS opens nothing; after
  `MgViewStageController.End` plus `PauseManager.ForcePauseOff` it opens the pause menu, and Skip Stage's scene
  change asked of that menu is queued and pushed (its manager's stack grows) but the stage never changes. The
  attempt is kept outside the repository as a patch. With
  `--no-stages` and the stage already in the game as this import would make it, the pictures are taken before
  the import; otherwise after it, and the import runs once more with `--no-stages --no-views` to put them in.
  A picture that could not be taken (the game is running, the menus were not reached) leaves the editor's
  preview in the game, with a line in the output. One picture takes 70 s on the development machine, because
  the game is started for each. The importing process must not declare itself aware of display scaling: then
  `PrintWindow` gives the content smaller than the window rectangle.

**The editor** (`editor.cmd`, `mania\editor.py` with the page `mania\editor.html`): a page in the browser, served
on 127.0.0.1 only, that takes changes only from itself (the `Origin` header is checked). Left: the worlds and
their stages. Middle: the stage as Mania has it, drawn with WebGL from the drawn meshes at rest (read from the
Mania install with `maniastage.py`; textures scaled to 256), with a marker on each banana, the start and the
goals; a click on a banana makes it the Golden Banana. Two more tabs are mock-ups of Select Stage and Select
World with the pictures and mission numbers the game will show. Right: the stage's mission values and the
world's missions switch, theme and pictures; under each picture "Upload" takes an image file (PNG, JPEG, WebP,
BMP, GIF) of one's own and "Remove" deletes it again, and a stage's thumbnail can also be taken "From the view"
(the middle square of the 3D view on a sky, as a preview: the game draws the real one from that spot when the
import runs, see above). Every change is saved at once; "Apply to game" runs
`build.py --no-stages` (about a minute; it refuses while the game runs, because the game keeps the files open).
Nothing of either game is copied into the repository: what the page reads is cached in
`build\mania_work\editor\`.

Checked in the running game (2.20, one stage each): the chosen banana is golden in the stage and taking it
completes the third mission on the result screen; Select Stage shows Mania's thumbnails and the three stamps with
the set numbers; Select World shows Mania's course pictures and the chosen theme's big picture; the Missions menu
lists the imported worlds that have missions with the set values, while its overall percentage stays the game's
own; a world without a title card; uploaded pictures as a stage's thumbnail (a file and one taken from the
view), a world's small picture and its big picture; a stage picture taken in the game from an editor view
(st1008: same framing as the preview, Sunset background, shown in Select Stage). A world icon, borrowed or uploaded, was not found on any
screen: the title cards seen (the theme of World 3) do not show one. Not looked at: the time and banana missions
completed in play (only the golden one was), perfect marks, split screen and online with missions, other
languages.

## Testing

`python mania\tools\try_stage.py <course> <stage>` (or `st<Mania stage number>`) starts the built game, walks
the menus into that stage (it reads the UI state lines of `port.log` to know where the menus are), holds the stick
forward, sends further input lines (`--input "WAIT 2000;GOAL;A"`) and saves pictures of the window. It uses the
save profile `T` (`--profile`), not the real save, and ignores the real keyboard, mouse and controllers
(`BR_NO_REAL_INPUT`), so the PC can be used meanwhile; dragging the game's window still stalls it.

Live input commands that make checks possible without playing a stage (`port\runtime\test_aids.c`, see
`docs\TECHNICAL.md`): `GOAL` (the local player's ball enters the goal: results, progress, what follows the last
stage of a world), `WHEEL`, `HOLD` / `MOVE` / `RELEASE`.

What was checked in the running game (2.00, one PC):

* stages: SMB1 Beginner 1 played to the goal; Diamond, Wide Bridge, Steps, Blocks (moving parts), Switches (both
  switches, the bridge is crossed), Conveyers (the belt pushes the ball), Linear Seesaws (the plank tilts);
  a 12-stage sample across courses loaded without a crash. Most of the 392 stages have never been started;
* the last stage of an imported world returns to the stage select of the next world;
* online, two instances: the imported worlds are in the host's world picker, a locked Rumble world is not;
  SMB1 Beginner stages 1 to 4 cleared in sequence by both players;
* music: the right cue sheet and stream are opened for a stage, with either soundtrack (heard by nobody).

## What is not converted

* What a green or a red goal does (skipping stages): every goal ends the stage; only its colour is kept.
* Mania's own model of the wormhole: Rumble's stands there.
* A seesaw inside another seesaw (three stages), the camera distance area of st1110, the manager's scroll on
  the unlit belts of st1069.
* Of Mania's backgrounds: weather, distortion and the mirror images on scenery (see "Backgrounds"). The stage intro
  graphics and the big picture of a course in the world picker are a Rumble world's (the one chosen in the
  editor, else the one in `WORLD_OF_BG`).
* A stage's lit materials are reduced to a texture, a tint, culling and (cut-out) the alpha threshold on three
  Rumble shaders; which of the three is read from the pass state and tags of Mania's shader (`background.py`,
  `describe`). Its unlit materials (`Custom/TextureVc`, `TextureVa`: arrows, marks) go on `bg_unlit_abd` with a
  baked copy of the mesh, as the backgrounds do, because the Rumble stage shaders take transparency only from
  the texture and those materials have it in the colour and the vertex alpha. On the lit ones vertex colours, second textures,
  rim light ramps and scrolling textures are dropped. Three things about them:
  a see-through lit material whose colour has an alpha below one (the glass sheet over the Masters floors, 0.5)
  gets that alpha in the vertices of a mesh copy, or it is drawn solid (that was the white glare on Masters);
  a floor that mirrors a cubemap in Mania (Space, Ice, Storm) gets a little gloss on the lit shader
  (`MIRROR_SMOOTHNESS`, `MIRROR_METALLIC` in `stage.py`; more gloss puts a glare spot on it); and an additive layer
  that is a moving texture times a still mask is drawn as the mask, standing still (`MASK_AS_ALBEDO`: the glow
  lines of the Space floors, which without the mask were a white sheet).
* The guide line, rotten / golden banana layouts, half-time and checkpoint flags of the
  courses, stage start animations (`OnReadyGo`).
* `import_report.txt` in `game\mania\` lists per stage what it has and which components were skipped.
