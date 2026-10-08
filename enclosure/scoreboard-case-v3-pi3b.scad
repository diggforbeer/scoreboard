// NHL Scoreboard enclosure v3 (Pi 3 Model B+ faceplate) -- holds a Raspberry Pi 3 Model B+
// with an RGB matrix hat, two upward-firing speakers and the two chained
// HUB75 panels, which snap onto steel washers with their own magnetic
// screws.
//
// Changes from v2: the power brick lives outside now (a panel-mount 5.5mm
// barrel jack in the left wall feeds the hat); the Pi's USB/Ethernet end
// sits against the right wall behind a port faceplate; the sensor moves to
// the left wall; the panel ledge is gone -- magnet pads set the
// panels' depth instead; the speakers move inboard between the magnets.
//
// Orientation: z=0 is the back wall; the front (z=outer_d) is open and the
// panels' LED faces sit flush with it. y=0 is the BOTTOM of the case.
// Left/right are as seen from the front. Prints flat, back face down.
//
// Layout, left to right:
//   ceiling:               L speaker                       R speaker
//   bay:  L wall: jack  |  open  |  Pi ▐ ports + button, R wall; top: sensor
//
// Too wide for a 256mm bed in one piece, so it prints as two halves split
// at the seam between the two panels (set `part`). Each half has an
// internal flange along its cut edge (back, top and bottom walls); the
// halves bolt together through them with M3 bolts and nuts -- nothing
// crosses the cut, and nothing shows from outside.

part = "all";  // "all" (preview), "left", "right"

// ---- version label ------------------------------------------------------------
// Raised text on the inside of the back wall in the Pi half: the repo and
// the case revision, plus the board variant. Bump case_version with every
// change to the design so a printed case can be matched to its source.
case_version = "3.10";
repo_label   = "github.com/diggforbeer/scoreboard";
label_size   = 5;     // text height, mm -- bold strokes ~0.8mm+, printable with a 0.4mm nozzle
label_raise  = 0.8;   // how far the text stands off the wall

// ---- panels ---------------------------------------------------------------
panel_w     = 160;  // mm, one panel
panel_h     = 80;
panel_count = 2;    // chained horizontally, matches PanelConfig.chain_length
// Gap between the two panels. The seam flanges (and their bolts) sit in
// it, centred, so each half gets panel_gap / 2 of extra room at the seam
// and the panels' ends clear the flanges (measured: 3mm overlap per panel
// with no gap). Magnet pads are placed per panel from this, so each
// panel's pads stay aligned with its own magnets.
panel_gap   = 6;
panel_t     = 15;   // panel frame thickness, measured (no magnet screws)

// Magnetic screws (came with the panels) thread into the panel's M3 posts.
// Positions per panel, from its LEFT end as seen from the front, read off
// a photo against the product drawing -- the top row and bottom row are
// the same pattern rotated 180deg. Steel washers on printed pads catch
// them; the washers are bigger than the magnets so a couple of mm of error
// in these numbers doesn't matter.
mag_top_xs  = [16, 66, 141];
mag_bot_xs  = [16, 94, 144];
mag_edge    = 7.5;  // magnet centre in from the panel's top/bottom edge
mag_d       = 11.5;
mag_total_t = 27;   // panel + screwed-in magnet, front face to magnet face

// Steel washer each magnet lands on, pressed/glued into a pocket flush
// with the pad face. Any steel washer ~16mm across works. It's centred a
// touch further in than the magnet when needed so it clears the wall --
// still fully covers the magnet.
washer_d  = 16;
washer_t  = 1.2;
washer_off = max(mag_edge, washer_d / 2 + 0.5);  // washer centre from the panel edge
pad_t     = 4;      // pad slab thickness behind the washer
pad_w     = washer_d + 4;

// ---- Raspberry Pi 4 Model B / 3 Model B+ (official mechanical spec) -----
// Same outline and hole pattern on both. Holes sit 3.5mm in from the edge
// OPPOSITE the USB/Ethernet ports. Mounted with the GPIO header (and hat)
// along the top edge, ports facing the right wall.
pi_w            = 85;
pi_h            = 56;
pi_hole_dx      = 58;
pi_hole_dy      = 49;
pi_hole_inset_x = 3.5;
pi_hole_inset_y = 3.5;
pi_hole_d       = 2.7; // M2.5
pi_standoff_h   = 6;
pi_standoff_d   = 6;   // top diameter, where the board sits
// Standoffs taper out to a wide base (a cone, like a pyramid) so they
// don't snap off at the back wall.
pi_standoff_base_d = 10;
pi_pcb_t        = 1.4;
pi_port_gap     = 0.5; // board edge to the inside of the right wall
pi_floor_gap    = 5;   // board's bottom edge above the floor -- the 3.5mm audio
                       // jack overhangs that edge by ~3mm, so this leaves ~2mm under it

