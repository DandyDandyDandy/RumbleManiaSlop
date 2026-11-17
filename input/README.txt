Put your own files here, then run setup.cmd (one folder up).

  prod.keys             the key file of your own console (Lockpick_RCM writes it)
  the base game         Super Monkey Ball Banana Rumble as .xci (cartridge dump) or .nsp
  the 2.2.0 update      as .nsp
  add-on content        .nsp files, optional: every pack found here is installed
  mania.txt             optional, see below

File names do not matter; the setup looks inside the files. Compressed dumps (.nsz, .xcz) are not supported.
After the setup has finished, nothing in this folder is needed any more (but pictures\, see below).

Add-on content bought later: put its .nsp files here together with prod.keys and run  setup.cmd --only dlc
(the base game and the update are not needed for that).

Banana Mania (optional)
  When Super Monkey Ball Banana Mania (the Steam version) is installed on this PC, the setup finds it by itself and
  imports its stages, their music and the classic characters into the built game. To say where it is, or to leave
  something out, make a text file mania.txt here with any of these lines:

      path=C:\Program Files (x86)\Steam\steamapps\common\smbbm
      levels=no        do not import the stages
      music=no         import the stages without Banana Mania's music
      backgrounds=no   import the stages without Banana Mania's backgrounds (they get a Rumble world's scenery)
      classic=no       do not import the classic characters

  Changing mania.txt and running setup.cmd again redoes only the import.

Pictures of your own (optional)
  The level editor (editor.cmd) keeps the pictures you upload for stages and worlds in the folder pictures\ here.
  Every import reads them again, so keep the folder.

  The title screen: RumbleMania's own title pictures are in mania\title\. PNG files in a folder title\ here
  replace any of them, or other monkeys and logos of the title screen (names and sizes: run
  build\venv\Scripts\python.exe mania\title.py --export <folder> for the game's own pictures, and see the top of
  mania\title.py). Every import puts them in; mania\title.py alone does it in seconds.

Nothing in this folder is ever committed (see .gitignore). Do not share these files or the built game.
