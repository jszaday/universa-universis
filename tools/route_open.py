#!/usr/bin/env python3
"""Hand-controlled connector for the nets the grid router and Freerouting left open.

Run with KiCad's Python (pcbnew reads the board; the board file is edited as text):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      tools/route_open.py [--board PATH] [--out PATH] [--nets A,B,...] [--skip-prefix ...]

For every net that is not one copper component it joins the components with the same A* as
route_regular.py (same obstacle grid, so the same clearances; layer changes are explicit vias).
The largest component is the tree; the nearest other component is joined each time. Existing
copper is never changed. New copper has a uuid starting with OPEN_UUID_PREFIX, so a re-run
removes exactly its own copper first. Components made only of pads listed in tools/left_pads.txt
(alternate footprints left on purpose) are not joined. See tools/GND.md.
"""
import argparse
import hashlib
import math
import os
import re
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

import pcbnew  # noqa: E402
import route_regular as rr  # noqa: E402
from check_board import components, read_left  # noqa: E402

OPEN_UUID_PREFIX = "4f70656e-"  # ASCII "Open"
BLOCK = rr.BLOCK
mm = pcbnew.ToMM


def uuid_for(key):
    h = hashlib.sha1(key.encode()).hexdigest()
    return "%s%s-4%s-8%s-%s" % (OPEN_UUID_PREFIX, h[0:4], h[4:7], h[7:10], h[10:22])


def strip_open(text):
    n = 0

    def sub(m):
        nonlocal n
        if '(uuid "%s' % OPEN_UUID_PREFIX in m.group(0):
            n += 1
            return ""
        return m.group(0)

    return BLOCK.sub(sub, text), n