// Port faceplate in the right wall: one opening per jack, with solid
// columns between. Centres are from the board's bottom (HDMI) edge, per
// the official mechanical drawings -- the 3B+ has Ethernet and USB
// swapped, so pick the board here.
pi_model = 3;   // 4 or 3 (3 Model B+)
usb_w = 13.1;  usb_h = 16;     // double-stacked USB-A
eth_w = 16;    eth_h = 13.5;   // RJ45
// [centre, width, height] for each port
ports = pi_model == 4
    ? [[9.0,   usb_w, usb_h], [27.0, usb_w, usb_h], [45.75, eth_w, eth_h]]
    : [[10.25, eth_w, eth_h], [29.0, usb_w, usb_h], [47.0,  usb_w, usb_h]];
port_margin = 0.75;  // clearance around each jack
port_r      = 1;     // corner radius

// ---- speakers (ceiling, firing up) ----------------------------------------
// Placeholder 40mm driver. Each sits in the gap between the 2nd and 3rd
// top-row magnets of its panel, firing up through a grille.
speaker_d       = 40;
speaker_depth   = 18;  // how far it hangs down from the ceiling
speaker_hole_d  = speaker_d - 4;
speaker_wall_margin = 2.5;
grille_hole_d   = 3;
grille_pitch    = 4.5;

// ---- power jack (left wall), light sensor (top wall), button (right wall) ---
// Power jack: 22mm hole for the panel-mount connector, centred top to bottom
// on the left wall. Its nut goes on from inside, so there must be room for
// the nut (and room to turn it) above the bottom-left screen mount's pad,
// which reaches pad_depth up the wall; an assert below checks that. Nut size
// is an assumption (no measurement yet): change jack_nut_d / jack_nut_room if
// it needs more.
jack_hole_d   = 22;
jack_nut_d    = 30;   // nut across its widest point, mm
jack_nut_room = 3;    // working room around the nut, mm
// jack_y (hole centre, from the outside bottom) is set below, once the
// magnet pads are defined.
// BH1750 (#44/#45) behind a 6mm window in the TOP wall, beside the left
// speaker's grille, held in rails (see sensor_mount). sensor_x is set below.
sensor_hole_d = 6;
sensor_grille_gap = 4;  // mm between the grille's edge and the rails
// 7mm momentary push button (#50) -- right wall, above the port faceplate
// and close to the back wall, so it clears the magnet pad above it.
button_hole_d = 7;
button_y      = 71;
button_z      = 12;

// Finger notch: a half-circle scooped out of the front edge of each side
// wall, so you can get a fingertip on the panel's edge to pull it off the
// magnets.
notch_r = 9;

// GY-302 breakout, measured: 13.9 x 18.5 x 1.6mm. The chip (3.0mm long)
// spans 2.5-5.5mm from the mounting-hole end, centred side to side. It
// slides into two rails from the open front, chip facing the wall, header
// end toward you, until its hole end hits a stop -- leaving the chip
// centred behind the sensor window.
bh_w = 13.9;
bh_l = 18.5;
bh_t = 1.6;
bh_chip_from_hole_end = 2.5 + 3.0 / 2;
bh_standoff  = 1.5;
bh_clr       = 0.25;
bh_slot_t    = bh_t + 0.3;
bh_rail_w    = 2;
bh_lip_t     = 1.2;
bh_lip_ov    = 1.2;  // how far the lip over the board's back face reaches in
// How far the step on the wall side (the chip side) reaches in under the
// board edge. Kept shallower than the lip: there's a small part near the
// GY-302's edge on the chip side that caught on a 1.2mm step.
bh_step_ov   = 0.8;
bh_header_keepout = 3;

// ---- vent slits (back wall, behind the Pi) -------------------------------------
vent_count = 6;
vent_w     = 2.5;
vent_pitch = 5;
vent_angle = 15;
vent_standoff_margin = 3;
vent_span = pi_hole_dx - pi_standoff_base_d - vent_standoff_margin * 2;
vent_len  = (vent_span - vent_w) / cos(vent_angle) + vent_w;  // ~43.4mm
vent_keepout_d = pi_standoff_base_d + 3;

