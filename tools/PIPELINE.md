# Routing pipeline

`pipeline.py` rebuilds every script-made copper item in order and checks it. Status of each stage is stated here as of this commit; a stage marked NOT DONE has code but was not run to a clean result.

```
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
JAR=/path/to/freerouting-2.5.0.jar        # FILL.md has the checksum
$PY tools/pipeline.py --work /tmp/pipe --jar $JAR --main /path/to/main.kicad_pcb
$PY tools/pipeline.py --work /tmp/pipe --stages strip,route    # one stage at a time also works
```

Run the stages with KiCad closed; the driver refuses to run otherwise. The router needs numpy, which is in the user site-packages of KiCad's Python, so run `route` without `-I`. The check scripts run under `-I`.

## Stages

1. `strip`: removes the tagged copper of all three tools (`52757465-` grid router, `46726565-` Freerouting, `474e4420-` pours and stitching vias). Nothing else is touched.
2. `route`: `route_regular.py`. Fanout first: before any bus is laid, every chip pin gets a straight stub out of the pad field (1 mm beyond the pad edge, perpendicular to the pad rows), power pins next to a decoupling capacitor get a link to it, and GND stubs end in a via. Row and column stubs become terminals of their bus (all or nothing: a failed bus leaves no stub). If a bus cannot reach its stub ends, that bus falls back to the old order (bus first, chip pins afterwards). `--no-fanout-first` restores the old order for everything.
3. `fill`: Freerouting for the rest (power, I2C, LED). It never routes `*_GND` nets (poured) or nets that have a pad in `left_pads.txt`. Default flags, 12 minute limit, killed by process group and the stop asserted.
4. `pour`: `gnd_pour.py`, a KiCad fill, island vias. NOT DONE: the step that joins GND pads left alone in a small B.Cu island (U4.10, U4.17, U1.10, C1.2, J14.2) is not written; the driver references a `gnd_pad_join.py` that does not exist yet.
5. `check`: DRC with `--refill-zones --all-track-errors --schematic-parity`, `netcheck.py`, `shortdet.py` plus its negative control, `check_pipeline.py` (connectivity with zones counted as copper, zone-to-foreign-copper clearance, negative controls), `check_board.py` (outline and footprints unchanged, tidiness table).

## Division of labour between the checks

KiCad re-nets a written track or via that touches other-net copper when it loads the file. `netcheck.py` finds that case (written net versus loaded net). `shortdet.py` finds different-net pads, tracks and vias that overlap; it does not see re-netted items and does not test zones. `check_pipeline.py zone-clearance` tests zone fills against foreign copper. DRC covers all three, so it is the final gate; the others show where.
