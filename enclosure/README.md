# Enclosure

OpenSCAD model for a 3D-printed case holding the Raspberry Pi and the
chained HUB75 panel(s) behind a shared front frame.

`scoreboard-case.scad` is a first-pass shell: outer walls, a ledge the
panel(s) rest against from the front, and standoffs matching the Pi 4's
official mounting-hole spacing. **Cable, vent, and access holes aren't
modeled yet** -- next pass, once we know exactly where the panel's power
and HUB75 cables, and the Pi's USB-C/GPIO/HDMI ports, need to exit.

All the panel dimensions at the top of the file come from the spec sheet
in `CLAUDE.md`'s Hardware facts section, except `panel_depth`, which is
an estimate -- measure the real panel (PCB + connectors) and correct it
before printing a final version. `wall` (2.4mm) assumes a 0.4mm nozzle at
~6 perimeters; adjust to your printer/slicer if different.

```bash
# Preview
openscad enclosure/scoreboard-case.scad

# Render a still, e.g. for a quick visual check
openscad -o case.png --imgsize=1600,500 \
  --camera=162,42,300,0,0,0,600 --projection=ortho \
  enclosure/scoreboard-case.scad

# Export for printing
openscad -o case.stl enclosure/scoreboard-case.scad
```

Designed to print without supports: flat base (the back wall), no
overhangs beyond 45°, open front face.
