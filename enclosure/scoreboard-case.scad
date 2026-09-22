// NHL Scoreboard enclosure -- holds a Raspberry Pi 4 and the HUB75 LED
// panel(s) behind a shared front frame. Cable, vent, and mounting-access
// holes are deliberately NOT modeled yet -- this is a first-pass shell to
// confirm overall size before adding that detail.
//
// Orientation: z=0 is the back wall (Pi side); the front (z=outer_d) is
// fully open so the panel's LED face shows through. Prints flat, back
// face down, no overhangs beyond 45 degrees -- no supports needed.

// ---- panel (from the purchased spec sheet, CLAUDE.md Hardware facts) --
panel_w    = 160;  // mm, one panel
panel_h    = 80;   // mm
panel_count = 2;   // chained horizontally, matches PanelConfig.chain_length
panel_gap  = 0;    // mm between chained panels, if any
// Not on the spec sheet -- measure the real panel (PCB + connectors) and
// correct this before printing for a final fit.
panel_depth = 15;

// ---- Raspberry Pi 4 Model B (official mechanical spec) -----------------
pi_w            = 85;
pi_h            = 56;
pi_hole_dx      = 58;  // mounting hole spacing
pi_hole_dy      = 49;
pi_hole_inset_x = (pi_w - pi_hole_dx) / 2;
pi_hole_inset_y = (pi_h - pi_hole_dy) / 2;
pi_hole_d       = 2.7;
pi_standoff_h   = 6;   // clearance under the board for underside components
pi_standoff_d   = 6;

// ---- ambient light sensor (#44/#45 -- auto-dimming) ---------------------
// #45 landed a BH1750 over I2C -- still sized generically since the
// exact breakout board's dimensions aren't pinned down, but no longer a
// stand-in for an unknown part. Through the right side wall, near the
// top edge (moved down from centre to leave the wall's vertical middle
// clear for the speaker hole below) -- positioned at electronics-bay
// depth (behind panel_seat_z, not within the panel's own depth range)
// so the panel itself doesn't sit right in front of the hole.
sensor_hole_d = 6;
sensor_margin_top = 10;  // mm from the top edge to the hole centre

// ---- speaker holes (both sides) ------------------------------------------
// Provisional: no speaker driver picked yet, so this is a generic round
// port, not a grille cut for a specific model -- revisit once one's
// chosen. Centred vertically on each side wall (the sensor moved up to
// make room), same electronics-bay depth as the sensor so neither sits
// in front of the panel.
speaker_hole_d = 25;

// ---- enclosure -----------------------------------------------------------
wall = 2.4;  // ~6 perimeters at a 0.4mm nozzle
lip  = 4;    // how far the front ledge overlaps the panel edge, each side
electronics_clearance = 20;  // mm behind the panel(s) for the Pi + wiring

total_panel_w = panel_w * panel_count + panel_gap * (panel_count - 1);
inner_w = total_panel_w;
inner_h = panel_h;
inner_d = electronics_clearance + panel_depth;

outer_w = inner_w + wall * 2;
outer_h = inner_h + wall * 2;
outer_d = inner_d + wall;  // one wall (back) -- front stays open

// z where the panel's back face sits -- the ledge holds it here
panel_seat_z = wall + electronics_clearance;

module shell() {
    difference() {
        cube([outer_w, outer_h, outer_d]);
        // Hollow it out; extend past outer_d so the front is fully open
        // rather than leaving a thin front wall.
        translate([wall, wall, wall])
            cube([inner_w, inner_h, outer_d]);
    }
}

module panel_ledge() {
    // A step at panel_seat_z the panel(s) rest against from the front,
    // `lip` mm wide on each side -- keeps them from falling through to
    // the electronics bay.
    translate([wall, wall, panel_seat_z])
        difference() {
            cube([inner_w, inner_h, wall]);
            translate([lip, lip, -1])
                cube([inner_w - lip * 2, inner_h - lip * 2, wall + 2]);
        }
}

module pi_standoffs() {
    x0 = wall + (inner_w - pi_w) / 2 + pi_hole_inset_x;
    y0 = wall + (inner_h - pi_h) / 2 + pi_hole_inset_y;
    for (dx = [0, pi_hole_dx])
        for (dy = [0, pi_hole_dy])
            translate([x0 + dx, y0 + dy, wall])
                difference() {
                    cylinder(h = pi_standoff_h, d = pi_standoff_d, $fn = 32);
                    cylinder(h = pi_standoff_h + 1, d = pi_hole_d, $fn = 32);
                }
}

module sensor_hole() {
    // Drilled through the right wall, near the top edge, centered in the
    // electronics bay's depth (not the panel's) so the panel isn't
    // sitting right in front of the hole. rotate([0,90,0]) maps the
    // cylinder's local +z (its extrusion axis) onto global +x, so it
    // must start 1mm before the wall's inner face to fully clear both
    // faces after the wall + 2mm cylinder length.
    translate([outer_w - wall - 1, outer_h - sensor_margin_top, wall + electronics_clearance / 2])
        rotate([0, 90, 0])
            cylinder(h = wall + 2, d = sensor_hole_d, $fn = 32);
}

module speaker_hole(side) {
    // side = "left" or "right". Same rotate([0,90,0]) approach as
    // sensor_hole() -- local +z maps onto global +x, so the start x
    // differs by which face is being cut: 1mm outside the outer face on
    // the near side for the right wall, or 1mm outside the outer face on
    // the far (negative) side for the left wall.
    x0 = side == "right" ? outer_w - wall - 1 : -1;
    translate([x0, outer_h / 2, wall + electronics_clearance / 2])
        rotate([0, 90, 0])
            cylinder(h = wall + 2, d = speaker_hole_d, $fn = 48);
}

difference() {
    union() {
        shell();
        panel_ledge();
        pi_standoffs();
    }
    sensor_hole();
    speaker_hole("left");
    speaker_hole("right");
}