// ---- seam flanges (join the two halves) ------------------------------------------
// M3 socket-head bolts from the left half, nuts captured in hex pockets in
// the right flange. With both flanges 5mm thick, an M3x10 bolt ends flush
// with the nut (M3x12 pokes out 2mm -- also fine).
flange_t     = 5;     // each flange's thickness (along x)
flange_w     = 10;    // how far the flange reaches in from the wall
flange_front_gap = 1; // stop this far behind the panels' back face
bolt_d       = 3.4;   // M3 clearance
nut_af       = 5.8;   // M3 nut across flats (5.5) + clearance
nut_depth    = 2.6;
// Bolt spots, as [y, z]. The top/bottom ones sit forward (z=40) where a
// hex key can reach past the magnet pads; the back-wall ones are clear of
// the pads' gussets.
function seam_bolts() = [
    [wall + inner_h * 0.25 - 0.4, wall + flange_w / 2],  // back wall, low
    [outer_h / 2,                 wall + flange_w / 2],  // back wall, middle
    [outer_h - wall - 19.4,       wall + flange_w / 2],  // back wall, high
    [outer_h - wall - flange_w / 2, 40],                 // top wall
    [wall + flange_w / 2,           40],                 // bottom wall
];

// ---- enclosure -------------------------------------------------------------------
wall = 2.4;  // ~6 perimeters at a 0.4mm nozzle
// Bay behind the panels: fits a ceiling speaker with solid wall around it.
electronics_clearance = speaker_d + speaker_wall_margin * 2;

total_panel_w = panel_w * panel_count + panel_gap * (panel_count - 1);
inner_w = total_panel_w;
inner_h = panel_h;
inner_d = electronics_clearance + panel_t;

outer_w = inner_w + wall * 2;
outer_h = inner_h + wall * 2;
outer_d = inner_d + wall;

bay_mid_z    = wall + electronics_clearance / 2;
mag_face_z   = outer_d - mag_total_t;  // where the magnets touch the washers
split_x      = wall + panel_w + panel_gap / 2;  // middle of the gap

// ---- placement (derived) ---------------------------------------------------------
// Pi: ports end against the right wall, bottom edge near the floor (so the
// right speaker fits above it).
pi_x1 = outer_w - wall - pi_port_gap;
pi_x0 = pi_x1 - pi_w;
pi_y0 = wall + pi_floor_gap;
pi_hole_xs = [pi_x0 + pi_hole_inset_x, pi_x0 + pi_hole_inset_x + pi_hole_dx];
pi_holes = [for (x = pi_hole_xs) for (dy = [0, pi_hole_dy])
                [x, pi_y0 + pi_hole_inset_y + dy]];

// Magnet pads: [x, "top"|"bottom"] for every magnet, then drop any bottom
// pad that would land over the Pi/hat (its magnet just goes unused).
pad_depth = washer_off + washer_d / 2 + 2;   // how far a pad reaches in from its wall

// Power jack: centred top to bottom on the left wall; the nut and working
// room must clear the bottom-left pad.
jack_y = outer_h / 2;
assert(jack_y - jack_nut_d / 2 >= wall + pad_depth + jack_nut_room,
       "power jack nut would hit the bottom-left magnet pad");
all_pads = concat(
    [for (p = [0 : panel_count - 1]) for (x = mag_top_xs)
        [wall + p * (panel_w + panel_gap) + x, "top"]],
    [for (p = [0 : panel_count - 1]) for (x = mag_bot_xs)
        [wall + p * (panel_w + panel_gap) + x, "bottom"]]);
function over_pi(pd) = pd[1] == "bottom"
    && pd[0] + pad_w / 2 > pi_x0 - 2 && pd[0] - pad_w / 2 < pi_x1 + 2;
// The left panel's middle top pad is dropped: the light sensor and its rails
// take that spot on the top wall, beside the speaker grille. (That panel is
// held by its other five magnets.)
function dropped(pd) = pd[1] == "top" && abs(pd[0] - (wall + mag_top_xs[1])) < 0.01;
pads = [for (pd = all_pads) if (!over_pi(pd) && !dropped(pd)) pd];

// Speakers: midway between the 2nd and 3rd top-row magnets of each panel.
spk_xs = [for (p = [0 : panel_count - 1])
    wall + p * (panel_w + panel_gap) + (mag_top_xs[1] + mag_top_xs[2]) / 2];

