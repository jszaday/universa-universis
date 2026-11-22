#!/usr/bin/env python3
"""Rebuild every script-made copper item of the board, in order, and check it. See tools/PIPELINE.md.

  pipeline.py [--board PATH] [--work DIR] [--jar FREEROUTING_JAR] [--stages strip,route,fill,pour,check]

Stages (each reads and writes --board; every stage logs to DIR/<stage>.log and records its exit code in DIR/<stage>.rc):
  strip  remove every tagged item (52757465- grid router, 46726565- Freerouting, 474e4420- pours) and nothing else
  route  tools/route_regular.py (fanout first)
  fill   Freerouting for what is left (never GND nets or deliberately left nets), merged as 46726565- copper
  pour   tools/gnd_pour.py zones and stitching vias, KiCad fill, island vias, then a short track or via for each GND pad still alone
  check  DRC, netcheck, shortdet, zone clearance, connectivity, same-as-base and the negative controls

Run it with KiCad's Python (pcbnew) and with KiCad closed. numpy must be importable (the router needs it).
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
JAVA = "/Library/Java/JavaVirtualMachines/temurin-25.jdk/Contents/Home/bin/java"
FREEROUTING_LIMIT_S = 12 * 60
PY = sys.executable
GND_PREFIX = "474e4420-"


def run(cmd, log, rc_file, limit=None, ok=(0,)):
    """Run cmd with output to `log`; write the exit code to `rc_file`; return it. A run over `limit` seconds is killed
    by its process group and the kill is asserted."""
    t0 = time.time()
    with open(log, "w") as lg:
        p = subprocess.Popen(cmd, stdout=lg, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = p.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=20)
            rc = 124
            with open(log, "a") as lg2:
                lg2.write("pipeline: killed after %d s (limit) and confirmed stopped, pid %d\n" % (limit, p.pid))
    try:
        os.kill(p.pid, 0)
        alive = True
    except OSError:
        alive = False
    if alive and p.poll() is None:
        raise SystemExit("pipeline: pid %d is still running after the kill; stop it by hand (kill -9 %d)." % (p.pid, p.pid))
    open(rc_file, "w").write("rc=%d\n" % rc)
    print("  %-60s rc=%d  %.0fs" % (" ".join(os.path.basename(c) for c in cmd[:3]), rc, time.time() - t0), flush=True)
    return rc


def strip_all(board):
    import route_regular as rr
    import fill_freerouting as ff
    import gnd_pour as gp
    t = open(board, encoding="utf-8").read()
    t, a = rr.strip_router_copper(t)
    t, b = ff.strip_fill_copper(t)
    t, c = gp.strip_own(t)
    open(board, "w", encoding="utf-8").write(t)
    print("strip: removed %d router, %d fill, %d pour items" % (a, b, c))


def drc(board, out_json, log, rc, extra=()):
    return run([KICAD_CLI, "pcb", "drc", "--exit-code-violations", "--severity-all", "--format", "json",
                "--all-track-errors", "--schematic-parity", "-o", out_json, *extra, board], log, rc)


def stage_route(a, w):
    left = os.path.join(HERE, "left_pads.txt")
    return run([PY, os.path.join(HERE, "route_regular.py"), "--board", a.board, "--left-file", left, "--log", os.path.join(w, "route_nets.log")],
               os.path.join(w, "route.log"), os.path.join(w, "route.rc"))


def stage_fill(a, w):
    left = os.path.join(HERE, "left_pads.txt")
    ff = os.path.join(HERE, "fill_freerouting.py")
    dsn, ses = os.path.join(w, "fill.dsn"), os.path.join(w, "fill.ses")
    base = os.path.join(w, "fill_base.kicad_pcb")
    open(base, "w").write(open(a.board).read())
    if run([PY, ff, "prep", base, dsn, "--left", left], os.path.join(w, "fill_prep.log"), os.path.join(w, "fill_prep.rc")):
        return 1
    if os.path.exists(ses):
        os.remove(ses)
    rc = run([JAVA, "-jar", a.jar, "-de", dsn, "-do", ses], os.path.join(w, "freerouting.log"), os.path.join(w, "freerouting.rc"), limit=FREEROUTING_LIMIT_S)
    if rc != 0 or not os.path.exists(ses):
        print("fill: Freerouting rc=%d, no merge (see %s)" % (rc, os.path.join(w, "freerouting.log")))
        return 1
    return run([PY, ff, "merge", base, ses, a.board], os.path.join(w, "fill_merge.log"), os.path.join(w, "fill_merge.rc"))


def stage_pour(a, w):
    gp = os.path.join(HERE, "gnd_pour.py")
    solid = "J11:2,J12:2,J21:2"
    cmd = [PY, gp, "--board", a.board, "--solid-pth", solid]
    if run(cmd, os.path.join(w, "pour.log"), os.path.join(w, "pour.rc")):
        return 1
    extra = os.path.join(w, "extra_vias.txt")
    open(extra, "w").write("")
    for rnd in range(4):
        # fill (the saved board then holds the filled polygons) and look for split pours
        if run([KICAD_CLI, "pcb", "drc", "--refill-zones", "--save-board", "--schematic-parity", "-o", os.path.join(w, "pour_drc.json"), a.board],
               os.path.join(w, "pour_fill%d.log" % rnd), os.path.join(w, "pour_fill%d.rc" % rnd)) not in (0, 5):
            return 1
        more = os.path.join(w, "extra_vias_%d.txt" % rnd)
        if run([PY, os.path.join(HERE, "gnd_pad_join.py"), a.board, more, os.path.join(HERE, "left_pads.txt")],
               os.path.join(w, "pour_join%d.log" % rnd), os.path.join(w, "pour_join%d.rc" % rnd)):
            return 1
        if not open(more).read().strip():
            break
        with open(extra, "a") as f:
            f.write(open(more).read())
        if run(cmd + ["--extra-items", extra], os.path.join(w, "pour_again%d.log" % rnd), os.path.join(w, "pour_again%d.rc" % rnd)):
            return 1
    return 0


def stage_check(a, w):
    left = os.path.join(HERE, "left_pads.txt")
    main_pcb = a.main
    bad = 0
    bad |= bool(drc(a.board, os.path.join(w, "drc.json"), os.path.join(w, "drc.log"), os.path.join(w, "drc.rc"), ("--refill-zones",)) not in (0, 5))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "netcheck.py"), a.board], os.path.join(w, "netcheck.log"), os.path.join(w, "netcheck.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "shortdet.py"), a.board], os.path.join(w, "shortdet.log"), os.path.join(w, "shortdet.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "shortdet.py"), "--selftest", a.board], os.path.join(w, "shortdet_self.log"), os.path.join(w, "shortdet_self.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "check_pipeline.py"), "zone-clearance", a.board], os.path.join(w, "zone.log"), os.path.join(w, "zone.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "check_pipeline.py"), "connectivity", a.board, left, os.path.join(HERE, "allowed_open.txt")], os.path.join(w, "conn.log"), os.path.join(w, "conn.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "check_pipeline.py"), "selftest", a.board, left], os.path.join(w, "check_self.log"), os.path.join(w, "check_self.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "check_board.py"), "same-as-base", main_pcb, a.board], os.path.join(w, "same.log"), os.path.join(w, "same.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "check_board.py"), "selftest", a.board, main_pcb, left], os.path.join(w, "board_self.log"), os.path.join(w, "board_self.rc")))
    bad |= bool(run([PY, "-I", os.path.join(HERE, "check_board.py"), "metrics", a.board], os.path.join(w, "metrics.log"), os.path.join(w, "metrics.rc")))
    # DRC verdict: zero of the hard classes, unconnected items listed
    hard = ("clearance", "shorting_items", "tracks_crossing", "copper_edge_clearance", "courtyards_overlap", "hole_clearance",
            "hole_to_hole", "solder_mask_bridge", "track_dangling", "via_dangling", "track_width", "isolated_copper")
    d = json.load(open(os.path.join(w, "drc.json")))
    counts = {}
    for v in d.get("violations", []):
        counts[v["type"]] = counts.get(v["type"], 0) + 1
    hardn = {k: counts.get(k, 0) for k in hard}
    par = len(d.get("schematic_parity", []))
    print("DRC hard classes: %s; parity %d; unconnected %d" % (hardn, par, len(d.get("unconnected_items", []))))
    if any(hardn.values()) or par:
        bad = 1
    return int(bad)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", default=os.path.join(ROOT, "fkb-109j-big", "fkb-109j-big.kicad_pcb"))
    ap.add_argument("--work", required=True, help="directory for logs, rc files and intermediates")
    ap.add_argument("--jar", help="freerouting-2.5.0.jar (needed by the fill stage)")
    ap.add_argument("--main", help="the main branch's board for the same-as-base check (check stage)")
    ap.add_argument("--stages", default="strip,route,fill,pour,check")
    a = ap.parse_args()
    a.board = os.path.abspath(a.board)
    os.makedirs(a.work, exist_ok=True)
    w = os.path.abspath(a.work)
    ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    if any("KiCad.app/Contents/MacOS/kicad" in l and "kicad-cli" not in l for l in ps.splitlines()):
        raise SystemExit("pipeline: KiCad is running; a save from it would overwrite %s. Quit KiCad and rerun." % a.board)
    stages = a.stages.split(",")
    if "fill" in stages and not a.jar:
        raise SystemExit("pipeline: the fill stage needs --jar PATH_TO_freerouting-2.5.0.jar (see tools/FILL.md).")
    if "check" in stages and not a.main:
        raise SystemExit("pipeline: the check stage needs --main PATH_TO_main_board.kicad_pcb for the unchanged-outline check.")
    rc = 0
    for s in stages:
        print("== %s" % s, flush=True)
        if s == "strip":
            strip_all(a.board)
        elif s == "route":
            rc |= stage_route(a, w)
        elif s == "fill":
            rc |= stage_fill(a, w)
        elif s == "pour":
            rc |= stage_pour(a, w)
        elif s == "check":
            rc |= stage_check(a, w)
        else:
            raise SystemExit("pipeline: unknown stage %r" % s)
        if rc:
            print("pipeline: stage %s failed, stopping (logs in %s)" % (s, w))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
