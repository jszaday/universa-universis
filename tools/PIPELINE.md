# Routing pipeline

`pipeline.py` rebuilds every script-made copper item in order and checks it. The help text of `pipeline.py` lists which stages are implemented. No stage has been verified as part of an end-to-end run. A stage that is incomplete stops with exit code 2 and names what is missing.

```
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
JAR=/path/to/freerouting-2.5.0.jar        # FILL.md has the checksum
$PY tools/pipeline.py --work /tmp/pipe --jar $JAR --main /path/to/main.kicad_pcb
$PY tools/pipeline.py --work /tmp/pipe --stages strip,route    # one stage at a time also works
```

Run the stages with KiCad closed; the driver refuses to run otherwise. The router needs numpy, which is in the user site-packages of KiCad's Python, so run `route` without `-I`. The check scripts run under `-I`.

## Stages

1. `strip`: removes the tagged copper of all three tools (`52757465-` grid router, `46726565-` Freerouting, `474e4420-` pours and stitching vias). Nothing else is touched.
2. `route`: `route_regular.py`. The default order is buses first, then the chip pins; this is how the committed board was built. `--fanout-first` (chip pins routed before the buses) is opt-in: implemented, not a clear win (state and numbers: `TODO.md`). `pipeline.py` does not pass it.
3. `fill`: Freerouting for the rest (power, I2C, LED). It never routes `*_GND` nets (poured) or nets that have a pad in `left_pads.txt`. Default flags, 12 minute limit, killed by process group and the stop asserted.
4. `pour`: `gnd_pour.py` and one KiCad fill. Stops with exit code 2 at `TODO(pipeline-gnd-join)`: the step that joins GND pads left alone in a pour island is not written; run `gnd_pour.py --extra-vias` by hand (`tools/GND.md`).
5. `check`: stops with exit code 2 at `TODO(pipeline-allowed-open)` because `tools/allowed_open.txt` does not exist. Once it exists: DRC with `--refill-zones --all-track-errors --schematic-parity`, `netcheck.py`, `shortdet.py` plus its negative control, `check_pipeline.py` (connectivity with zones counted as copper, zone-to-foreign-copper clearance, negative controls), `check_board.py` (outline and footprints unchanged, tidiness table).

## Division of labour between the checks

KiCad re-nets a written track or via that touches other-net copper when it loads the file. `netcheck.py` finds that case (written net versus loaded net). `shortdet.py` finds different-net pads, tracks and vias that overlap; it does not see re-netted items and does not test zones. `check_pipeline.py zone-clearance` tests zone fills against foreign copper. DRC covers all three, so it is the final gate; the others show where.