// Light sensor: on the top wall, just left of the left speaker's grille. The
// rails reach bh_w/2 + bh_clr + bh_rail_w either side of the window.
sensor_half = bh_w / 2 + bh_clr + bh_rail_w;
sensor_x = spk_xs[0] - speaker_hole_d / 2 - sensor_grille_gap - sensor_half;
assert(min([for (pd = pads) if (pd[1] == "top") abs(pd[0] - sensor_x)]) >= pad_w / 2 + sensor_half,
       "light sensor rails would hit a top magnet pad");

// ---- modules ------------------------------------------------------------------------
module shell() {
    difference() {
        cube([outer_w, outer_h, outer_d]);
        translate([wall, wall, wall])
            cube([inner_w, inner_h, outer_d]);
    }
}

module pi_standoffs() {
    for (h = pi_holes)
        translate([h[0], h[1], wall])
            difference() {
                cylinder(h = pi_standoff_h, d1 = pi_standoff_base_d,
                         d2 = pi_standoff_d, $fn = 32);
                cylinder(h = pi_standoff_h + 1, d = pi_hole_d, $fn = 32);
            }
}

// One magnet pad: a slab reaching in from the top or bottom wall, its face
// at mag_face_z with a washer pocket centred on the magnet, and a 45deg
// gusset back to the wall underneath so it prints without supports.
module magnet_pad(x, side) {
    y_wall = side == "top" ? outer_h - wall : wall;   // inner face of that wall
    dir    = side == "top" ? -1 : 1;                  // into the case
    y_wsh  = y_wall + dir * washer_off;
    difference() {
        // slab + gusset, drawn as a y-z profile extruded along x
        translate([x - pad_w / 2, 0, 0])
            rotate([90, 0, 90])     // local x -> y, local y -> z, extrude along +x
                linear_extrude(height = pad_w)
                    polygon([[y_wall, mag_face_z],
                             [y_wall + dir * pad_depth, mag_face_z],
                             [y_wall + dir * pad_depth, mag_face_z - pad_t],
                             [y_wall, mag_face_z - pad_t - pad_depth]]);
        translate([x, y_wsh, mag_face_z - washer_t])
            cylinder(h = washer_t + 1, d = washer_d + 0.4, $fn = 48);
    }
}

module magnet_pads() {
    for (pd = pads) magnet_pad(pd[0], pd[1]);
}

// Round hole through the left wall at bay depth.
module left_wall_hole(y, d) {
    translate([-1, y, bay_mid_z])
        rotate([0, 90, 0])
            cylinder(h = wall + 2, d = d, $fn = 48);
}

// Sensor rails, drawn centred on y=0 against the RIGHT wall, then turned
// onto the top wall by sensor_mount().
module sensor_mount_right() {
    wall_in = outer_w - wall;
    x_face  = wall_in - bh_standoff;
    x_back  = x_face - bh_slot_t;
    x_outer = x_back - bh_lip_t;
    z_hole_end = bay_mid_z - bh_chip_from_hole_end;
    z_rail_top = z_hole_end + bh_l - bh_header_keepout;
    yb = -bh_w / 2;
    {
        for (s = [1, -1])
            scale([1, s, 1])            // bottom rail, then its mirror on top
                difference() {
                    translate([x_outer, yb - bh_clr - bh_rail_w, wall])
                        cube([wall_in - x_outer, bh_rail_w + bh_clr + bh_lip_ov,
                              z_rail_top - wall]);
                    translate([x_back, yb - bh_clr, wall - 1])
                        cube([bh_slot_t, bh_clr + bh_lip_ov + 1, z_rail_top - wall + 2]);
                    // trim the wall-side step back to bh_step_ov
                    translate([x_face - 0.01, yb + bh_step_ov, wall - 1])
                        cube([wall_in - x_face + 0.01, bh_lip_ov, z_rail_top - wall + 2]);
                }
        // stop under the board's hole end, bridging the rails
        translate([x_outer, yb - bh_clr - bh_rail_w, wall])
            cube([wall_in - x_outer, bh_w + (bh_clr + bh_rail_w) * 2,
                  z_hole_end - bh_clr - wall]);
    }
}
module sensor_mount() {
    // Turn 90deg about z so the right wall becomes the top wall, with the
    // board still sliding in from the open front, chip facing the wall.
    translate([sensor_x, outer_h, 0]) rotate([0, 0, 90])
        translate([-outer_w, 0, 0]) sensor_mount_right();
}

