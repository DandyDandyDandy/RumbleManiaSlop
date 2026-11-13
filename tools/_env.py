"""Folders for the analysis scripts (see port/paths.py)."""
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(REPO, 'port'))
import paths  # noqa: E402

W = str(paths.BUILD)            # W\work\... is the extracted game and the analysis outputs, W\generated the lifted C
GAME = str(paths.GAME)
# <Unity 2022.3.30f1>\Editor\Data: only the few scripts that compare the game with the engine's own files need it
UNITY_EDITOR = os.environ.get('UNITY_EDITOR_DATA', '')
