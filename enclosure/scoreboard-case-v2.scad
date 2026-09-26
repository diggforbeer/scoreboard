// NHL Scoreboard enclosure -- holds a Raspberry Pi (3 Model B+ or 4), the power
// brick, two upward-firing speakers and the HUB75 LED panel(s) behind a
// shared front frame.
//
// Orientation: z=0 is the back wall (Pi side); the front (z=outer_d) is
// fully open so the panel's LED face shows through. y=0 is the BOTTOM of
// the case. Prints flat, back face down -- no supports needed.
//
// Layout, left to right (looking at the back, inside the bay):
//   ceiling:  L speaker                                   R speaker
//   bay:      (sensor on L wall) | Pi | open | brick ▐ socket out R wall
//
// Too wide for a 256mm bed in one piece, so it splits at the seam between
// the two real panels (set `part` below), or cut the full STL in the
// slicer instead.

part = "all";  // "all" (preview), "left", "right"

// ---- panel (from the purchased spec sheet, CLAUDE.md Hardware facts) --
panel_w    = 160;  // mm, one panel
panel_h    = 80;   // mm
panel_count = 2;   // chained horizontally, matches PanelConfig.chain_length
panel_gap  = 0;    // mm between chained panels, if any
// Not on the spec sheet -- measure the real panel (PCB + connectors) and
// correct this before printing for a final fit.
panel_depth = 15;

// ---- Raspberry Pi 3 Model B+ / 4 Model B (official mechanical spec) ----
// Both boards share the same outline and hole pattern, so one mount fits
// either.
// Holes sit 3.5mm in from the edge OPPOSITE the USB/Ethernet ports (not
// centered on the board) -- the ports overhang past the last hole column.
pi_w            = 85;
pi_h            = 56;
pi_hole_dx      = 58;  // mounting hole spacing
pi_hole_dy      = 49;
pi_hole_inset_x = 3.5; // from the non-port short edge
pi_hole_inset_y = 3.5;
pi_hole_d       = 2.7; // M2.5
pi_standoff_h   = 6;   // clearance under the board for underside components
pi_standoff_d   = 6;

// ---- speakers (ceiling, firing up) --------------------------------------
// Placeholder: no driver picked yet -- generic 40mm round driver. Each
// driver sits against the inside of the top wall and fires up through a
// slightly smaller port so its rim has something to glue/clamp to. One
// in each top corner, mirrored.
speaker_d       = 40;  // driver outer diameter
speaker_depth   = 18;  // driver depth incl. magnet -- how far it hangs down
speaker_hole_d  = speaker_d - 4;
speaker_wall_margin = 2.5; // solid wall kept around the driver, front/back
speaker_side_inset  = 3;   // gap from driver rim to the side wall

// ---- ambient light sensor (#44/#45 -- auto-dimming) ---------------------
// BH1750 over I2C, sized generically. Left side wall, vertically centred
// (the top-left corner belongs to the left speaker), at bay depth.
sensor_hole_d = 6;

// ---- power brick (listing: 125 x 55 x 31; sized up a little) -------------
// Lies flat against the back wall, lengthwise, long edge on the case floor,
// IEC C14 socket end hard against the right wall. The socket is exposed
// through a cutout in the right wall so a straight C13 cord plugs straight
// in from outside. DC cable exits the other end, toward the middle.
brick_l   = 128;
brick_w   = 56;   // height in the case (y)
brick_t   = 32;   // thickness (z, off the back wall)
brick_clr = 0.5;  // seat clearance per side

// Socket position on the brick's end face -- MEASURED GUESS from the
// product photo: the C14 inlet looks centred on the end face both ways.
// Offsets are from the face centre; refine once the brick is in hand.
socket_off_y = 0;  // + = toward the top of the case
socket_off_z = 0;  // + = away from the back wall
// Right-wall cutout around the socket -- sized to clear a straight C13
// plug body (~33 x 23mm) with a little room.
power_open_h = 45; // along y (the brick's 55mm width)
power_open_d = 26; // along z (the brick's 31mm thickness)
power_open_r = 3;  // corner radius

// Brick seat, all inside: the floor and right wall do most of the work.
// At the DC end, an L-shaped corner stop at the bottom and top corners;
// at the right-wall end, a short cap over the top edge. Together they
// trap the brick in x and y; the panel in front keeps it off the ledge.
seat_h     = 12;   // how far the stops stand off the back wall
seat_t     = 2.4;
seat_tab_w = 8;    // tab length along the brick's edges

// ---- vent slits (back wall, behind the Pi) -------------------------------
vent_count = 6;
vent_w     = 2.5;  // mm slit width
vent_pitch = 5;    // mm, centre-to-centre vertically
vent_angle = 15;   // degrees of tilt
// Slits fit horizontally BETWEEN the two standoff columns, with this much
// solid wall left between each slit end and the nearest standoff edge,
// so the back wall stays stiff around the screw bosses.
vent_standoff_margin = 3;
vent_span = pi_hole_dx - pi_standoff_d - vent_standoff_margin * 2; // usable width
// Slit length whose tilted, round-ended outline spans exactly vent_span.
vent_len = (vent_span - vent_w) / cos(vent_angle) + vent_w;  // ~47.5mm
vent_keepout_d = pi_standoff_d + 3; // never cut under a standoff

// ---- enclosure -----------------------------------------------------------
wall = 2.4;  // ~6 perimeters at a 0.4mm nozzle
lip  = 4;    // how far the front ledge overlaps the panel edge, each side
// The bay must fit both the brick (plus a little air) and a ceiling
// speaker driver with solid wall in front of and behind it.
electronics_clearance = max(brick_t + 3, speaker_d + speaker_wall_margin * 2);

