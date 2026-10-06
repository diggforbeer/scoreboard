# Enclosure

OpenSCAD models for a 3D-printed case holding the Raspberry Pi and the
chained HUB75 panel(s). There is one design, **v3**, in a Pi 4 and a
Pi 3 Model B+ variant. Earlier iterations (v1, v2) were removed; they
remain in git history.

## `scoreboard-case-v3.scad` / `scoreboard-case-v3-pi3b.scad` (current)

A rework after printing and fitting the earlier v2 design. The two files are identical
except for `pi_model` (`4` or `3`), which only changes the port
faceplate -- the Pi 3 Model B+ has its Ethernet and USB jacks in swapped
positions. The board variant and `case_version` are printed as raised
text on the inside of the back wall, along with the repo URL, so a
printed case can be matched to its source; bump `case_version` with
every design change.

What changed from v2:

- **Power brick moves outside.** Having it inside blocked access to the
  Pi. A 21mm hole low on the left wall takes a panel-mount 5.5mm barrel
  jack (nut inside, flange outside) that feeds the matrix hat.
- **Pi against the right wall**, USB/Ethernet end out through a port
  faceplate -- one rounded opening per jack with solid columns between,
  so an external USB speaker can plug straight in. The board sits 5mm
  off the floor (the 3.5mm audio jack overhangs its bottom edge ~3mm).
  Standoffs are cones (10mm base, 6mm top) so they don't snap off.
  Tilted vent slits through the back wall behind it (#49).
- **Magnetic panel mounting.** The panels' own magnetic screws land on
  16mm steel washers glued into pads on the top and bottom walls; the old
  ledge is gone and the panel fronts sit flush with the case. Magnet
  positions were read from a photo of the panel backs -- the washers are
  oversized to absorb a couple of mm of error. The two bottom magnets of
  the right panel that would sit over the Pi/hat have no pad (unscrew the
  bottom-middle one). A half-circle finger notch in each side wall's
  front edge helps pull the panels off.
- **Light sensor (#44/#45)** on the left wall: the GY-302/BH1750 board
  slides into rails from the open front, chip facing a 6mm window, until
  it hits a stop. The chip-side step is trimmed to 0.8mm (`bh_step_ov`)
  so a part near the board edge doesn't catch.
- **Push button (#50)**, 7mm, on the right wall above the faceplate.
- **Speaker grilles (#114)** in the ceiling, now between the magnet pads.
  Still sized for a placeholder 40mm driver (`speaker_d`/`speaker_depth`).
- **Bolted seam.** Still two halves split at the panel seam (`part` =
  `"left"` / `"right"`), now joined by a 5mm internal U-flange on each
  half (back, top and bottom walls) with five M3 bolts -- heads on the
  left half, nuts captured in hex pockets on the right. Nothing crosses
  the cut, so each half is one clean solid for the slicer.

Hardware: 5x M3x10 socket-head bolts + nuts (seam), 4x M2.5 screws (Pi),
10x ~16mm steel washers (magnet pads), panel-mount 5.5mm barrel jack
(21mm hole), 7mm momentary button.

Still open: the speaker grille's hole size/pitch (generic until a real
driver is picked), and confirming the magnet
positions and right-panel stability on a full print.

## Shared conventions

All panel dimensions at the top of each file come from the spec sheet in
`CLAUDE.md`'s Hardware facts section. earlier versions' `panel_depth` was an
estimate; v3 uses the measured panel thickness (`panel_t`, 15mm) and the
panel + magnet-screw depth (`mag_total_t`, 27mm). `wall` (2.4mm) assumes a 0.4mm nozzle at
~6 perimeters; adjust to your printer/slicer if different. Both print
without supports: flat base (the back wall), no overhangs beyond 45°,
open front face.

Every design change bumps `case_version` and regenerates the preview
images (`scoreboard-case-v3.png`, `scoreboard-case-v3-pi3b.png`) and the
printable STLs (`*-left.stl`, `*-right.stl`), all beside the models, with
`scripts/enclosure.sh all` -- see `CLAUDE.md`. The STLs are ready to slice
as they are; they match the `case_version` printed on the part.

```bash
# Preview
openscad enclosure/scoreboard-case-v3.scad

# Render a still, e.g. for a quick visual check
openscad -o case.png --imgsize=1600,500 \
  --camera=162,42,300,0,0,0,600 --projection=ortho \
  enclosure/scoreboard-case-v3.scad

# Export the two printable halves
openscad -D 'part="left"'  -o case-left.stl  enclosure/scoreboard-case-v3.scad
openscad -D 'part="right"' -o case-right.stl enclosure/scoreboard-case-v3.scad
```
