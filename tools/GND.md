# Ground pours and the last open nets

Scripts (KiCad's Python, KiCad closed): `gnd_pour.py` writes the pours and stitching vias, `gnd_islands.py` proposes extra vias where a filled pour is still split, `check_gnd.py` checks the result, `route_open.py` is the hand-controlled connector for open power, I2C and chip-pin nets. `netcheck.py` and `shortdet.py` are the researcher's net-rewrite and geometric-overlap tests (run with `python3 -I`; a script-written copper item that touches a foreign pad is silently re-netted by KiCad on load, so DRC alone cannot show it).

## What was done (director decisions)

- GND is a pour, not tracks: one zone on F.Cu and one on B.Cu for each of FROW_GND, MAIN_GND, NAV_GND, NUMPAD_GND (F-nav has no GND net). Each zone stays 1 mm inside its piece outline, 2 mm (plus the slot's own extent) from mouse-bite slots, 2 mm from the popout ring, 0.5 mm from other nets. Through-hole pads use KiCad's default thermal relief, except J11.2, J12.2 and J21.2 (reported starved) and every SMD GND pad, which are connected solid (`zone_connect 2` on the pad).
- Stitching vias 0.8/0.4 on an 8 mm lattice, each moved to the nearest spot at least 1.05 mm from foreign copper and holes. Zones and vias have uuids starting `474e4420-`; a re-run removes exactly those.
- The committed file contains the fill because `kicad-cli pcb drc --refill-zones --save-board` rewrites the board with the filled polygons. KiCad reorders items on that save, so the grid-router and Freerouting copper is compared by uuid and block text (`check_gnd.py tagged`), not by position.
- Alternate footprints far from their diode stay unwired (decision 4): MX_BSLSH2 (Net-(D79-A), U4_COL6), MX_RALT2 (U4_COL0 branch), and the pads in `left_pads.txt` (MX_KC1, MX_RWIN1, MX_RCTRL1/2, MX_RWIN2, MX_MENU1, MX_ROPT1: the last three inside the popout ring). MX_BSLSH2 cannot be populated unless the director decides otherwise.

## Rebuild

```
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
$PY tools/gnd_pour.py --solid-pth J11:2,J12:2,J21:2          # unfilled zones + vias into the board
kicad-cli pcb drc --refill-zones --save-board --schematic-parity -o drc.json fkb-109j-big/fkb-109j-big.kicad_pcb
$PY tools/gnd_islands.py fkb-109j-big/fkb-109j-big.kicad_pcb extra.txt tools/left_pads.txt   # then gnd_pour.py --extra-vias extra.txt
$PY tools/check_gnd.py components BOARD tools/left_pads.txt; $PY tools/check_gnd.py tagged BASE BOARD; $PY tools/check_gnd.py selftest BOARD BASE tools/left_pads.txt
```

## Still open and why

- Chip pins on B.Cu are caged by the grid router's own straight buses. U4 pins 7, 9, 10, 12, 13, 17 (COL0, VCC, GND, SCL, SDA, GND) sit between ROW0 at x=291.6 and ROW1 at x=294.4; U1 pins 24 to 27 (COL3 to COL6) sit between horizontal U1_COL1 (y=32.5) and U1_COL2 (y=35.6). A 0.25 mm track needs 0.345 mm from foreign copper and a 0.8 mm via cannot sit in the 1.3 mm channel, so `route_open.py` finds no path for MAIN_SCL, MAIN_SDA, MAIN_VCC, U1_COL3 to 6, U4_COL0. A fix needs ripping up and rerouting those tagged buses (not done; removals of tagged copper were not attempted). Not tried: Freerouting again, because `fill_freerouting.py strip` would replace the committed `46726565-` copper.
- GND groups not joined by the pour: U4.10 and U4.17 (same cage), U1.10, C1.2 and J14.2 in the F-row (each pad has only a small B.Cu island with no F.Cu fill above it for a stitching via). They need a short track or a via by hand.
- U6_NUM (J26 to U6 pin 8) and J13/J11 VCC and SCL stubs: not attempted beyond `route_open.py`.

## Checks

Zone short control (scratch copy, FROW_GND F.Cu zone renamed to MAIN_VCC so its stored fill overlaps GND copper): DRC without refill reported 70 clearance and 70 hole_clearance violations (0 shorting_items), `netcheck.py` exited 1 (vias re-netted), `shortdet.py` exited 0 (it does not test zone fill). So a zone short is caught by DRC and netcheck, not by shortdet.
