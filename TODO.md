# TODO

Open work for the rev. 1 (beta) revision. Priorities: P0 security, crash or data loss; P1 blocker; P2 important; P3 later. Items that depend on the PCB say "on the rev1 PCB branch" (`rev1/pcb`, not yet merged). Electrical design: `docs/rev1-spec.md`.

## P1

- PCB routing is unfinished: 13 nets are still open (25 unconnected items in the design rule check, DRC: MAIN_VCC 7 items; FROW_GND 3; U4_COL0, U4_COL6, MAIN_GND and MAIN_SCL 2 each; MAIN_SDA, U1_COL3 to U1_COL6, U6_NUM and Net-(D79-A) 1 each). Cause: the grid router's buses cage some chip pins. The fanout-first mode in `tools/route_regular.py` (chip pins routed before the buses) is not the default and is not a clear win: 7 buses fall back to the old order, it fixed U1_COL3, U1_COL4, U1_COL6 and U4_COL0 but left U1_COL5, U1_COL7, U1_COL10, U1_COL11, U4_COL5 and U6_COL1 open, vias rose from 31 to 69, and it takes about 11 minutes. The committed board is the previous one; the director hand-finishes the remaining nets in KiCad. Net-(D79-A) and the alternate pads in `tools/left_pads.txt` are deliberately unwired (see the ISO backslash item). Trigger: before ordering the board.
- `tools/pipeline.py` has never run end to end: the pour stage lacks the GND island join and the check stage lacks `tools/allowed_open.txt`; both stop with exit code 2 (`TODO(pipeline-gnd-join)`, `TODO(pipeline-allowed-open)`). Trigger: a rerouting of the whole board is wanted.

## P2

- ISO Enter switch position (`MX_ENTR1`) is suspected off by about half a key in some direction (the Alpha known issue in `README.md`). Current behaviour: not moved in rev. 1. Trigger: the director checks the physical board for direction and amount; the rev1-beta tag must not be created before this is answered.
- ISO backslash alternate `MX_BSLSH2` (1U at about x 163.5, y 119.1) shares cell D79 with the US `MX_BSLSH1` (about x 401.6, y 81.0), so its track would exceed 260 mm. Current behaviour: left unwired. Decision pending: give it its own matrix cell on the Main-L chip (U3, which has 4 spare lines) or leave it unwired. The same question applies to the other far alternates `MX_RALT2`, `RWIN1`, `RCTRL1`, `RCTRL2` and `KC1` in `tools/left_pads.txt`. Trigger: before the first board is ordered, or a donor that needs one of them.
- Bus connector: the baseline is the plain unkeyed 1x04 header, but the spec recommends the keyed Molex KK-254 (`docs/rev1-spec.md` section 5, reversal analysis). Current behaviour: plain header on the PCB. Trigger: director decision; if adopted, re-check header fit on every piece.
- Numpad plus and Enter switches (`MX_KPPLS2`, `MX_KPENT1`) are still rotated -90 degrees. Current behaviour: unchanged; a +90 degree flip detaches 4 more pad connections and needs re-routing. Trigger: after routing, try the flip and confirm it against a donor plate.
- First-board bench checks, none done yet: diode forward drop against the extender's input-low limit (about 0.4 V against 0.66 V at 3.3 V; inference only, not measured), I2C rise times on the cables, a continuity check of the F-nav cable path between J27 and J28 (no netlist check can see the cable), back-side part height against donor cases, and the GPA7/GPB7 pin limit (the MCP23017 datasheet contradicts itself: the features list says output-only, the pin table says bidirectional; the firmware validator takes the stricter reading). Trigger: the first board is assembled.
- Firmware: `firmware/matrix_config.h` is a two-chip placeholder; the real per-chip pin table is in `docs/rev1-spec.md` and must be transcribed. The QMK glue file `firmware/matrix.c` has never been compiled against QMK. On AVR the I2C speed must be set in the keyboard config. Trigger: before the first board is flashed.

## P3

- LED carrier board: rev. 1 provides only a 4-pin header (power plus three active-low lock-LED lines; the series resistors are off-board in the LED harness, `docs/rev1-spec.md` D9); the carrier may be built on perfboard. Trigger: donor LED positions and colours are known.
- Teardrops (tapered pad-to-track joints) are missing. Current behaviour: stale teardrop zones were removed on the rev1 PCB branch and none were added. The director adds them in KiCad (Edit > Teardrops). Trigger: after routing is finished.
- KiCad silkscreen warnings, and four `lib_footprint_mismatch` footprints (`MX_ROPT1`, `MX_MENU1`, `MX_LWIN1`, `MX_LOPT1`) that differ from the library. Current behaviour: reported by DRC, no electrical effect. Trigger: next silkscreen pass.
- Rev2 (punted by the director; not part of rev1): donor labels. 34 positions have 2-4 overlapping switch footprints and no per-donor silkscreen. Current behaviour: no labels. Needs the director's donor-to-footprint mapping; scheme `<DONOR>-<LAYOUT>` (for example `AEK-ISO`, `AT101W`) plus the cell's diode reference. Trigger: rev2 planning, with the mapping supplied.
- Mounting holes are deliberately not added in rev. 1. Trigger: a case or mounting approach is chosen.
- The upstream mouse-bite footprint repository has no licence text; `umu.pretty/umu_mouse-bite-5mm-slot.kicad_mod` records its origin in its description. Trigger: settle before publishing.
- Back-side diodes are not in one orientation (102 at 90 degrees, 7 at 0, 2 at 180) because both pads had to stay put on the rev1 PCB branch. Cosmetic only.
- Rev. 0 row and column legends (R1-R5, C0-C20) are to be removed from the PCB silkscreen; not yet done. Current behaviour: they remain and the diode silkscreen marks overlap them. Trigger: next silkscreen pass.
- The schematic and PCB are in KiCad 10 format and will not open in older versions. Trigger: a collaborator needs an older version.
- Unmeasured: Alps housing dimensions and donor plate and case dimensions (ISO Enter cutout, numpad cutout axis, AT101 blank, switch pins, plate-to-PCB gap). Trigger: a donor board is on the bench.