total_panel_w = panel_w * panel_count + panel_gap * (panel_count - 1);
inner_w = total_panel_w;
inner_h = panel_h;
inner_d = electronics_clearance + panel_depth;

outer_w = inner_w + wall * 2;
outer_h = inner_h + wall * 2;
outer_d = inner_d + wall;  // one wall (back) -- front stays open

// z where the panel's back face sits -- the ledge holds it here
panel_seat_z = wall + electronics_clearance;
bay_mid_z    = wall + electronics_clearance / 2;

// Split at the real seam between panel 1 and panel 2.
split_x = wall + panel_w;

// ---- placement (derived) --------------------------------------------------
// Speakers: mirrored in the two top corners.
spk_xs = [wall + speaker_side_inset + speaker_d / 2,
          outer_w - wall - speaker_side_inset - speaker_d / 2];

// Pi: just right of the left speaker (it hangs lower than the Pi's top
// edge), vertically centred. Ports face right, toward open space.
pi_x0 = wall + speaker_side_inset + speaker_d + 5;
pi_y0 = wall + (inner_h - pi_h) / 2;
pi_hole_xs = [pi_x0 + pi_hole_inset_x, pi_x0 + pi_hole_inset_x + pi_hole_dx];
pi_holes = [for (x = pi_hole_xs) for (dy = [0, pi_hole_dy])
                [x, pi_y0 + pi_hole_inset_y + dy]];

// Brick: socket end against the right wall.
brick_x1    = outer_w - wall - brick_clr;      // socket end face
brick_x0    = brick_x1 - brick_l;              // DC end face
brick_y0    = wall;                            // on the floor
brick_top_y = brick_y0 + brick_w + brick_clr;
socket_y    = brick_y0 + brick_w / 2 + socket_off_y;
socket_z    = wall + brick_t / 2 + socket_off_z;

// ---- modules ----------------------------------------------------------------
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
    for (h = pi_holes)
        translate([h[0], h[1], wall])
            difference() {
                cylinder(h = pi_standoff_h, d = pi_standoff_d, $fn = 32);
                cylinder(h = pi_standoff_h + 1, d = pi_hole_d, $fn = 32);
            }
}

module brick_seat() {
    xd = brick_x0 - brick_clr;   // DC end (seat side)
    translate([0, 0, wall]) {
        // DC end: upright stop at each corner...
        for (y = [brick_y0, brick_top_y - seat_tab_w])
            translate([xd - seat_t, y, 0])
                cube([seat_t, seat_tab_w, seat_h]);
        // ...plus a cap over the top edge, making an L at the top corner.
        translate([xd - seat_t, brick_top_y, 0])
            cube([seat_tab_w + seat_t, seat_t, seat_h]);
        // Right-wall end: cap over the top edge, tied into the wall.
        translate([outer_w - wall - seat_tab_w, brick_top_y, 0])
            cube([seat_tab_w, seat_t, seat_h]);
    }
}

module sensor_hole() {
    // Left wall, vertically centred, at bay depth.
    // rotate([0,90,0]) maps local +z onto global +x.
    translate([-1, outer_h / 2, bay_mid_z])
        rotate([0, 90, 0])
            cylinder(h = wall + 2, d = sensor_hole_d, $fn = 32);
}

module speaker_holes() {
    // Through the top wall; rotate([-90,0,0]) maps local +z onto global +y.
    for (x = spk_xs)
        translate([x, outer_h - wall - 1, bay_mid_z])
            rotate([-90, 0, 0])
                cylinder(h = wall + 2, d = speaker_hole_d, $fn = 64);
}

module power_opening() {
    // Right wall, centred on the brick's C14 socket. Rounded rectangle in
    // the y-z plane, extruded along +x through the wall.
    translate([outer_w - wall - 1, socket_y, socket_z])
        rotate([0, 90, 0])            // local x -> -z, local y -> y, local z -> +x
            linear_extrude(height = wall + 2)
                offset(r = power_open_r)
                    square([power_open_d - power_open_r * 2,
                            power_open_h - power_open_r * 2], center = true);
}

module vents() {
    // Rounded-end slits through the back wall, centred between the two
    // standoff columns (so they end short of the screw bosses on both
    // sides) and tilted by vent_angle. Printed back-face-down these are
    // plain vertical through-holes, so no supports.
    cx = (pi_hole_xs[0] + pi_hole_xs[1]) / 2;
    cy = pi_y0 + pi_h / 2;
    translate([0, 0, -1])
        linear_extrude(height = wall + 2)
            difference() {
                for (i = [0 : vent_count - 1])
                    translate([cx, cy + (i - (vent_count - 1) / 2) * vent_pitch])
                        rotate(vent_angle)
                            hull() {
                                translate([-(vent_len - vent_w) / 2, 0]) circle(d = vent_w, $fn = 24);
                                translate([ (vent_len - vent_w) / 2, 0]) circle(d = vent_w, $fn = 24);
                            }
                for (h = pi_holes)
                    translate(h) circle(d = vent_keepout_d, $fn = 32);
            }
}

module body() {
    difference() {
        union() {
            shell();
            panel_ledge();
            pi_standoffs();
            brick_seat();
        }
        sensor_hole();
        speaker_holes();
        vents();
        power_opening();
    }
}

// ---- output -----------------------------------------------------------------
if (part == "all") {
    body();
} else if (part == "left") {
    intersection() {
        body();
        translate([-1, -1, -1]) cube([split_x + 1, outer_h + 2, outer_d + 2]);
    }
} else if (part == "right") {
    intersection() {
        body();
        translate([split_x, -1, -1]) cube([outer_w - split_x + 1, outer_h + 2, outer_d + 2]);
    }
}
