#!/usr/bin/env bash
# Version-bump and render the enclosure OpenSCAD models (see CLAUDE.md,
# "Enclosure (OpenSCAD) changes").
#
#   scripts/enclosure.sh bump [major|minor]   # default minor: 3.5 -> 3.6
#   scripts/enclosure.sh render               # PNG beside each .scad
#   scripts/enclosure.sh stl                  # printable parts beside each .scad
#   scripts/enclosure.sh all [major|minor]    # bump, then render and stl
#
# case_version is printed on the part (version_label in the .scad) and is
# kept identical across every model file, so one bump covers all of them.
set -euo pipefail

cd "$(dirname "$0")/../enclosure"
models=(scoreboard-case-v3.scad scoreboard-case-v3-pi3b.scad legs/scoreboard-legs.scad)

current_version() {
    local v
    v=$(sed -n 's/^case_version = "\([0-9]*\.[0-9]*\)";.*/\1/p' "$1")
    [ -n "$v" ] || { echo "no case_version in $1" >&2; exit 1; }
    echo "$v"
}

bump() {
    local kind=${1:-minor} cur new m
    cur=$(current_version "${models[0]}")
    for m in "${models[@]}"; do
        [ "$(current_version "$m")" = "$cur" ] ||
            { echo "case_version differs between model files; fix by hand first" >&2; exit 1; }
    done
    case "$kind" in
        minor) new="${cur%.*}.$((${cur#*.} + 1))" ;;
        major) new="$((${cur%.*} + 1)).0" ;;
        *) echo "usage: $0 bump [major|minor]" >&2; exit 2 ;;
    esac
    for m in "${models[@]}"; do
        sed -i "s/^case_version = \"$cur\";/case_version = \"$new\";/" "$m"
    done
    echo "case_version $cur -> $new"
}

render() {
    local m
    for m in "${models[@]}"; do
        if [ "$m" = legs/scoreboard-legs.scad ]; then
            # The legs standing under a stand-in for the case, seen from below.
            openscad -D 'part="preview"' -o "${m%.scad}.png" --imgsize=1600,600 \
                --camera=0,0,0,115,0,25,0 --viewall --autocenter \
                --colorscheme=Tomorrow "$m" >/dev/null 2>&1
        else
            # Front, tilted so the open face, the Pi side and the ceiling all show.
            openscad -o "${m%.scad}.png" --imgsize=1600,600 \
                --camera=0,0,0,-20,-20,0,0 --viewall --autocenter \
                --colorscheme=Tomorrow "$m" >/dev/null 2>&1
        fi
        echo "rendered ${m%.scad}.png"
    done
}

# The printable parts of each model beside it, as <model>-<side>.stl: the case
# is too wide for the bed, so it is two halves; the legs are one leg (print
# four). The case is mounted turned over (180 degrees about the front-back
# axis, see enclosure/README.md), so the file names are AS MOUNTED: the model's
# `part="left"` half (with the Pi) is saved as -right.stl, and `part="right"`
# as -left.stl. Exported in parallel; a failed export fails the script.
stl() {
    local m part parts pids=() pid
    for m in "${models[@]}"; do
        if [ "$m" = legs/scoreboard-legs.scad ]; then parts="leg"; else parts="left right"; fi
        for part in $parts; do
            side=$part
            if [ "$m" != legs/scoreboard-legs.scad ]; then
                if [ "$part" = left ]; then side=right; else side=left; fi
            fi
            openscad -D "part=\"$part\"" -o "${m%.scad}-$side.stl" "$m" >/dev/null 2>&1 &
            pids+=($!)
        done
    done
    for pid in "${pids[@]}"; do
        wait "$pid" || { echo "STL export failed" >&2; exit 1; }
    done
    echo "exported STLs for: ${models[*]}"
}

case "${1:-}" in
    bump)   bump "${2:-minor}" ;;
    render) render ;;
    stl)    stl ;;
    all)    bump "${2:-minor}"; render; stl ;;
    *) echo "usage: $0 {bump [major|minor]|render|stl|all [major|minor]}" >&2; exit 2 ;;
esac
