# Costumes and extra characters: working notes

For whoever adds another costume, outfit or character model. These are the notes from adding the six classic
monkeys of Banana Mania's "Classic Character Pack" as the "Classic Outfit" item: everything learned on the way,
including the dead ends, so the next piece of work starts from the right place. The code is in `mania\classic\`
(`classic_chara.py`, `classic_outfit.py`) and `port\runtime\classic.c`; `mania\build.py` runs it as part of the
Banana Mania import.

Rule that shaped everything: the game's own files are never modified. New and changed data goes in an override
tree (`game\mania\`) that the runtime reads first.

## 1. How the game builds a character

* **Prefabs.** Each character has four per-context prefabs in
  `aa\Switch\chara_model_assets_chara\model\<NN><name>\`: `<NN>01…MainGame`, `<NN>02…Selector` (menus),
  `<NN>05…Ghost`, `<NN>06…IngameLight`. Each is a full copy of the hierarchy with its own renderers. The prefab
  `chara_cmn_assets_data\chara\model\<NN><name>Base.prefab` is never instantiated; editing it does nothing.
* **Meshes and materials** of a character are in `manual_additions_assets_design\chara\ch_00N_<name>.bundle`
  (the "design bundle"), shared by the four prefabs. Characters 1-7 are AiAi, MeeMee, Baby, GonGon, YanYan,
  Doctor, Palette.
* **Hierarchy.** Root > up to three detail levels (`ch_00N_<name>_body`, `…_LOD`, `…_LOD2`), each with its own
  skeleton copy (`Hips > Spine > Chest > Head`, arms `Shoulder/UpperArm/LowerArm/Hand_L|R` with four fingers,
  legs `UpperLeg/LowerLeg/Foot/Toes_L|R`, `TailRoot`) and a `model` node with the renderers. Bone names are the
  same in every prefab and detail level; the lower levels lack finger bones.
* **Renderers.** `ch_00N_cstm_body01`, `…_cstm_hand01`, `…_cstm_shoes01` are costume slots. The head is eight
  expression sets (`headNN`, `faceNN`, `mouthNN` under `FaceNN_Base`) switched by `CharaFace`, plus `ch_00N_ear`
  and the hair tuft. Attach points for worn items are transforms such as `ch_00N_cstm_head02..05`,
  `…_cstm_face02/03`, `…_cstm_back01`.
* **Space.** Rumble faces +Z, left is -X, about 0.7 units tall, bones have X along the bone. The prefab's stored
  pose is the bind pose (a mesh's bind pose for a bone is the inverse of that bone's world matrix in the prefab).
* **Shader.** `Chara/ch_lit_toon` (bundle `manual_additions_assets_design\shaders\ch_lit_toon.shader.bundle`):
  `_BaseMap`, `_NormalMap`, `_SpecularMap`, two shadow tints `_ToonColor1/2`, `_ToonScale/_ToonOffset`, rim and
  specular terms. The build has no alpha-clip or blended variant of it (no game material uses one).
* **Mesh layout** of the game's character meshes: stream 0 position, normal, tangent (float); stream 1 uv0
  (half) and uv1 (float); stream 2 four weights (float) and four bone indices (uint32); 16-bit indices; each
  stream starts on a 16-byte boundary. `classic_chara.write_mesh` writes this.

## 2. How the costume system works

* **Component.** `Wonder.CharaCustomizeAssetAssign` sits on each detail-level root. It keeps one "datum" per
  asset category: `MeshDatum` (replaces a renderer's mesh) or `PrefabDatum` (attaches a prefab at an attach
  point). `Set(asset, flag)` finds the datum whose category equals the asset's and calls Revert then Replace.
* **Asset.** `Wonder.CharaCustomizeAssetData` (a ScriptableObject, one per item, part and character, e.g.
  `body001c01_body01_ch01.asset`). Serialized fields, in order: `m_CharaID` (int), `m_AssetCategoryID` (int; 21 is
  body01), `m_Prefab` (PPtr), `m_Mesh` (PPtr), `m_BoneNameArray` (strings), `m_MaterialArray` (PPtrs).
* **Applying a mesh** (`MeshDatum.onReplace`): remembers the renderer's own mesh, bones and materials once, sets
  the asset's mesh and materials, and builds the renderer's bone array by looking up the asset's bone names in
  that detail level's skeleton. So a costume mesh may use any bones, in any order, as long as the names exist.
  A character's default body is itself such an asset (`body001c01`), with 22 bones including `Head` and the hands.
* **What it does not do.** It never touches the head, face, mouth, ear or hair renderers, and an outfit without
  hand or shoe assets leaves the default hands and shoes on. Anything that must disappear under a full-body
  replacement has to be hidden by the port (section 6).
* **Items.** An item belongs to a category (1 Headwear, 2 Facial Wear, 3 Clothes, 4 Back, 5 Handwear,
  6 Footwear, 7 Outfit, 8 Ball, 9 Effect) and lists up to ten asset records; an asset record lists one asset per
  character slot. An Outfit is the category for sets that span several parts (Banana Suit = body, hand, head,
  shoes assets).

## 3. Database tables

Tables are `MonoBehaviour` objects without type trees; UnityPy gives the raw bytes (`get_raw_data`). After the
object header and name: an int count, then the records. Every record ends with two ints: an "empty" flag (1 for
an unused id) and an order index (-1 when empty). Field lists come from the IL2CPP metadata
(`tools\il2cpp_meta.py`, class `Wonder.DB.<…>.RawRecord`).

| Table | Where | Record |
|---|---|---|
| `CharaCustomize_Item` | hash-named bundle at the top of `aa\Switch` (was encrypted) | 24 ints: id, name id, explanation id, colour id, category id, sprite id, is-default, initial condition, 10, ten asset-record ids, season id, season step, not-in-coordinate, empty, order |
| `CharaCustomize_Item_Text_<lang>` | hash-named bundles, 11 languages | id, name string, explanation string, empty, order |
| `CharaCustomize_Asset` | `db_assets_db\characustomize_asset.asset.bundle` | id, 8, eight asset references (each three strings: GUID, sub-object name, sub-object type), empty, order |
| `UI_Sprite` | `db_assets_db\ui_sprite.asset.bundle` | id, one asset reference, empty, order |
| `Unlock_Subject_CharaCustomizeItem` | `db_assets_db\…` | id, terms id, item id, condition id, notice id, DLC id (not needed for an owned item) |

* Strings are int length + UTF-8 bytes, padded to four bytes.
* The item table has 60 unused ids (10-50, 56, 180-192, 196, 442, 447, 544, 545); the Classic Outfit uses 544.
  The text tables may carry left-over text for an unused id. The sprite table has about 2000 unused ids.
* Initial condition: 5 on the nine "Default …" items, 1 and 3 on items that must be bought or unlocked, 4 on one
  item (Resort Outfit). An item added with 4 appeared as owned straight away, including in an existing save.
* Asset record slot 0 is unused, slots 1-7 are the characters. Empty slots are normal (many game items lack an
  asset for some character); the Classic Outfit leaves Palette's empty.
* To find which hash-named bundle holds a table, scan the top-level bundles for the object name
  (`classic_outfit.db_bundle` does this and caches the result).

## 4. Addressables catalog

`aa\catalog.json` (Addressables 1.x JSON format); `port\assets\aacatalog.py` reads and extends it and documents
the binary layout. What matters:

* A bundle is an entry with provider `AssetBundleProvider`, an `AssetBundleRequestOptions` JSON in the extra
  data (`m_BundleName`, `m_BundleSize`, `m_Crc` 0), listed under its primary key
  (`<group>/<path>_<hash>.bundle`) and, when assets depend on it together with other bundles, under a
  dependency key.
* An asset is an entry with provider `BundledAssetProvider`, internal id = the asset path stored in the bundle's
  container, listed under its address and its GUID, with a dependency key whose bucket lists the bundles to
  load: its own bundle first, then the others (for a costume asset: design bundle, mesh bundle, shader bundle).
* A sprite is two entries with the same keys, one typed `Texture2D` and one `Sprite`.
* The game reads `settings.json` and the catalog through the port's file layer, so `classic_fs_override`
  (`imports_fs.c` > `classic.c`) can hand it another catalog.
* Internal ids start with `{UnityEngine.AddressableAssets.Addressables.RuntimePath}/Switch/…`; a new bundle
  given such an id is looked for under `aa\Switch\…`, which the bundle-load hook maps to `game\mania\Switch\…`.

## 5. Making bundles with UnityPy

There is no Unity editor in the loop, so new bundles are copies of game bundles with objects rewritten in place:

* Typed objects (Mesh, Material, Texture2D, AssetBundle, renderers) through `read_typetree` / `save_typetree`;
  `MonoBehaviour` data through `get_raw_data` / `set_raw_data`.
* The costume code reuses existing objects: a Mesh object of the design bundle becomes the new mesh, its Material
  and Texture2D objects become the new materials and textures. (Objects can also be added: `mania\unityfile.py`,
  written later for the stage import, does it by copying an object record of the same class.)
* **Internal names.** Two loaded bundles may not contain a file with the same internal (CAB) name. A copy that is
  loaded beside its original needs new names: `classic_outfit.rename_cab` (rename the entries of
  `env.file.files` and each file's `.name`). Point references at it by editing `externals[i].path`
  (`archive:/CAB-x/CAB-x`) and the AssetBundle object's `m_Dependencies`, `m_Container` path and `m_PreloadTable`.
* **Textures.** `Texture2D.set_image(img, target_format=RGBA32, mipmap_count=1)` stores the picture inline.
  Orientation needs no flip. Keep textures square (a non-square one with generated mips did not render, cause
  not pinned down). The Windows player cannot use the Switch ASTC formats anyway.
* **Meshes.** Clear `m_StreamData`, write vertex data inline, set `m_BindPose`, `m_BoneNameHashes` (CRC32 of the
  bone's path below the skeleton's parent, e.g. `Hips/Spine`), `m_BonesAABB`, sub-meshes and bounds.
* Save with `env.file.save(packer='lz4')`.
* Git Bash heredocs mangle backslashes and quotes in generated code: write patch scripts with a file tool.

## 6. What the Classic Outfit adds (the working recipe)

Files: `mania\classic\classic_chara.py` (fitting a foreign model to Rumble's rig), `classic_outfit.py` (assets,
catalog, tables, icon), `port\assets\aacatalog.py`, `port\runtime\classic.c`, `mania\classic\make_hand_poser.py`.

1. **Fit the model** (`classic_chara.fit`): skin the foreign mesh into its own rest pose, turn it to Rumble's
   facing, move it so the neck joints coincide, shift limb joints onto Rumble's joints (blended by the skin
   weights), map each foreign bone to a Rumble bone by name (`BONE_MAP`) and merge the weights per Rumble bone.
   The head is bound to `Head` only. Body and head go into one mesh.
2. **One pack bundle per character**: the design bundle's copy, renamed, holding the new mesh, materials and
   textures. **One costume asset bundle per character**: a copy of that character's `body001c01` asset bundle,
   renamed, whose asset points at the pack (mesh, bone names, materials).
3. **Catalog**: bundle entries for both, an asset entry under a new address and GUID, a dependency bucket
   (asset bundle, pack, design bundle, shader bundle).
4. **Tables**: an appended asset record with the GUIDs, an unused item record filled in (category 7), text in
   every language table, an unused sprite record for the icon.
5. **Icon**: a copy of a ball item's icon bundle (its sprite outline covers nearly the whole 256 x 256 picture;
   outfit icons have tight outlines that would crop a new picture) with the picture replaced.
6. **Runtime** (`classic.c`): load overrides from `game\mania\`; while a body renderer carries a mesh named
   `classic_*`, take the meshes off the character's other skinned renderers and put them back afterwards. The
   costume calls `Set`, `Revert` and `RevertAll` are hooked only to trigger a re-check.

To add another full-body outfit the same way: give the mesh a name the runtime can recognise (or extend the
check), pick another unused item id, and add its entries beside the classic ones. An ordinary costume that keeps
Rumble's head needs no runtime code at all: a body asset with Rumble's proportions is enough.

Looks, in the order they were got right:

* **Eyes.** The foreign eye textures are alpha decals above the face. Without a cut-out shader they are baked
  opaque: each transparent texel takes the colour of the surface behind it (ray cast from the decal into the
  model), and the decal's vertices take the normals of the skin under them (`bake_transparent`).
* **Shading.** Reusing Rumble materials as they are gives mismatched tints (the costume material's shadows are
  blue, for denim). A flat neutral set was rejected as unshaded. What was accepted: every material takes the
  settings of that character's own `ch_00N_body_mat`, with normal and specular maps dropped.
* **Hands.** Binding five straight classic fingers to Rumble's four finger chains tears them. The hand is bound
  to the hand bone as one piece and posed beforehand. The pose comes from `mania\classic\classic_hands.json`,
  made with the page `make_hand_poser.py` writes (`hand_poser.html`); the pose
  arithmetic exists twice, in `classic_chara.finger_pose` and in the page's `poseMatrices`, and must stay equal.
  Doctor has no finger bones and is left out on purpose.

## 7. Dead ends

* **Editing the "Base" prefab**: no effect, the game spawns the per-context prefabs. This cost the most time,
  because the meshes in the shared design bundle did change, so the game showed Rumble's body wearing the new
  textures and every guess about "the game overriding materials" was wrong. Log what the game has before
  theorising (section 8).
* **Replacing the character's bundles through a per-character switch** (Options rows, bundle paths redirected):
  worked, but needed a restart (the game loads all character bundles once at start), broke with any costume
  equipped, and was not what the user wanted. Removed in favour of the outfit item.
* **New roster characters**: not attempted. It would mean new records in every table keyed by character id
  (definition, parameters, placement, face icons, unlocks, costume parameters, texts) with hard crashes on any
  miss, since the game is built without null checks.
* **Bringing over the other game's animations or shaders**: not possible. Rumble's animator has its own state
  set, and the shaders are built for another pipeline.
* **Reversing triangles or flipping textures** "because it looked inside out": both were wrong reactions to the
  Base-prefab mistake. The foreign meshes use the same winding and texture orientation.

## 8. Test loop

* **Offline, seconds**: `classic_hand.py` (hand close-ups), `classic_chara.py build <name>` +
  `classic_view.py <name> out.png` (whole character from built bundles; it draws the game's own character
  correctly with `orig`, so it can be trusted for what the files say; its front view is mirrored).
* **Spawn dump, about a minute, no screenshots**: `BR_CHARA_DUMP=<name part or *>` logs every renderer of each
  spawned character with its mesh, material slots and textures after the game's set-up code has run;
  `BR_CHARA_DUMP_EXIT=1` ends the run after the first match. This is the tool that found the real cause.
* **Screenshots, about 100 s**: `port\runtime\run_player.sh` with `BR_INPUT_SCRIPT`, and
  `port\tools\shot_window.ps1`. Routes (timings drift by seconds; take several shots):
  * title `30000 A`, play style `58000 A`, main menu at about 69 s (tags: Adventure, Battle, Style, Shop,
    Missions, Memories, Options);
  * Style > Outfit: `72000 RIGHT, 72800 RIGHT, 74500 A`, then six `R` from 82000, 0.9 s apart; `DOWN`, `RIGHT`
    reach the Classic Outfit, `A` equips;
  * character screen: `72000 A, 78000 A, 86000 X`, then `RIGHT` per character, `ZR` zooms;
  * a stage: `72000 A, 78000 A, 84000 A`.
* A headless browser can screenshot a local tool page:
  `msedge --headless=new --enable-unsafe-swiftshader --screenshot=out.png file:///…`.
* Test runs write to the real save in `game\save` (equipped items, dismissed dialogs, missions). Use a test
  profile (`BR_PROFILE`) or copy it first.

## 9. Open items

* Only AiAi was seen wearing the Classic Outfit in the game (Style menu and the first Adventure stage); the
  other five were seen in the earlier per-prefab build and in offline renders. Multiplayer, ghosts and the
  low-detail levels at a distance are untested.
* The classic face is static. The other game's bundles hold eye textures per expression (normal, joy, sad,
  angry, surprise, down, some with close); Rumble's eight face sets could be mapped to them.
* Other body, hand and shoe items do not show while the outfit is worn. A glove equipped and removed while
  wearing it restores the hand mesh the runtime remembered, not necessarily the one the costume system holds.
* One frame of Rumble's head may show when the outfit is put on (the hiding runs in a later update).
* The item name and description are English in every language.
* If `game\mania\` is removed while a save has the item equipped, the save refers to an item id that is
  empty again; what the game does then is untested.
