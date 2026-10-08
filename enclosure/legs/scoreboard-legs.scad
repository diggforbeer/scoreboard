// NHL Scoreboard retro legs (enclosure/legs/) -- 70s-style splayed, tapered furniture legs
// to glue under the case after printing.
//
// Each leg is a square glue plate (its flat top face goes against the
// case's bottom wall) and a round tapered leg that splays outward on the
// diagonal, with a ferrule band near the foot and a flat foot so it stands
// square on the floor. All four legs are the same part rotated 90deg, so
// print four of the one STL.
//
// Orientation (assembled): z=0 is the case's bottom face, the legs hang
// down (-z), x is the case's width, y its depth.
//
//   part = "preview"  the legs under a slab standing in for the case
//   part = "leg"      ONE leg, glue face down on the bed (this is what to print)
//   part = "set"      four legs laid out on one bed
//
// Prints with no supports: plate down on the bed, the leg leans out at only
// `splay` degrees from vertical.

part = "preview";

// ---- version label ------------------------------------------------------------
// Raised text on the plate's edge. Bumped by scripts/enclosure.sh together
// with the case files; never edit by hand.
case_version = "3.12";
label_size   = 3.2;
label_raise  = 0.6;

// ---- the case these go under (from scoreboard-case-v3.scad: outer_w, outer_d) --
// Update if the case's outside size changes.
case_w = 326.8;
case_d = 67.4;
case_bottom_t = 2.4;   // only used by the preview slab

// ---- legs ----------------------------------------------------------------------
total_h   = 100;   // floor to the case's bottom face
plate_w   = 28;    // square glue plate
plate_t   = 5;
plate_r   = 4;     // plate corner radius
inset_x   = 15;    // plate's outer edge in from the case's end
inset_y   = 3;     // plate's outer edge in from the case's front/back edge
splay     = 8;     // degrees out from vertical, on both axes (diagonal)
top_d     = 24;    // leg diameter where it meets the plate
foot_d    = 14;    // leg diameter at the floor
ferrule_d = 17.6;  // diameter of the band near the foot

leg_h   = total_h - plate_t;
offset  = leg_h * tan(splay);   // how far the foot sits out from the top, per axis
$fn     = 64;

// Leg profile as [t, diameter]: t runs 0 (plate) to 1 (foot). The ferrule is
// the raised band; consecutive discs are hulled into a smooth taper.
function taper(t) = top_d + (foot_d - top_d) * t;
profile = [
    [0.00, taper(0.00)],
    [0.76, taper(0.76) + 0.4],
    [0.79, ferrule_d],
    [0.88, ferrule_d],
    [0.91, taper(0.91) + 1],
    [1.00, foot_d],
];

module disc(t, d) {
    translate([offset * t, offset * t, -plate_t - leg_h * t])
        cylinder(h = 0.01, d = d);
}

module shaft() {
    for (i = [0 : len(profile) - 2])
        hull() {
            disc(profile[i][0],   profile[i][1]);
            disc(profile[i+1][0], profile[i+1][1]);
        }
}

module plate() {
    translate([0, 0, -plate_t])
        linear_extrude(height = plate_t)
            offset(r = plate_r) square(plate_w - plate_r * 2, center = true);
}

// The version, raised on the plate's -y edge (reads left to right when you
// look at that face from outside).
module label() {
    translate([0, -plate_w / 2, -plate_t / 2])
        rotate([90, 0, 0])
            linear_extrude(height = label_raise)
                text(str("v", case_version), size = label_size, halign = "center",
                     valign = "center", font = "Liberation Sans:style=Bold");
}

module leg_assembled() {
    plate();
    label();
    shaft();
}

// One leg flipped so the glue face is on the bed (z=0) and the foot is up.
module leg_printable() {
    rotate([180, 0, 0]) leg_assembled();
}

// ---- layout under the case --------------------------------------------------------
leg_x = case_w / 2 - inset_x - plate_w / 2;
leg_y = case_d / 2 - inset_y - plate_w / 2;

module legs_under_case() {
    for (sx = [1, -1]) for (sy = [1, -1])
        // each leg splays toward (+,+); rotate it so it splays outward
        translate([sx * leg_x, sy * leg_y, 0])
            rotate([0, 0, sx > 0 ? (sy > 0 ? 0 : 270) : (sy > 0 ? 90 : 180)])
                leg_assembled();
}

module preview() {
    color("#bbbbbb", 0.6)
        translate([-case_w / 2, -case_d / 2, 0])
            cube([case_w, case_d, case_bottom_t]);
    color("#c8873a") legs_under_case();
}

// ---- output -----------------------------------------------------------------------
if (part == "preview") {
    preview();
} else if (part == "leg") {
    leg_printable();
} else if (part == "set") {
    for (i = [0 : 3])
        translate([(i % 2) * (plate_w + offset + 20), floor(i / 2) * (plate_w + offset + 20), 0])
            leg_printable();
}
