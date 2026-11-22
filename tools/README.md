# Routing tools

`route_regular.py` lays the regular nets of `fkb-109j-big.kicad_pcb` as tidy, deterministic tracks. `check_board.py` checks the result independently of the router. Both need KiCad's Python (pcbnew), and KiCad must not be running when the router writes the board.

```
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
$PY tools/route_regular.py                       # edits the board in place, about 12 minutes (the Main piece dominates)
$PY tools/route_regular.py --out /tmp/x.kicad_pcb # write a copy instead
$PY tools/route_regular.py --no-fanout           # skip the chip-pin step (on by default)
$PY tools/check_board.py connectivity BOARD tools/left_pads.txt # one copper component per routed net
$PY tools/check_board.py metrics BOARD           # segments, bends, vias per class
$PY tools/check_board.py same-as-base BASE BOARD # outline and footprints unchanged
$PY tools/check_board.py selftest BOARD BASE tools/left_pads.txt # negative controls for the checks above
```

## What it routes

In this order, each class by increasing bounding-box length, then net name: diode-to-switch links (`Net-(Dn-A)`), F-nav cable nets (`FNAV_*`), row buses (`*_ROW<n>`), column buses (`*_COL<n>`). Power, I2C and LED nets are never touched. Re-measure the table with `check_board.py metrics` and `--profile baseline` (four directions, via cost 12, no preferred direction: the research prototype's cost model on this obstacle model). A row or column bus connects every pad except the chip pin; the chip pin is a separate fanout step (on by default, `--no-fanout` skips it). A net that cannot be completed gets no copper at all (all or nothing per bus), and the script prints it. Pads it leaves on purpose are printed as `LEFT` and written to `tools/left_pads.txt` (net, reference, pad), which `check_board.py` reads so it does not count them as breaks: switches inside the popout ring (sacrificed by design) and alternate-layout switch footprints more than 60 mm from their diode (node links) or 40 mm sideways from their column.

## Rules

- Track width, clearance, via size and drill come from the Default net class in `.kicad_pro`; hole clearance, hole-to-hole and copper-to-edge from the board's design rules. The obstacle model covers other-net pads, every drill (plated and unplated), Edge.Cuts, and any copper that is not the router's own. A narrower track near chip pads is not used: the net-class width fits the SOIC-28W gap and chip pins are escaped outward.
- Grid router: A* on a 0.1 mm grid, two layers, eight directions (0 and 45 degrees). Costs, in grid cells: a corner of 45 degrees costs 5 and a right angle 14; moving against a layer's preferred axis costs +80%; a diagonal +40%/50%; a via 150. Diode links use neutral layers and cheap corners.
- Preferred directions: vertical on F.Cu, horizontal on B.Cu (`--swap-pref` reverses). Measured both on the same board without the chip-fanout step: the reverse gave 4 fewer vias and 5 fewer segments but 7 more bends on rows, so it is a tie; the default keeps rows straight on B.Cu next to the diodes.
- A bus grows from its leftmost pad, connecting the nearest remaining pad each time, so a row ends up as one straight run on B.Cu.
- Nets in different, spatially separate groups route in parallel worker processes; results merge in a fixed order, so the output does not depend on timing. The same board gives the same bytes.

## Tagging and re-runs

Every segment and via the router writes has a uuid starting with `52757465-` (ASCII "Rute"), derived from its net and geometry. A run first deletes exactly those items and then routes again, so it can be repeated after any placement change. Anything else on the board is treated as a fixed obstacle. To keep a hand-tidied track across re-runs, redraw it in KiCad (new uuid) or the next run will replace it.

The file is edited as text (items inserted before the `embedded_fonts` line), so the diff is only the added copper. Teardrops are not generated; the owner does that in KiCad.
