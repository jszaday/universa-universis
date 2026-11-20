# TODO

Open work for the rev. 1 (beta) revision. Priorities: P0 security, crash or data loss; P1 blocker; P2 important; P3 later. Items that depend on the PCB say "on the rev1 PCB branch" (`rev1/pcb`, not yet merged). Electrical design: `docs/rev1-spec.md`.

## P1

- PCB routing is unfinished. Current behaviour: about 45 connections remain as ratsnest lines (unrouted straight-line connections) on the rev1 PCB branch (18 address-jumper links, 10 matrix column links, a few I2C, interrupt, reserved-pin and power links), so the board fails the design rule check (DRC) only with unconnected items. Trigger: before ordering the board.
- Teardrops (tapered pad-to-track joints) are missing near changed tracks. Current behaviour: stale teardrop zones near changed tracks were removed on the rev1 PCB branch and none were added. Regenerate them in KiCad (Edit > Teardrops). Trigger: after routing is finished.

## P2

- ISO Enter switch position (`MX_ENTR1`) is suspected off by about half a key in some direction (the Alpha known issue in `README.md`). Current behaviour: not moved in rev. 1. Trigger: the director checks the physical board for direction and amount; the rev1-beta tag must not be created before this is answered.
- Numpad plus and Enter switches (`MX_KPPLS2`, `MX_KPENT1`) are still rotated -90 degrees. Current behaviour: unchanged; a +90 degree flip detaches 4 more pad connections and needs re-routing. Trigger: after routing, try the flip and confirm it against a donor plate.
- Donor labels: 34 positions have 2-4 overlapping switch footprints and no per-donor silkscreen. Current behaviour: no labels. Needs the director's donor-to-footprint mapping; scheme `<DONOR>-<LAYOUT>` (for example `AEK-ISO`, `AT101W`) plus the cell's diode reference. Trigger: the mapping is supplied.
- First-board bench checks, none done yet: diode forward drop against the extender's input-low limit (about 0.4 V against 0.66 V at 3.3 V; inference only, not measured), I2C rise times on the seam cables, and the GPA7/GPB7 pin limit (the MCP23017 datasheet contradicts itself: the features list says output-only, the pin table says bidirectional; the firmware validator takes the stricter reading). Trigger: the first board is assembled.
- Firmware: `firmware/matrix_config.h` is a two-chip placeholder; the real per-chip pin table is in `docs/rev1-spec.md` and must be transcribed. The QMK glue file `firmware/matrix.c` has never been compiled against QMK. On AVR the I2C speed must be set in the keyboard config. Trigger: before the first board is flashed.
- Service strips: the Nav, F-nav and Numpad strips are 28 mm (two rows of parts) on the rev1 PCB branch instead of the spec's 14 mm, because three IDC ports (ribbon-cable connectors) plus a socket do not fit in one row. Clearance against donor cases is unmeasured, and the jumper and IDC placement on the strips is provisional. Trigger: donor case measurements are taken.

## P3

- LED carrier board: rev. 1 provides only a 4-pin header (power plus three active-low lock-LED lines, with 470 ohm resistors on the board); the carrier may be built on perfboard. Trigger: donor LED positions and colours are known.
- Mounting holes are deliberately not added in rev. 1. Trigger: a case or mounting approach is chosen.
- `fkb-109j-big/fkb-109j-big.kicad_prl` is tracked and rewritten on every KiCad open. Recommend untracking it and adding it to `.gitignore`. Trigger: next housekeeping commit.
- The upstream mouse-bite footprint repository has no licence text; `umu.pretty/umu_mouse-bite-5mm-slot.kicad_mod` records its origin in its description. Trigger: settle before publishing.
- Seven back-side diodes cannot share the common rotation (7 at 0 degrees, 2 at 180 degrees) because both pads had to stay put on the rev1 PCB branch. Cosmetic only.
- Rev. 0 back-side legends (C13..C00, R1-R5) are relics that the diode silkscreen marks overlap. Tidy when touching silkscreen next.
- The schematic and PCB are in KiCad 10 format and will not open in older versions. Trigger: a collaborator needs an older version.
- Unmeasured: Alps housing dimensions and donor plate and case dimensions (ISO Enter cutout, numpad cutout axis, AT101 blank, switch pins, plate-to-PCB gap). Trigger: a donor board is on the bench.
