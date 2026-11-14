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
of game version 2.0.0.

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
| `Stage_DoleDisposition` | per stage id: the sponsor logo under the start (read in `MainGameStage.Start` without a check). Imported stages get a row without a logo (`AssetRef` empty, `Num` 0, as seven of the game's own rows are): Mania's stages have their own start mark |
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
| `GOALnn` | the template's goal arch (first goal) or a copy of it, at the goal's place under the same parent, turned by 180 degrees |
| the Animator of `Collision` | an Animator (update mode 1) and a ReplayTracker on the `Collision` copy, with the carried-over controller and clips, listed in `m_StageAnimators` |
| `StageMovObjManager.m_info` (moving node -> its drawn twin), `MgTRSSync` (source -> targets) | Mania copies transforms every frame; here each target is hung **under** its source, keeping its place, so the one Animator moves the drawn parts and whatever rides on a moving part |
| nothing (Mania moves every collision part it finds under an animated node) | the tag `StgMot` on every object the clips move and on everything below it (below) |
| `CollisionBumper` (+ the model under the root's `bumpers`) | Rumble's `CollisionBumper` (same sphere, same push) and `MgBumper` |
| `MgStageSwitchManager`, `MgStageSwitch`, `CollisionSwitchUpper` | `MgStageSwitchController` on the `Collision` copy, `MgSwitch` and `CollisionSwitchUpper` on each switch (below) |
| `MgSeesaw {momentFactor, frictionFactor, restoreFactor, seeSawModel}` on a node above the seesaw's collision parts | `MgSeesaw` (same three factors), one merged `CollisionStagePart` and a `ReplayTracker` on that node (below) |
| `MgConveyer {m_StaticSpeed}` next to a `CollisionStagePart` | `MgConveyer` with the same speed vector next to the converted part |
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
any moving part. The belt's texture does not scroll (Mania's `MgConveyManager` is not converted).

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
switch's on / off clips are the game's own (`obj_com_switch_on` / `_off`, copied from World 3 Stage 1); the
switch model itself is drawn but does not move when pressed.

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
| `Stage`, `Stage_Text_<lang>`, `Stage_DoleDisposition` | a new row per stage (ids from 705): scene name, name, 60 or 30 seconds, the converted scenery and lighting scenes of its Mania background, the game's empty sky scene `sky05_w05`, no effect scene and no screen effect. Without backgrounds (`--no-backgrounds`, `backgrounds=no` in `input\mania.txt`, or a background that failed to convert): the scenery, sky, lighting and effect scenes of the Rumble world that stands in for the Mania background (`WORLD_OF_BG`) |
| `Stage_List_Group_wld97_wldtst` | every imported course's stages, one after the other |
| `Course`, `Course_Text_<lang>` | a row per course (ids from 27), category 6, always unlocked, no missions, hung on the end of the game's chain of Adventure worlds (below) |
| `MainGame_Story_Progress` | a row per stage that opens it |
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

**The intro fly-over.** Before a stage the camera flies between two points of a box (`BeginningBounds`:
`m_Bounds`, a begin and an end point given as a pivot on the box and a target, and one of three generic
timeline assets, `MainGame_Beginning`). The points are children of the box object, so they follow its
rotation. Rumble's stages run towards +Z and Mania's towards -Z; the import keeps the template's points, sets
the box to the stage's size and turns it half round, without which the fly-over looked away from the stage.
It is still one generic camera move for every stage (see `docs\ROADMAP.md`).

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
* Not converted: particle systems (storm fires and lightning, waterfall
  spray, cloud puffs), camera weather, flow-map distortion, flip-book animation (city lights of Night), toon ramp,
  rim light, specular and cube-map reflections, Mania's post-processing, the collision twin of four backgrounds.

### Runtime (`port\runtime\mania.c`, `classic.c`)

* the override folder: bundles under `aa\Switch\` are taken from `mania\Switch\` when they exist there, the
  catalog from `mania\catalog.json`, sound files from `mania\Sound\`;
* numeric scene names and virtual stage lists (above);
* `MainGameBg.calcBgCue` answers with the imported cue for an imported stage (`mania_music.txt`): Banana Mania's
  own music, or the Classic Soundtrack's when the import has it and the player chose it (Options > Display >
  Imported Stage Music, a row added in `display_opt.c`; kept in `port_mania.txt`);
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

* Wormholes (17 stages), jamabars (2: st1024, st1035): the objects are drawn and
  their collision is solid, but they do not act. Rumble has classes for wormholes and jamabars (`MgWormhole` /
  `CollisionWormholeGate`, `MgJamabar`); a wormhole there is a prefab of its own with a cubemap camera, particle
  renderers and a text, so it wants a whole object tree brought over from one of the game's stages, not just
  a script.
* Goal colours: every goal is Rumble's arch and ends the stage.
* Of Mania's backgrounds: particles, weather, distortion and reflections (see "Backgrounds"). The stage intro
  graphics and the course's look in the world picker are still those of the Rumble world in `WORLD_OF_BG`.
* A stage's lit materials are reduced to a texture, a tint, culling and (cut-out) the alpha threshold on three
  Rumble shaders; which of the three is read from the pass state and tags of Mania's shader (`background.py`,
  `describe`). Its unlit materials (`Custom/TextureVc`, `TextureVa`: arrows, marks) go on `bg_unlit_abd` with a
  baked copy of the mesh, as the backgrounds do, because the Rumble stage shaders take transparency only from
  the texture and those materials have it in the colour and the vertex alpha. On the lit ones vertex colours, second textures,
  rim light ramps, reflection cubes and scrolling textures are dropped.
* Stage pictures, missions, the guide line, rotten / golden banana layouts, half-time and checkpoint flags of the
  courses, stage start animations (`OnReadyGo`).
* `import_report.txt` in `game\mania\` lists per stage what it has and which components were skipped.