module port_faceplate() {
    // Right wall: a rounded opening per jack, each sitting on the board's
    // top surface, extruded along +x through the wall.
    board_top = wall + pi_standoff_h + pi_pcb_t;
    for (pt = ports) {
        w = pt[1] + port_margin * 2;
        h = pt[2] + port_margin * 2;
        translate([outer_w - wall - 1, pi_y0 + pt[0], board_top - port_margin + h / 2])
            rotate([0, 90, 0])        // local x -> -z, local y -> y, local z -> +x
                linear_extrude(height = wall + 2)
                    offset(r = port_r)
                        square([h - port_r * 2, w - port_r * 2], center = true);
    }
}

module button_hole() {
    translate([outer_w - wall - 1, button_y, button_z])
        rotate([0, 90, 0])
            cylinder(h = wall + 2, d = button_hole_d, $fn = 32);
}

module finger_notches() {
    // Axis along x through both side walls, centred on the front edge.
    translate([-1, outer_h / 2, outer_d])
        rotate([0, 90, 0])
            cylinder(h = outer_w + 2, r = notch_r, $fn = 64);
}

module speaker_grilles() {
    // Hex grid of holes clipped to the port circle, through the top wall.
    r   = speaker_hole_d / 2 - grille_hole_d / 2;
    n   = ceil(r / grille_pitch) + 1;
    row = grille_pitch * sqrt(3) / 2;
    for (x = spk_xs)
        translate([x, outer_h - wall - 1, bay_mid_z])
            rotate([-90, 0, 0])
                for (j = [-n * 2 : n * 2])
                    for (i = [-n : n]) {
                        px = i * grille_pitch + (j % 2 == 0 ? 0 : grille_pitch / 2);
                        py = j * row;
                        if (px * px + py * py <= r * r)
                            translate([px, py, 0])
                                cylinder(h = wall + 2, d = grille_hole_d, $fn = 16);
                    }
}

module vents() {
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

// One U-shaped flange (back + top + bottom bands) against the cut, on the
// side given by dir (-1 = left half, +1 = right half).
module seam_flange(dir) {
    z_front = outer_d - panel_t - flange_front_gap;
    x0 = dir < 0 ? split_x - flange_t : split_x;
    translate([x0, 0, 0]) {
        // back wall band
        translate([0, wall, wall]) cube([flange_t, inner_h, flange_w]);
        // bottom and top bands
        translate([0, wall, wall]) cube([flange_t, flange_w, z_front - wall]);
        translate([0, outer_h - wall - flange_w, wall])
            cube([flange_t, flange_w, z_front - wall]);
    }
}

module seam_bolt_holes() {
    for (b = seam_bolts()) {
        // clearance hole through both flanges
        translate([split_x - flange_t - 1, b[0], b[1]])
            rotate([0, 90, 0])
                cylinder(h = flange_t * 2 + 2, d = bolt_d, $fn = 24);
        // hex nut pocket opening onto the right flange's inner face;
        // rotate puts a vertex pointing up (+z) so it prints cleanly
        translate([split_x + flange_t - nut_depth, b[0], b[1]])
            rotate([0, 90, 0])
                cylinder(h = nut_depth + 1, d = nut_af / cos(30), $fn = 6);
    }
}

// Two left-aligned lines on the back wall, in the strip above the Pi
// (between the Pi's top edge and the top wall), starting just right of
// the seam flange. Nothing else touches the back wall there -- the right
// speaker and the magnet pads hang from the top wall and stay clear of it.
module version_label() {
    variant = pi_model == 3 ? "pi3b" : "pi4";
    lines = [repo_label, str("case v", case_version, " - ", variant)];
    x0 = split_x + flange_t + 4;
    strip_mid = (pi_y0 + pi_h + outer_h - wall) / 2;   // middle of the strip
    pitch = label_size * 1.6;
    for (i = [0 : len(lines) - 1])
        translate([x0, strip_mid + (0.5 - i) * pitch, wall])
            linear_extrude(height = label_raise)
                text(lines[i], size = label_size, halign = "left", valign = "center",
                     font = "Liberation Sans:style=Bold");
}

module body() {
    difference() {
        union() {
            shell();
            version_label();
            seam_flange(-1);
            seam_flange(1);
            pi_standoffs();
            magnet_pads();
            sensor_mount();
        }
        left_wall_hole(jack_y,   jack_hole_d);
        // sensor window through the top wall, same z as the speaker grilles
        translate([sensor_x, outer_h - wall - 1, bay_mid_z])
            rotate([-90, 0, 0])
                cylinder(h = wall + 2, d = sensor_hole_d, $fn = 48);
        button_hole();
        port_faceplate();
        finger_notches();
        seam_bolt_holes();
        speaker_grilles();
        vents();
    }
}

// ---- output -------------------------------------------------------------------------
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