def item_cells(grid, kind, o, net):
    """{(i, j): layer mask} a new track may end on to touch this item (free cells only)."""
    cells = {}

    def put(x, y, mask, tol):
        i0, i1 = grid.ci(x - tol), grid.ci(x + tol)
        j0, j1 = grid.cj(y - tol), grid.cj(y + tol)
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                if abs(grid.cx(i) - x) <= tol + 1e-9 and abs(grid.cy(j) - y) <= tol + 1e-9:
                    cells[(i, j)] = cells.get((i, j), 0) | mask

    if kind == "pad":
        bb = o.GetBoundingBox()
        hw, hh = mm(bb.GetWidth()) / 2.0, mm(bb.GetHeight()) / 2.0
        tol = min(rr.PAD_TOL, max(hw, hh))
        mask = (1 if o.IsOnLayer(pcbnew.F_Cu) else 0) | (2 if o.IsOnLayer(pcbnew.B_Cu) else 0)
        put(mm(o.GetX()), mm(o.GetY()), mask, tol)
    elif kind == "via":
        put(mm(o.GetX()), mm(o.GetY()), 3, 0.07)
    else:
        mask = 1 if o.GetLayer() == pcbnew.F_Cu else 2
        ax, ay, bx, by = mm(o.GetStart().x), mm(o.GetStart().y), mm(o.GetEnd().x), mm(o.GetEnd().y)
        n = max(1, int(math.hypot(bx - ax, by - ay) / 0.05))
        for k in range(n + 1):
            put(ax + (bx - ax) * k / n, ay + (by - ay) * k / n, mask, 0.045)
    out = {}
    for c, m in cells.items():
        m2 = rr.free_cell(grid, net, c[0], c[1], m)
        if m2:
            out[c] = m2
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", default=os.path.join(here, "..", "fkb-109j-big", "fkb-109j-big.kicad_pcb"))
    ap.add_argument("--out")
    ap.add_argument("--nets", help="comma list; default: every net with more than one component except GND nets")
    ap.add_argument("--left", default=os.path.join(here, "left_pads.txt"))
    ap.add_argument("--cap", type=int, default=4000000, help="A* expansion cap per connection")
    ap.add_argument("--margin", type=float, default=10.0, help="search window margin around the two parts, mm")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    board = os.path.abspath(a.board)
    dst = os.path.abspath(a.out) if a.out else board
    if not a.force and rr.kicad_running():
        raise SystemExit("route_open: KiCad is running and a save from it would overwrite %s. Quit KiCad or pass --force for a scratch --out copy." % dst)
    t0 = time.time()
    text = open(board, encoding="utf-8").read()
    text, removed = strip_open(text)
    td = tempfile.mkdtemp()
    tmp = os.path.join(td, "in.kicad_pcb")
    open(tmp, "w", encoding="utf-8").write(text)
    rules = rr.read_rules(board.replace(".kicad_pcb", ".kicad_pro"))
    data = rr.extract_board(tmp)
    names = sorted({p["net"] for p in data["pads"] if p["net"]})
    netids = {n: k + 1 for k, n in enumerate(names)}
    xs = [e[0] for e in data["edges"]] + [e[2] for e in data["edges"]]
    ys = [e[1] for e in data["edges"]] + [e[3] for e in data["edges"]]
    grid = rr.Grid((min(xs), min(ys), max(xs), max(ys)), rules, netids)
    grid.add_pads(data["pads"])
    grid.add_edges(data["edges"])
    for t in data["tracks"]:
        if t["kind"] == "via":
            grid.add_via(t["net"], t["x"], t["y"], t["d"], t["drill"])
        else:
            grid.add_seg(t["net"], t["layer"], t["x1"], t["y1"], t["x2"], t["y2"], t["w"])
    grid.freeze()
    b = pcbnew.LoadBoard(tmp)
    comp = components(b)
    left = read_left(a.left)
    only = set(a.nets.split(",")) if a.nets else None
    P = rr.PROFILES["tidy"]["fan"]
    new_segs, new_vias, failed = [], [], []
    for net in sorted(comp):
        if not net or (only is not None and net not in only):
            continue
        if only is None and "GND" in net:
            continue
        items, d = comp[net]
        groups = {}
        for k in range(len(items)):
            groups.setdefault(d.find(k), []).append(k)

        def is_left(k):
            kind, o = items[k]
            return kind == "pad" and (net, o.GetParentFootprint().GetReference(), o.GetNumber()) in left

        def npads(g):
            return sum(1 for k in g if items[k][0] == "pad" and not is_left(k))

        comps = [g for g in groups.values() if not (npads(g) == 0 and any(is_left(k) for k in g))]
        if len(comps) < 2:
            continue
        comps.sort(key=lambda g: (-npads(g), -len(g), min(k for k in g)))
        print("%s: %d components, pads per component %s" % (net, len(comps), [npads(g) for g in comps]), flush=True)
        nid = netids[net]
        cellsets = [dict() for _ in comps]
        for ci_, g in enumerate(comps):
            for k in g:
                for c, m in item_cells(grid, items[k][0], items[k][1], nid).items():
                    cellsets[ci_][c] = cellsets[ci_].get(c, 0) | m
        tree_idx = 0
        tree = set((i, j, L) for (i, j), m in cellsets[0].items() for L in (0, 1) if (m >> L) & 1)
        todo = list(range(1, len(comps)))

        def cdist(ci_):
            best = 1e18
            ts = [(i, j) for (i, j, _) in tree]
            for (i, j) in cellsets[ci_]:
                for (ti, tj) in ts[:: max(1, len(ts) // 400)]:
                    dd = abs(i - ti) + abs(j - tj)
                    if dd < best:
                        best = dd
            return best

        while todo:
            todo.sort(key=lambda c: (cdist(c), c))
            done_one = False
            for ci_ in list(todo):
                goal = cellsets[ci_]
                if not goal or not tree:
                    print("  %s: component %d has no free cell where a track could end on it (hemmed in by neighbouring copper)" % (net, ci_), flush=True)
                    continue
                allc = [(c[0], c[1]) for c in tree] + list(goal)
                m = int(round(a.margin / rr.G))
                win = (max(min(c[0] for c in allc) - m, 0), max(min(c[1] for c in allc) - m, 0),
                       min(max(c[0] for c in allc) + m, grid.NX - 1), min(max(c[1] for c in allc) + m, grid.NY - 1))
                gxy = sorted(goal)[0]
                path = rr.astar(grid, nid, sorted(tree), goal, gxy, win, P, a.cap)
                if path is None:
                    print("  %s: no path from the tree to component %d (%d pads)" % (net, ci_, npads(comps[ci_])), flush=True)
                    continue
                segs, vias = rr.path_to_items(path)
                segs, vias = rr.merge_collinear(segs, vias, set(goal) | {(c[0], c[1]) for c in tree if False})
                for (L, p, q_, r_, s_) in segs:
                    grid.add_seg(net, L, grid.cx(p), grid.cy(q_), grid.cx(r_), grid.cy(s_), rules["width"])
                    new_segs.append((net, L, grid.cx(p), grid.cy(q_), grid.cx(r_), grid.cy(s_)))
                for (p, q_) in vias:
                    grid.add_via(net, grid.cx(p), grid.cy(q_), rules["via_d"], rules["via_drill"])
                    new_vias.append((net, grid.cx(p), grid.cy(q_)))
                for c in path:
                    tree.add(c)
                for (i, j), mk in goal.items():
                    for L in (0, 1):
                        if (mk >> L) & 1:
                            tree.add((i, j, L))
                todo.remove(ci_)
                done_one = True
                print("  %s: joined component %d (%d segments, %d vias)" % (net, ci_, len(segs), len(vias)), flush=True)
                break
            if not done_one:
                failed.append((net, len(todo)))
                print("  %s: %d component(s) left unjoined" % (net, len(todo)), flush=True)
                break
    fm = rr.fmt
    out = []
    for (net, L, x1, y1, x2, y2) in new_segs:
        lay = "F.Cu" if L == 0 else "B.Cu"
        key = "seg|%s|%s|%s,%s|%s,%s" % (net, lay, fm(x1), fm(y1), fm(x2), fm(y2))
        out.append("\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width %s)\n\t\t(layer %s)\n\t\t(net %s)\n\t\t(uuid %s)\n\t)\n"
                   % (fm(x1), fm(y1), fm(x2), fm(y2), fm(rules["width"]), rr.q(lay), rr.q(net), rr.q(uuid_for(key))))
    for (net, x, y) in new_vias:
        key = "via|%s|%s,%s" % (net, fm(x), fm(y))
        out.append("\t(via\n\t\t(at %s %s)\n\t\t(size %s)\n\t\t(drill %s)\n\t\t(layers \"F.Cu\" \"B.Cu\")\n\t\t(net %s)\n\t\t(uuid %s)\n\t)\n"
                   % (fm(x), fm(y), fm(rules["via_d"]), fm(rules["via_drill"]), rr.q(net), rr.q(uuid_for(key))))
    tail = "\t(embedded_fonts no)\n)"
    if text.count(tail) != 1:
        raise SystemExit("route_open: %s does not end with the expected '(embedded_fonts no)' trailer; the file layout changed, update the trailer check." % board)
    open(dst, "w", encoding="utf-8").write(text.replace(tail, "".join(out) + tail))
    print("removed %d old open-net items; added %d segments, %d vias; unjoined nets %s; wrote %s in %.0fs"
          % (removed, len(new_segs), len(new_vias), failed, dst, time.time() - t0))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
