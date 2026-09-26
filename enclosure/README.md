# Enclosure

OpenSCAD models for a 3D-printed case holding the Raspberry Pi and the
chained HUB75 panel(s) behind a shared front frame. Two versions live
here side by side rather than one file overwriting the other, since
they're genuinely different iterations (see below) and the second one
hasn't fully superseded the first in-repo yet.

## `scoreboard-case.scad` (v1)

The original shell: outer walls, a ledge the panel(s) rest against from
the front, standoffs matching the Pi 4's official mounting-hole spacing,
a side-wall ambient-light-sensor hole (#44/#45), and a speaker port in
each side wall (driver still unpicked, so these are generic round holes,
not a grille cut for a specific model). No power-brick seat, no venting
beyond the two speaker holes, and no print-bed splitting -- it's sized
for whatever bed the full width happens to fit on.

## `scoreboard-case-v2.scad`

A larger redesign: adds a power-brick bay with an IEC C14 socket cutout
through the right wall (so a straight C13 cord plugs in from outside),
moves the speakers to the ceiling firing upward instead of through the
side walls, relocates the sensor to the left wall, and adds tilted vent
slits through the back wall behind the Pi -- the first real attempt at
the airflow question #49 raises, not just component-clearance holes.
Also supports the Pi 3 Model B+'s mounting pattern in addition to the
Pi 4's (they share the same hole spacing). Too wide for a typical 256mm
print bed in one piece, so it splits into left/right halves at the seam
between the two chained panels -- set the `part` variable near the top
of the file to `"all"` (preview), `"left"`, or `"right"`.

Several dimensions are still placeholders pending real parts in hand:
`speaker_d`/`speaker_depth` (no driver picked), and the power brick's
socket position (`socket_off_y`/`socket_off_z`, a measured guess from a
product photo) -- refine both once the actual parts are available to
measure.

## Shared conventions

All panel dimensions at the top of each file come from the spec sheet in
`CLAUDE.md`'s Hardware facts section, except `panel_depth`, which is an
estimate -- measure the real panel (PCB + connectors) and correct it
before printing a final version. `wall` (2.4mm) assumes a 0.4mm nozzle at
~6 perimeters; adjust to your printer/slicer if different. Both print
without supports: flat base (the back wall), no overhangs beyond 45°,
open front face.

```bash
# Preview
openscad enclosure/scoreboard-case-v2.scad

# Render a still, e.g. for a quick visual check
openscad -o case.png --imgsize=1600,500 \
  --camera=162,42,300,0,0,0,600 --projection=ortho \
  enclosure/scoreboard-case-v2.scad

# Export for printing (v2: repeat with part = "left" / "right" if your
# bed can't take the full width in one piece)
openscad -o case.stl enclosure/scoreboard-case-v2.scad
```
