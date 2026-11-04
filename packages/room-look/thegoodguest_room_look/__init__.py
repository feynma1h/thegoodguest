"""The room look: everything that turns a scan into a finished, furnished room.

Pure Python over numpy and Pillow, no cloud and no network, so the same code
runs from the command line (the scripts in tools/ are wrappers over it) and
inside services/scene-finish.

  shell_finish      derive a wall and floor finish from a scan (finish.json)
  shell_atlas       rectified wall and floor atlases, median over frames
  shell_measure     colour measurement over an atlas
  shell_structure   baseboard, wainscot and similar edges found in an atlas
  finish_hints      the closed vocabulary a reviewer's hints must fit
  finish_compare    pose the viewer's camera at a real frame, compare renders
  furniture_boxes   boxes.json: where each boxed object stands
  furniture_geometry, furniture_clearance, furniture_placement
                    placing a twin on its box by rule, and the fixes it made
  furniture_models  build furniture.json from boxes and spec files
  furniture_evidence, furniture_compare
                    pick the frames that show a piece, compare render to photo
"""
