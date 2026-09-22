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

// ---- ambient light sensor (#44 -- auto-dimming) -------------------------
// Provisional: sized for a generic small I2C breakout's sensing window
// (e.g. a BH1750), not a specific module yet -- #44 hasn't settled on
// one. Revisit diameter/position once it has. Through the right side
// wall, near the front edge so the panel and the box's own depth don't
// shadow it, at half the enclosure's height.
sensor_hole_d      = 6;
sensor_inset_front = 8;   // mm back from the open front face

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
    // Drilled through the right wall. rotate([0,90,0]) maps the
    // cylinder's local +z (its extrusion axis) onto global +x, so it
    // must start 1mm before the wall's inner face to fully clear both
    // faces after the wall + 2mm cylinder length.
    translate([outer_w - wall - 1, outer_h / 2, outer_d - sensor_inset_front])
        rotate([0, 90, 0])
            cylinder(h = wall + 2, d = sensor_hole_d, $fn = 32);
}

difference() {
    union() {
        shell();
        panel_ledge();
        pi_standoffs();
    }
    sensor_hole();
}
