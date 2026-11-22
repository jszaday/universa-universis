# CLAUDE.md

Guide for working on the Universa Universis keyboard-retrofit PCB (KiCad project `fkb-109j-big/`). It records how rev1 ("rev. 1/β") is done with an agent, so the next session can pick up the same way. The electrical design is in `docs/rev1-spec.md`; open work is in `TODO.md`. Don't restate either here.

## Tooling

- KiCad 10.0.1. `kicad-cli` is not on PATH: use `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`.
- `pcbnew` Python imports only under `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3`. Use that interpreter for scripted board edits and checks.
- `kicad-cli` exits 0 even with violations unless given `--exit-code-violations`. Always pass it, and read the report as well as the exit code.
- Check KiCad is not running before writing board files from outside. A save from the GUI will overwrite them.
- Project-local `sym-lib-table` and `fp-lib-table` are committed in `fkb-109j-big/`. Without them ERC reports hundreds of library violations.
- Libraries: `umu.pretty/` (project footprints), `Panelization.pretty/`, and the `MX_Alps_Hybrid` submodule (switch footprints). A fresh worktree has empty submodules: run `git submodule update --init` in it first, or ERC and DRC report library warnings.

## Gates (run before accepting any PCB or schematic change)

1. ERC strict: `kicad-cli sch erc --severity-all --exit-code-violations`. Expect 0 violations.
2. DRC with `--refill-zones --all-track-errors --schematic-parity --severity-all --exit-code-violations`. Expect 0 parity items and 0 of clearance, shorting_items, tracks_crossing, copper_edge_clearance, courtyards_overlap, hole_clearance, hole_to_hole, solder_mask_bridge, track_dangling, via_dangling, track_width, isolated_copper. Silkscreen and library-footprint warnings are standing. Unconnected items are expected only for nets listed in `TODO.md` and the deliberately unwired alternate footprints; anything else is a regression. Without `--all-track-errors` DRC reports only the first error per track.
3. Short checks beyond DRC. KiCad rewrites an item's net from the copper it touches when it loads a board, so DRC cannot see a short that a script writes into the file as text. Also run `tools/netcheck.py <pcb>` (nets as written in the file against nets after load; exit 1 on any mismatch) and `tools/shortdet.py <pcb>` (geometric different-net overlap on loaded shapes; it does not test zone fills, so also run `tools/check_pipeline.py zone-clearance <pcb>`, which checks every zone-fill island against foreign-net copper). Run the Python tools with the KiCad interpreter and `-I`. Each check needs a negative control that fails.
4. Outline: the Edge.Cuts set must be identical to rev0. Margins are minimal by design, so the board must not grow. Compare against the rev0 commit with a script, not by eye, and show the script can fail.
5. Counts: the switch and diode footprint counts are unchanged from the base commit, every footprint keeps its position, angle and layer (pad-level property changes are listed separately), and the board's pads match the schematic netlist with 0 mismatches. Diodes are on B.Cu but not in one orientation (a few sit at 0 or 180 degrees; cosmetic). Derive the numbers from the base commit, not from this file.
6. Popout: compare the final board with itself before and after a change. Comparing against rev0 is invalid, because rev0 has no perforation ring.
7. Firmware: `make -C firmware test` (checks the pin table against the spec's CSV blocks) and `make -C firmware mutants` (the tests must kill every mutant).

Have a fresh agent run these, with only the artifact and the criteria. Don't hand it the author's conclusions.

## Design rules that were decided (don't reopen without the owner)

- Keep the breakaway panel: pieces F-row, F-nav, Main, Nav, Numpad. The main deployment cuts every seam, so no hand-wired jumpers across seams, and each piece except F-nav works alone.
- Each piece has its own MCP23017 extender where it needs one (Main has two), on a 4-wire I2C bus (VCC, GND, SDA, SCL on a 1x04 2.54 mm header). All chips are one part and one footprint, SOIC-28W. Addresses are hardwired per chip; there are no address jumpers. Decoupling is one 100 nF 0805 per chip and nothing else.
- Bus headers sit on the back along the edge nearest the neighbouring piece, never in the interior.
- SMD parts sit on the back inside the original outline. Through-hole diodes (1N4148, DO-35) are also on the back, with the cathode on the row side.
- Rows are driven low one at a time and unselected rows are high-Z. Columns use pull-ups. GPA7/GPB7 are output-only.
- The popout circle (r = 5.5 mm, near the AT101 blank) is a perforation ring. MX_MENU1, MX_ROPT1 and MX_RWIN2 are sacrificed on purpose.
- Routing, as built: `tools/route_regular.py` lays the diode links, F-nav nets, rows and columns as deterministic tracks (tagged uuid prefix `52757465-`); `tools/fill_freerouting.py` lets Freerouting (v2.5.0, Java 25, default flags) route what is left, with the script's nets removed from the DSN network (tagged `46726565-`); `tools/gnd_pour.py` adds per-piece GND pours with stitching vias. Marking wires `fix` in the DSN does not stop Freerouting rerouting them, so exclude nets instead. The remaining open nets are finished by hand in KiCad (`TODO.md`). A fanout-first router mode exists but was not a clear win.
- Not done yet, and deliberately: the ISO Enter offset (owner is checking the physical board), the numpad plus/Enter rotation, the LED carrier board. Donor labels are out of scope for rev1 (rev2). All are in `TODO.md`. Don't create the `rev1-beta` tag until the owner answers the ISO Enter question.

## How the work was run

- Lead plus parallel workers, each in its own git worktree under `/Users/szaday2/workspace/universa-universis-wt/`. Workers commit on their branch. The lead rebases and fast-forwards into `main`. Push only when the owner asks, after listing the stacked commits with one-line descriptions.
- Order that worked: spec first (`docs/rev1-spec.md`), then footprint library, schematic and firmware in parallel against the spec, then PCB, then an independent verifier.
- Brief workers with absolute paths, the locked decisions, the files they own and a done check they can run. Tell each to run long commands in the background with output to a log and a return-code file.
- Verify what a worker reports. In this project workers got facts wrong several times (a claimed VCC-GND short on a reversed plug, a wrong "added N segments" in a commit message, a README claim about `MX_ENTR1` that didn't reproduce). Reproduce the claim before it goes into a doc.

## Pitfalls seen

- The first PCB round grew the outline with service strips. The owner rejected that. Chips go on the back inside the original outline.
- Before fast-forwarding `main`, stash the owner's uncommitted board and project settings (`git stash push -m <message> -- <paths>`) rather than discarding them; the owner may have stripped or edited the board in KiCad.
- Tags: check `git tag` before creating one. A duplicate (`alpha-revision`) was found and removed at the owner's request. The rev0 tag is `rev0-alpha`.
- Stage files by explicit path. `fkb-109j-big/.history/` (KiCad autosave) and `fkb-109j-big.kicad_prl` (view state) are ignored; never force-add them.
- Teardrops are not regenerated by scripts. The owner does Edit > Teardrops in KiCad after routing.

## What the owner still does in KiCad

Route what the scripts and the autorouter leave, regenerate teardrops, run F8 "Update PCB from Schematic" as a sanity check, and look over placement, including header solder joints against switch bodies and back-side part height against the donor cases. Also pending is the bus connector choice (plain 1x04 header, keyed Molex KK-254 recommended, or a plain header plus series resistors at the controller).
