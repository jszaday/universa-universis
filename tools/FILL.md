# Freerouting fill step

`fill_freerouting.py` routes what the grid router (`route_regular.py`) left, with Freerouting 2.5.0, and adds only the new copper to the board. `check_fill.py` checks the result independently. Both need KiCad's Python (pcbnew), and KiCad must not be running when the board is written.

## Why not just run Freerouting on the board

Marking the grid router's wires as fixed in the DSN did not stop Freerouting from re-routing nets that were already complete, and importing a SES replaces all tracks. So the DSN built here lists only the nets that are not yet one copper component (power, I2C, LED, column fanouts, the left pads). Every other net is removed from the DSN network, so Freerouting never routes it, while its pads, tracks and vias stay in the DSN wiring as obstacles. Existing wires of the nets still being routed are marked fixed. The class rule is pinned to the board's net class: 0.25 mm track, 0.8/0.4 mm via only, 0.2 mm clearance (the default export allowed a 0.6/0.3 via and a 0.2 mm track).

Only wires and vias from the SES are merged, as text, tagged with the uuid prefix `46726565-` ("Free"). Grid-router items (`52757465-`) are never rewritten.

## Recipe

Run from the repository root. Freerouting jar: v2.5.0, SHA-256 `f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7`. Use the default flags only (`-mp`/`-mt` made it exit without output); it takes about a minute or two. The native freerouting-cli binary crashes, use the jar.

```
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
JAVA=/Library/Java/JavaVirtualMachines/temurin-25.jdk/Contents/Home/bin/java
JAR=/path/to/freerouting-2.5.0.jar
BOARD=fkb-109j-big/fkb-109j-big.kicad_pcb
W=$(mktemp -d)
$PY tools/fill_freerouting.py strip $BOARD $W/base.kicad_pcb      # remove earlier 46726565- copper
$PY tools/fill_freerouting.py prep $W/base.kicad_pcb $W/fill.dsn
$JAVA -jar $JAR -de $W/fill.dsn -do $W/fill.ses > $W/fr.log 2>&1
$PY tools/fill_freerouting.py merge $W/base.kicad_pcb $W/fill.ses $BOARD
```

Checks:

```
kicad-cli pcb drc --exit-code-violations --schematic-parity --format json -o drc.json $BOARD
$PY tools/check_fill.py components $BOARD                # every net one copper component
$PY tools/check_fill.py script-copper BASE.kicad_pcb $BOARD   # grid-router copper unchanged (BASE = board before the fill)
$PY tools/check_fill.py metrics $BOARD                   # segments, vias, corners of the fill copper
$PY tools/check_fill.py selftest $BOARD BASE.kicad_pcb   # negative controls
$PY tools/check_board.py same-as-base MAIN.kicad_pcb $BOARD   # outline and footprints unchanged
```

Then drop the fill copper that breaks a rule, and leave those nets for hand routing (the DRC json is the one written above; `drop-nets` takes net names, so pass what `bad-nets` prints plus any net you judge too long):

```
$PY tools/fill_freerouting.py bad-nets $BOARD drc.json
$PY tools/fill_freerouting.py drop-nets $BOARD $BOARD <nets printed above>
```

Why this is needed: Freerouting narrows a track to 0.187 mm next to some pads. `merge` writes every track at the net-class 0.25 mm, so those spots fail clearance (FROW_GND beside C1 pad 1, NAV_GND beside U5 pad 14). A second Freerouting pass on those nets did not fix them (it also left more nets open), so they stay unrouted. Nets that remain open after the fill are the dense ones around the Main chips (power and I2C) and a few chip column pins; see the commit message.

`prep` keeps the DSN to the nets that are not one copper component; for a net that already has grid-router copper it lists only the pad pairs that bridge its components.

Freerouting is not guaranteed to be deterministic, so a rerun may give different fill copper; the grid-router copper is identical either way.
