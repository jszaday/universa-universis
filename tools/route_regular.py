#!/usr/bin/env python3
"""Deterministic grid router for the regular nets of the keyboard PCB.

Run with KiCad's Python (pcbnew is only used to read the board):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      tools/route_regular.py [--board PATH] [--out PATH] [--profile tidy|baseline] [--jobs N]

It lays diode-to-switch links, F-nav cable nets, row/column buses and (optionally) chip-pin
fanout, never power, I2C or LED nets. See tools/README.md for the rules and the tagging scheme.
The board file is edited as text: every track or via this script writes carries a uuid starting
with ROUTER_UUID_PREFIX, so a re-run removes exactly its own copper and nothing else.
"""
import argparse
import hashlib
import heapq
import json
import math
import multiprocessing
import os
import re
import subprocess
import sys
import tempfile
import time
from array import array

import numpy as np

SQ2 = math.sqrt(2.0)
ROUTER_UUID_PREFIX = "52757465-"  # ASCII "Rute": marks copper created by this script
G = 0.1  # grid pitch, mm; grid points are the multiples of G in board coordinates
MARGIN = 0.02  # extra clearance baked into every zone, mm
PAD_TOL = 0.08  # a track may end on any cell within this distance of a pad centre, mm
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
CLASS_ORDER = ["node", "fnav", "row", "col"]
COL_REACH = 40.0  # mm; a column pad farther than this sideways from the column's median x is left
NODE_REACH = 60.0  # mm; a node-link pad farther than this (Manhattan) from its diode is not a link

# cost profiles in cell units (1 cell = G mm). ww = extra factor for a wrong-way axis move,
# wd = extra factor for a diagonal move, b45/b90 = corner penalties, via = layer change.
PROFILES = {
    "tidy": {
        "node": dict(ww=0.0, wd=0.0, b45=3.0, b90=8.0, via=150.0, pref=None, diag=True),
        "fnav": dict(ww=0.8, wd=0.4, b45=5.0, b90=14.0, via=150.0, pref=("v", "h"), diag=True),
        "row": dict(ww=0.8, wd=0.5, b45=5.0, b90=14.0, via=150.0, pref=("v", "h"), diag=True),
        "col": dict(ww=0.8, wd=0.5, b45=5.0, b90=14.0, via=150.0, pref=("v", "h"), diag=True),
        "fan": dict(ww=0.3, wd=0.2, b45=3.0, b90=8.0, via=150.0, pref=("v", "h"), diag=True),
    },
    # the research prototype's model on this script's obstacle model: 4 directions, a small
    # per-turn cost, via cost 12, no preferred direction. Only used to measure "before".
    "baseline": {
        c: dict(ww=0.0, wd=0.0, b45=0.3, b90=0.3, via=12.0, pref=None, diag=False)
        for c in ("node", "fnav", "row", "col", "fan")
    },
}


# ----------------------------------------------------------------------------- classification
def classify_net(name):
    """Router class of a net name, or None for nets this script never touches."""
    if re.match(r"^Net-\(D\d+-A\)$", name):
        return "node"
    if name.startswith("FNAV"):
        return "fnav"
    if re.search(r"_ROW\d+$", name):
        return "row"
    if re.search(r"_COL\d+$", name):
        return "col"
    return None


def is_chip(ref):
    return re.match(r"^U\d+$", ref) is not None


# ----------------------------------------------------------------------------- rules
def read_rules(pro_path):
    d = json.load(open(pro_path))
    ds = d["board"]["design_settings"]["rules"]
    ns = d["net_settings"]
    if ns.get("netclass_patterns") or ns.get("netclass_assignments"):
        raise SystemExit(
            "route_regular: %s assigns nets to non-default net classes, which this router does not read. "
            "Extend read_rules() to resolve per-net classes before routing." % pro_path
        )
    cls = [c for c in ns["classes"] if c["name"] == "Default"][0]
    return dict(
        width=cls["track_width"],
        clearance=max(cls["clearance"], ds["min_clearance"]),
        via_d=cls["via_diameter"],
        via_drill=cls["via_drill"],
        hole_clr=ds["min_hole_clearance"],
        hole_hole=ds["min_hole_to_hole"],
        edge_clr=ds["min_copper_edge_clearance"],
    )


# ----------------------------------------------------------------------------- board extraction
def extract_board(path):
    """Plain-data view of the board (pads, drills, outline segments, existing copper)."""
    import pcbnew

    mm = pcbnew.ToMM
    b = pcbnew.LoadBoard(path)
    pads = []
    for f in b.GetFootprints():
        for p in f.Pads():
            bb = p.GetBoundingBox()
            drill = p.GetDrillSize()
            npth = p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
            circ = p.GetShape() == pcbnew.PAD_SHAPE_CIRCLE
            sx, sy = mm(p.GetSizeX()), mm(p.GetSizeY())
            pads.append(
                dict(
                    ref=f.GetReference(),
                    fp=f.GetFPIDAsString(),
                    fx=mm(f.GetX()),
                    fy=mm(f.GetY()),
                    num=p.GetNumber(),
                    net=p.GetNetname(),
                    x=mm(p.GetX()),
                    y=mm(p.GetY()),
                    hw=mm(bb.GetWidth()) / 2.0,
                    hh=mm(bb.GetHeight()) / 2.0,
                    round=bool(circ and abs(sx - sy) < 1e-6),
                    top=bool(p.IsOnLayer(pcbnew.F_Cu)),
                    bot=bool(p.IsOnLayer(pcbnew.B_Cu)),
                    npth=bool(npth),
                    hole=(mm(drill.x), mm(drill.y)),
                    smd=p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD,
                )
            )
    edges = []  # polylines of Edge.Cuts shapes as segment tuples
    for d in b.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts or d.GetClass() != "PCB_SHAPE":
            continue
        s = d.GetShape()
        if s == pcbnew.SHAPE_T_SEGMENT:
            edges.append((mm(d.GetStartX()), mm(d.GetStartY()), mm(d.GetEndX()), mm(d.GetEndY())))
        elif s == pcbnew.SHAPE_T_RECT:
            x0, y0, x1, y1 = mm(d.GetStartX()), mm(d.GetStartY()), mm(d.GetEndX()), mm(d.GetEndY())
            edges += [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]
        elif s in (pcbnew.SHAPE_T_ARC, pcbnew.SHAPE_T_CIRCLE):
            if s == pcbnew.SHAPE_T_CIRCLE:
                c = d.GetCenter()
                cx, cy, r = mm(c.x), mm(c.y), mm(d.GetRadius())
                a0, sweep = 0.0, 2 * math.pi
            else:
                c = d.GetCenter()
                cx, cy, r = mm(c.x), mm(c.y), mm(d.GetRadius())
                sx_, sy_ = mm(d.GetStartX()), mm(d.GetStartY())
                a0 = math.atan2(sy_ - cy, sx_ - cx)
                sweep = math.radians(d.GetArcAngle().AsDegrees())
            n = max(8, int(abs(sweep) * r / 0.15))
            pts = [(cx + r * math.cos(a0 + sweep * k / n), cy + r * math.sin(a0 + sweep * k / n)) for k in range(n + 1)]
            edges += [pts[k] + pts[k + 1] for k in range(n)]
        elif s == pcbnew.SHAPE_T_POLY:
            ps = d.GetPolyShape()
            for oi in range(ps.OutlineCount()):
                ch = ps.Outline(oi)
                m = ch.PointCount()
                for k in range(m):
                    a, c2 = ch.CPoint(k), ch.CPoint((k + 1) % m)
                    edges.append((mm(a.x), mm(a.y), mm(c2.x), mm(c2.y)))
        else:
            raise SystemExit("route_regular: Edge.Cuts shape type %s is not handled; add it to extract_board()." % s)
    tracks = []
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            tracks.append(dict(kind="via", net=t.GetNetname(), x=mm(t.GetX()), y=mm(t.GetY()), d=mm(t.GetWidth()), drill=mm(t.GetDrillValue())))
        else:
            tracks.append(
                dict(
                    kind="seg",
                    net=t.GetNetname(),
                    layer=0 if t.GetLayer() == pcbnew.F_Cu else 1,
                    x1=mm(t.GetStart().x), y1=mm(t.GetStart().y), x2=mm(t.GetEnd().x), y2=mm(t.GetEnd().y),
                    w=mm(t.GetWidth()),
                )
            )
    return dict(pads=pads, edges=edges, tracks=tracks)


# ----------------------------------------------------------------------------- obstacle grid
class Grid:
    """Per-layer owner maps. own_t[L][cell]: 0 free, n>0 only net n may put a track centre here,
    -1 nobody. own_v likewise for a via centre (blocks both layers). Cells are j*NX+i."""

    def __init__(self, bbox, rules, netids):
        self.r = rules
        self.x0 = math.floor((bbox[0] - 2.0) / G)
        self.y0 = math.floor((bbox[1] - 2.0) / G)
        self.NX = int(math.ceil((bbox[2] + 2.0) / G)) - self.x0 + 1
        self.NY = int(math.ceil((bbox[3] + 2.0) / G)) - self.y0 + 1
        self.netids = netids
        shape = (self.NY, self.NX)
        self.t = [np.zeros(shape, np.int16), np.zeros(shape, np.int16)]
        self.v = [np.zeros(shape, np.int16), np.zeros(shape, np.int16)]
        self.rt = rules["clearance"] + rules["width"] / 2.0 + MARGIN  # track centre to foreign copper
        self.rv = rules["clearance"] + rules["via_d"] / 2.0 + MARGIN  # via centre to foreign copper
        self.views = None

    # cell <-> mm
    def cx(self, i):
        return (i + self.x0) * G

    def cy(self, j):
        return (j + self.y0) * G

    def ci(self, x):
        return int(round(x / G)) - self.x0

    def cj(self, y):
        return int(round(y / G)) - self.y0

    def _stamp(self, arr, x0, y0, x1, y1, R, net, dist):
        """dist(X, Y) -> distance grid of the sub-window; cells closer than R get owned."""
        i0 = max(int(math.floor((x0 - R) / G)) - self.x0, 0)
        i1 = min(int(math.ceil((x1 + R) / G)) - self.x0, self.NX - 1)
        j0 = max(int(math.floor((y0 - R) / G)) - self.y0, 0)
        j1 = min(int(math.ceil((y1 + R) / G)) - self.y0, self.NY - 1)
        if i0 > i1 or j0 > j1:
            return
        X = (np.arange(i0, i1 + 1) + self.x0) * G
        Y = (np.arange(j0, j1 + 1) + self.y0) * G
        D = dist(X[None, :], Y[:, None])
        sub = arr[j0 : j1 + 1, i0 : i1 + 1]
        m = D < R
        if net == -1:
            sub[m] = -1
        else:
            cur = sub[m]
            sub[m] = np.where(cur == 0, net, np.where(cur == net, net, -1))

    def stamp_rect(self, arr, cx, cy, hw, hh, R, net):
        def dist(X, Y):
            return np.hypot(np.maximum(np.abs(X - cx) - hw, 0.0), np.maximum(np.abs(Y - cy) - hh, 0.0))

        self._stamp(arr, cx - hw, cy - hh, cx + hw, cy + hh, R, net, dist)

    def stamp_disc(self, arr, cx, cy, rad, R, net):
        def dist(X, Y):
            return np.maximum(np.hypot(X - cx, Y - cy) - rad, 0.0)

        self._stamp(arr, cx - rad, cy - rad, cx + rad, cy + rad, R, net, dist)

    def stamp_seg(self, arr, ax, ay, bx, by, R, net):
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy or 1e-12

        def dist(X, Y):
            t = np.clip(((X - ax) * vx + (Y - ay) * vy) / L2, 0.0, 1.0)
            return np.hypot(X - (ax + t * vx), Y - (ay + t * vy))

        self._stamp(arr, min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), R, net, dist)

    def add_pads(self, pads):
        r = self.r
        for p in pads:
            nid = self.netids.get(p["net"], -1) if p["net"] else -1
            layers = [L for L, on in ((0, p["top"]), (1, p["bot"])) if on]
            if not p["npth"]:
                for L in layers:
                    if p["round"]:
                        self.stamp_disc(self.t[L], p["x"], p["y"], p["hw"], self.rt, nid)
                        self.stamp_disc(self.v[L], p["x"], p["y"], p["hw"], self.rv, nid)
                    else:
                        self.stamp_rect(self.t[L], p["x"], p["y"], p["hw"], p["hh"], self.rt, nid)
                        self.stamp_rect(self.v[L], p["x"], p["y"], p["hw"], p["hh"], self.rv, nid)
                if p["smd"]:  # no vias on surface-mount pads
                    for L in (0, 1):
                        self.stamp_rect(self.v[L], p["x"], p["y"], p["hw"], p["hh"], r["via_d"] / 2.0, -1)
            hx, hy = p["hole"]
            if hx > 0 and hy > 0:
                hw, hh = hx / 2.0, hy / 2.0
                for L in (0, 1):
                    if p["npth"]:  # unplated hole: no foreign-or-own copper within the hole clearance
                        self.stamp_rect(self.t[L], p["x"], p["y"], hw, hh, r["hole_clr"] + r["width"] / 2.0 + MARGIN, -1)
                    self.stamp_rect(
                        self.v[L], p["x"], p["y"], hw, hh,
                        max(r["hole_hole"] + r["via_drill"] / 2.0, r["hole_clr"] + r["via_d"] / 2.0) + MARGIN, -1,
                    )

    def add_edges(self, edges):
        r = self.r
        for (ax, ay, bx, by) in edges:
            self.stamp_seg(self.t[0], ax, ay, bx, by, r["edge_clr"] + r["width"] / 2.0 + MARGIN, -1)
            self.stamp_seg(self.t[1], ax, ay, bx, by, r["edge_clr"] + r["width"] / 2.0 + MARGIN, -1)
            for L in (0, 1):
                self.stamp_seg(self.v[L], ax, ay, bx, by, r["edge_clr"] + r["via_d"] / 2.0 + MARGIN, -1)

    def add_seg(self, net, L, ax, ay, bx, by, w):
        r = self.r
        nid = self.netids.get(net, -1)
        self.stamp_seg(self.t[L], ax, ay, bx, by, r["clearance"] + w / 2.0 + r["width"] / 2.0 + MARGIN, nid)
        self.stamp_seg(self.v[L], ax, ay, bx, by, r["clearance"] + w / 2.0 + r["via_d"] / 2.0 + MARGIN, nid)

    def add_via(self, net, x, y, d, drill):
        r = self.r
        nid = self.netids.get(net, -1)
        for L in (0, 1):
            self.stamp_disc(self.t[L], x, y, d / 2.0, r["clearance"] + r["width"] / 2.0 + MARGIN, nid)
            self.stamp_disc(self.v[L], x, y, d / 2.0, r["clearance"] + r["via_d"] / 2.0 + MARGIN, nid)
            self.stamp_disc(self.v[L], x, y, drill / 2.0, r["hole_hole"] + r["via_drill"] / 2.0 + MARGIN, -1)

    def freeze(self):
        """Python-fast flat views of the owner maps."""
        self.views = ([memoryview(a.reshape(-1)) for a in self.t], [memoryview(a.reshape(-1)) for a in self.v])


# ----------------------------------------------------------------------------- A*
def build_tables(P):
    nxt = {}
    for d in range(9):
        lst = []
        for nd in range(8):
            if d == 8:
                tc = 0.0
            else:
                turn = min((nd - d) % 8, (d - nd) % 8)
                if turn == 0:
                    tc = 0.0
                elif turn == 1:
                    tc = P["b45"]
                elif turn == 2:
                    tc = P["b90"]
                else:
                    continue
            diag = nd % 2 == 1
            if diag and not P["diag"]:
                continue
            lst.append((nd, tc))
        nxt[d] = lst
    step = []
    for L in (0, 1):
        row = []
        for nd in range(8):
            diag = nd % 2 == 1
            if diag:
                c = SQ2 * (1.0 + P["wd"])
            else:
                horiz = nd in (0, 4)
                pref = P["pref"][L] if P["pref"] else None
                wrong = pref is not None and ((pref == "h") != horiz)
                c = 1.0 + (P["ww"] if wrong else 0.0)
            row.append(c)
        step.append(row)
    return nxt, step


def astar(grid, net, srcs, goal_cells, goal_xy, win, P, cap):
    """srcs: iterable of (i,j,L). goal_cells: {(i,j): layer-bitmask}. Returns list of (i,j,L) or None."""
    NX = grid.NX
    ownt, ownv = grid.views
    nxt, step = build_tables(P)
    via = P["via"]
    wi0, wj0, wi1, wj1 = win
    gx, gy = goal_xy
    heap = []
    g = {}
    parent = {}
    cnt = 0
    c2 = 2.0 - SQ2

    def h(i, j):
        dx = abs(i - gx)
        dy = abs(j - gy)
        v = dx + dy - c2 * (dx if dx < dy else dy) - 1.5
        return v if v > 0 else 0.0

    for (i, j, L) in srcs:
        k = ((j * NX + i) * 2 + L) * 9 + 8
        if k not in g:
            g[k] = 0.0
            heapq.heappush(heap, (h(i, j), cnt, 0.0, i, j, L, 8))
            cnt += 1
    exp = 0
    final = None
    while heap:
        f, _, gc, i, j, L, d = heapq.heappop(heap)
        k = ((j * NX + i) * 2 + L) * 9 + d
        if gc > g[k]:
            continue
        m = goal_cells.get((i, j))
        if m is not None and (m >> L) & 1:
            final = k
            break
        exp += 1
        if exp > cap:
            return None
        own = ownt[L]
        base = j * NX + i
        for nd, tc in nxt[d]:
            di, dj = DIRS[nd]
            ni = i + di
            nj = j + dj
            if ni < wi0 or ni > wi1 or nj < wj0 or nj > wj1:
                continue
            o = own[nj * NX + ni]
            if o != 0 and o != net:
                continue
            ng = gc + step[L][nd] + tc
            nk = ((nj * NX + ni) * 2 + L) * 9 + nd
            if ng < g.get(nk, 1e18):
                g[nk] = ng
                parent[nk] = k
                heapq.heappush(heap, (ng + h(ni, nj), cnt, ng, ni, nj, L, nd))
                cnt += 1
        # via
        ov0 = ownv[0][base]
        ov1 = ownv[1][base]
        if (ov0 == 0 or ov0 == net) and (ov1 == 0 or ov1 == net):
            o2 = ownt[1 - L][base]
            if o2 == 0 or o2 == net:
                ng = gc + via
                nk = ((base) * 2 + (1 - L)) * 9 + 8
                if ng < g.get(nk, 1e18):
                    g[nk] = ng
                    parent[nk] = k
                    heapq.heappush(heap, (ng + h(i, j), cnt, ng, i, j, 1 - L, 8))
                    cnt += 1
    if final is None:
        return None
    path = []
    k = final
    while True:
        idx2 = k // 9
        L = idx2 % 2
        idx = idx2 // 2
        path.append((idx % NX, idx // NX, L))
        if k not in parent:
            break
        k = parent[k]
    path.reverse()
    return path


# ----------------------------------------------------------------------------- path -> copper
def path_to_items(path):
    """Merge a cell path into segments [(L,i1,j1,i2,j2)] and vias [(i,j)]."""
    segs, vias = [], []
    run_a = path[0]
    rd = None
    for a, c in zip(path, path[1:]):
        if a[2] != c[2]:
            if run_a[:2] != a[:2]:
                segs.append((a[2], run_a[0], run_a[1], a[0], a[1]))
            vias.append((a[0], a[1]))
            run_a, rd = c, None
            continue
        d = (c[0] - a[0], c[1] - a[1])
        if rd is None:
            rd = d
        elif d != rd:
            segs.append((a[2], run_a[0], run_a[1], a[0], a[1]))
            run_a, rd = a, d
    last = path[-1]
    if run_a[:2] != last[:2]:
        segs.append((last[2], run_a[0], run_a[1], last[0], last[1]))
    return segs, vias


def merge_collinear(segs, vias, protect):
    """Join two same-layer segments that meet at a cell nothing else uses (no pad end, via or
    third segment) and continue in one direction."""
    segs = list(dict.fromkeys(segs))
    vset = set(vias)
    changed = True
    while changed:
        changed = False
        ends = {}
        for n, (L, a, b, c, d) in enumerate(segs):
            ends.setdefault((L, a, b), []).append(n)
            ends.setdefault((L, c, d), []).append(n)
        for (L, x, y), lst in sorted(ends.items()):
            if len(lst) != 2 or (x, y) in protect or (x, y) in vset:
                continue
            s1, s2 = segs[lst[0]], segs[lst[1]]
            if lst[0] == lst[1]:
                continue
            p1 = (s1[3], s1[4]) if (s1[1], s1[2]) == (x, y) else (s1[1], s1[2])
            p2 = (s2[3], s2[4]) if (s2[1], s2[2]) == (x, y) else (s2[1], s2[2])
            v1 = (x - p1[0], y - p1[1])
            v2 = (p2[0] - x, p2[1] - y)
            if v1[0] * v2[1] - v1[1] * v2[0] == 0 and v1[0] * v2[0] + v1[1] * v2[1] > 0:
                new = (L, p1[0], p1[1], p2[0], p2[1])
                segs = [s for n, s in enumerate(segs) if n not in lst] + [new]
                changed = True
                break
    return sorted(segs), sorted(vias)


# ----------------------------------------------------------------------------- per-cluster routing
class Ctx:
    """Everything a worker needs; inherited through fork, never pickled."""

    grid = None
    rules = None
    profile = None
    pads_by_net = None
    netids = None
    fanout = False


def pad_cells(grid, p, W):
    cells = {}
    tol = min(PAD_TOL, max(p["hw"], p["hh"]))
    i0, i1 = grid.ci(p["x"] - tol), grid.ci(p["x"] + tol)
    j0, j1 = grid.cj(p["y"] - tol), grid.cj(p["y"] + tol)
    mask = (1 if p["top"] else 0) | (2 if p["bot"] else 0)
    for j in range(min(j0, j1), max(j0, j1) + 1):
        for i in range(min(i0, i1), max(i0, i1) + 1):
            if abs(grid.cx(i) - p["x"]) <= tol + 1e-9 and abs(grid.cy(j) - p["y"]) <= tol + 1e-9:
                cells[(i, j)] = mask
    return cells


def free_cell(grid, net, i, j, mask):
    ownt = grid.views[0]
    ok = 0
    for L in (0, 1):
        if (mask >> L) & 1:
            o = ownt[L][j * grid.NX + i]
            if o == 0 or o == net:
                ok |= 1 << L
    return ok


def route_net(grid, name, pads, P, rules, log, anchor_cells=None, extra_goals=None):
    """Connect `pads` (plain pad dicts) of one net. Returns (segs, vias, protect) or None.
    anchor_cells: optional {(i,j,L)} existing tree to attach to (used for chip fanout)."""
    net = grid.netids[name]
    cellsets = []
    for p in pads:
        cs = pad_cells(grid, p, rules["width"])
        cs = {c: m2 for c, m in cs.items() for m2 in [free_cell(grid, net, c[0], c[1], m)] if m2}
        if not cs:
            log("  %s: pad %s.%s has no free cell for a track end (blocked by neighbouring copper)" % (name, p["ref"], p["num"]))
            return None
        cellsets.append(cs)
    allx = [grid.ci(p["x"]) for p in pads]
    ally = [grid.cj(p["y"]) for p in pads]
    if anchor_cells:
        allx += [c[0] for c in anchor_cells]
        ally += [c[1] for c in anchor_cells]
    wm = int(round(3.0 / G))
    for attempt, (marg, cap) in enumerate(((wm, 250000), (int(round(3.9 / G)), 900000), (int(round(12.0 / G)), 2500000))):
        win = (max(min(allx) - marg, 0), max(min(ally) - marg, 0), min(max(allx) + marg, grid.NX - 1), min(max(ally) + marg, grid.NY - 1))
        res = _route_attempt(grid, net, name, pads, cellsets, P, win, cap, anchor_cells, log)
        if res is not None:
            return res
    return None


def _route_attempt(grid, net, name, pads, cellsets, P, win, cap, anchor_cells, log):
    n = len(pads)
    tree = set()
    segs, vias, protect = [], [], set()
    connected = []
    todo = list(range(n))
    if anchor_cells:  # fanout: the existing bus tree is the target tree
        tree = set(anchor_cells)
    else:
        # deterministic start: leftmost, then topmost pad
        todo.sort(key=lambda k: (pads[k]["x"], pads[k]["y"], pads[k]["ref"], pads[k]["num"]))
        s = todo.pop(0)
        connected.append(s)
        for (i, j), m in cellsets[s].items():
            for L in (0, 1):
                if (m >> L) & 1:
                    tree.add((i, j, L))
    while todo:
        # nearest unconnected pad to the connected set (Manhattan on pad centres); tie -> order
        def dist(k):
            if connected:
                return min(abs(pads[k]["x"] - pads[c]["x"]) + abs(pads[k]["y"] - pads[c]["y"]) for c in connected)
            return min(abs(grid.cx(c[0]) - pads[k]["x"]) + abs(grid.cy(c[1]) - pads[k]["y"]) for c in tree)

        k = min(todo, key=lambda q: (dist(q), pads[q]["x"], pads[q]["y"], pads[q]["ref"], pads[q]["num"]))
        todo.remove(k)
        goal = cellsets[k]
        goal_xy = (grid.ci(pads[k]["x"]), grid.cj(pads[k]["y"]))
        path = astar(grid, net, sorted(tree), goal, goal_xy, win, P, cap)
        if path is None:
            log("  %s: no path to %s.%s within window/cap" % (name, pads[k]["ref"], pads[k]["num"]))
            return None
        s2, v2 = path_to_items(path)
        segs += s2
        vias += v2
        connected.append(k)
        for c in path:
            tree.add(c)
    for cs in cellsets:  # a vertex on any pad of this net is never merged away
        protect.update(cs)
    return segs, vias, protect


def run_cluster(args):
    cid, tasks = args
    grid, rules, prof = Ctx.grid, Ctx.rules, Ctx.profile
    out = []
    t0 = time.time()
    lines = []

    def log(s):
        lines.append(s)

    for task in tasks:
        cls, name, pads = task["cls"], task["net"], task["pads"]
        P = PROFILES[prof]["fan" if task["fan"] else cls]
        anchor = None
        if task["fan"]:
            anchor = task["anchor"]
        ts = time.time()
        res = route_net(grid, name, pads, P, rules, log, anchor_cells=anchor)
        if res is None:
            out.append(dict(cls=cls, net=name, fan=task["fan"], ok=False, segs=[], vias=[]))
            lines.append("%-6s %-22s FAIL   %.1fs" % (cls, name, time.time() - ts))
            continue
        segs, vias, protect = res
        # protect every pad terminal so merging never removes a vertex at a pad
        segs, vias = merge_collinear(segs, vias, protect)
        nid = grid.netids[name]
        w = rules["width"]
        for (L, a, b, c, d) in segs:
            grid.add_seg(name, L, grid.cx(a), grid.cy(b), grid.cx(c), grid.cy(d), w)
        for (a, b) in vias:
            grid.add_via(name, grid.cx(a), grid.cy(b), rules["via_d"], rules["via_drill"])
        out.append(dict(cls=cls, net=name, fan=task["fan"], ok=True, segs=segs, vias=vias))
        lines.append("%-6s %-22s ok seg=%d via=%d  %.1fs" % (cls, name, len(segs), len(vias), time.time() - ts))
    if Ctx.fanout:
        out += run_fanout(grid, rules, prof, out, Ctx.pads_by_net, lines)
    lines.append("cluster %d done in %.1fs" % (cid, time.time() - t0))
    return cid, out, lines


# ----------------------------------------------------------------------------- planning
def plan_clusters(pads_by_net, netids, tasks_by_net):
    """Group nets whose (dilated) pad boxes overlap so that clusters cannot influence each other."""
    names = sorted(tasks_by_net)
    box = {}
    for n in names:
        xs = [p["x"] for p in pads_by_net[n]]
        ys = [p["y"] for p in pads_by_net[n]]
        d = 5.0
        box[n] = (min(xs) - d, min(ys) - d, max(xs) + d, max(ys) + d)
    parent = {n: n for n in names}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            A, B = box[names[a]], box[names[b]]
            if A[0] <= B[2] and B[0] <= A[2] and A[1] <= B[3] and B[1] <= A[3]:
                parent[find(names[a])] = find(names[b])
    groups = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    return sorted(groups.values(), key=lambda g: (min(box[n][0] for n in g), min(box[n][1] for n in g), g[0]))


def hpwl(pads):
    xs = [p["x"] for p in pads]
    ys = [p["y"] for p in pads]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def fmt(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def uuid_for(key):
    h = hashlib.sha1(key.encode()).hexdigest()
    return "%s%s-4%s-8%s-%s" % (ROUTER_UUID_PREFIX, h[0:4], h[4:7], h[7:10], h[10:22])


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_text(results, grid, rules, selected_classes):
    out = []
    for r in results:
        if not r["ok"]:
            continue
        for (L, a, b, c, d) in r["segs"]:
            x1, y1, x2, y2 = fmt(grid.cx(a)), fmt(grid.cy(b)), fmt(grid.cx(c)), fmt(grid.cy(d))
            lay = "F.Cu" if L == 0 else "B.Cu"
            key = "seg|%s|%s|%s,%s|%s,%s" % (r["net"], lay, x1, y1, x2, y2)
            out.append(
                "\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width %s)\n\t\t(layer %s)\n\t\t(net %s)\n\t\t(uuid %s)\n\t)\n"
                % (x1, y1, x2, y2, fmt(rules["width"]), q(lay), q(r["net"]), q(uuid_for(key)))
            )
        for (a, b) in r["vias"]:
            x, y = fmt(grid.cx(a)), fmt(grid.cy(b))
            key = "via|%s|%s,%s" % (r["net"], x, y)
            out.append(
                "\t(via\n\t\t(at %s %s)\n\t\t(size %s)\n\t\t(drill %s)\n\t\t(layers \"F.Cu\" \"B.Cu\")\n\t\t(net %s)\n\t\t(uuid %s)\n\t)\n"
                % (x, y, fmt(rules["via_d"]), fmt(rules["via_drill"]), q(r["net"]), q(uuid_for(key)))
            )
    return "".join(out)


BLOCK = re.compile(r"\t\((?:segment|via)\n(?:\t\t.*\n|\t\t\t.*\n)+?\t\)\n")


def strip_router_copper(text):
    """Remove every top-level segment/via block whose uuid starts with the router prefix."""
    removed = 0

    def sub(m):
        nonlocal removed
        if '(uuid "%s' % ROUTER_UUID_PREFIX in m.group(0):
            removed += 1
            return ""
        return m.group(0)

    return BLOCK.sub(sub, text), removed


def kicad_running():
    ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return any("KiCad.app/Contents/MacOS/kicad" in l and "kicad-cli" not in l for l in ps.splitlines())


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.abspath(__file__))
    default_board = os.path.join(here, "..", "fkb-109j-big", "fkb-109j-big.kicad_pcb")
    ap.add_argument("--board", default=default_board)
    ap.add_argument("--out", help="write here instead of editing --board in place")
    ap.add_argument("--profile", choices=list(PROFILES), default="tidy")
    ap.add_argument("--classes", default="node,fnav,row,col", help="comma list of node,fnav,row,col")
    ap.add_argument("--no-fanout", action="store_true", help="skip connecting chip pins of row/column nets to their bus")
    ap.add_argument("--jobs", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--swap-pref", action="store_true", help="horizontal preferred on F.Cu and vertical on B.Cu instead")
    ap.add_argument("--force", action="store_true", help="skip the KiCad-is-running check")
    ap.add_argument("--only", help="comma list of net names to route (debug)")
    ap.add_argument("--left-file", help="write the pads left on purpose here (default tools/left_pads.txt when editing the default board in place)")
    ap.add_argument("--log", help="write the per-net log here as well")
    a = ap.parse_args()

    board = os.path.abspath(a.board)
    dst = os.path.abspath(a.out) if a.out else board
    if not a.force and kicad_running():
        raise SystemExit("route_regular: KiCad is running and a save from it would overwrite %s. Quit KiCad (or pass --force for a scratch --out copy)." % dst)
    classes = [c for c in a.classes.split(",") if c]
    for c in classes:
        if c not in CLASS_ORDER:
            raise SystemExit("route_regular: unknown class %r; use a subset of %s." % (c, CLASS_ORDER))
    t_start = time.time()
    text = open(board, encoding="utf-8").read()
    text, removed = strip_router_copper(text)
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "in.kicad_pcb")
        open(tmp, "w", encoding="utf-8").write(text)
        rules = read_rules(os.path.join(os.path.dirname(board), os.path.basename(board).replace(".kicad_pcb", ".kicad_pro")))
        data = extract_board(tmp)

    names = sorted({p["net"] for p in data["pads"] if p["net"]})
    netids = {n: k + 1 for k, n in enumerate(names)}
    pads_by_net = {}
    for p in data["pads"]:
        if p["net"]:
            pads_by_net.setdefault(p["net"], []).append(p)
    xs = [e[0] for e in data["edges"]] + [e[2] for e in data["edges"]]
    ys = [e[1] for e in data["edges"]] + [e[3] for e in data["edges"]]
    grid = Grid((min(xs), min(ys), max(xs), max(ys)), rules, netids)
    grid.add_pads(data["pads"])
    grid.add_edges(data["edges"])
    for t in data["tracks"]:  # copper that is not ours stays an obstacle
        if t["kind"] == "via":
            grid.add_via(t["net"], t["x"], t["y"], t["d"], t["drill"])
        else:
            grid.add_seg(t["net"], t["layer"], t["x1"], t["y1"], t["x2"], t["y2"], t["w"])
    grid.freeze()

    # pads inside a popout perforation ring are sacrificed on purpose (CLAUDE.md): never routed
    sacrificed = set()
    left = []
    left_pads = set()
    rings = {}
    for p in data["pads"]:
        if "popout-ring" in p["fp"]:
            rings.setdefault(p["ref"], []).append(p)
    for ref, rp in sorted(rings.items()):
        cx, cy = rp[0]["fx"], rp[0]["fy"]
        rad = max(math.hypot(p["x"] - cx, p["y"] - cy) for p in rp)
        for p in data["pads"]:
            if p["net"] and "popout-ring" not in p["fp"] and math.hypot(p["x"] - cx, p["y"] - cy) < rad:
                sacrificed.add(id(p))
                if classify_net(p["net"]):
                    left.append("%s: pad %s.%s lies inside popout ring %s, sacrificed on purpose" % (p["net"], p["ref"], p["num"], ref))
                    left_pads.add((p["net"], p["ref"], p["num"]))
    only = set(a.only.split(",")) if a.only else None
    tasks_by_net = {}
    for n in names:
        c = classify_net(n)
        if c is None or c not in classes or (only and n not in only):
            continue
        pads = pads_by_net[n]
        bus = [p for p in pads if not is_chip(p["ref"]) and id(p) not in sacrificed]
        if c == "node":  # alternate-layout switch footprints can sit far from the diode: leave those pads
            diode = [p for p in bus if p["ref"].startswith("D")]
            if diode:
                far = [p for p in bus if not p["ref"].startswith("D") and abs(p["x"] - diode[0]["x"]) + abs(p["y"] - diode[0]["y"]) > NODE_REACH]
                for p in far:
                    left.append("%s: pad %s.%s is %.0f mm from its diode (alternate-layout footprint), left unrouted" % (n, p["ref"], p["num"], abs(p["x"] - diode[0]["x"]) + abs(p["y"] - diode[0]["y"])))
                    left_pads.add((n, p["ref"], p["num"]))
                bus = [p for p in bus if p not in far]
        if c == "col" and len(bus) > 2:  # a column is vertical: drop alternate-layout pads far to the side
            med = sorted(p["x"] for p in bus)[len(bus) // 2]
            far = [p for p in bus if abs(p["x"] - med) > COL_REACH]
            for p in far:
                left.append("%s: pad %s.%s is %.0f mm to the side of its column (alternate-layout footprint), left unrouted" % (n, p["ref"], p["num"], abs(p["x"] - med)))
                left_pads.add((n, p["ref"], p["num"]))
            bus = [p for p in bus if p not in far]
        if len(bus) < 2:
            continue
        tasks_by_net[n] = dict(cls=c, net=n, pads=sorted(bus, key=lambda p: (p["x"], p["y"], p["ref"], p["num"])), fan=False)
    # clusters share no copper interaction, so they route in parallel and merge in a fixed order
    pads_for_plan = {n: tasks_by_net[n]["pads"] + [p for p in pads_by_net[n] if is_chip(p["ref"])] for n in tasks_by_net}
    clusters = plan_clusters(pads_for_plan, netids, tasks_by_net)
    jobs = []
    for cid, grp in enumerate(clusters):
        order = sorted(grp, key=lambda n: (CLASS_ORDER.index(tasks_by_net[n]["cls"]), hpwl(tasks_by_net[n]["pads"]), n))
        jobs.append((cid, [tasks_by_net[n] for n in order]))
    if a.swap_pref:
        for cl in PROFILES[a.profile].values():
            if cl["pref"]:
                cl["pref"] = (cl["pref"][1], cl["pref"][0])
    Ctx.grid, Ctx.rules, Ctx.profile, Ctx.fanout, Ctx.pads_by_net = grid, rules, a.profile, not a.no_fanout, pads_by_net
    print("route_regular: %d nets in %d clusters, profile %s, grid %dx%d" % (len(tasks_by_net), len(jobs), a.profile, grid.NX, grid.NY), flush=True)

    results_by_cid = {}
    logs = []
    nproc = max(1, min(a.jobs, len(jobs)))
    # largest clusters first so the pool stays busy; the merge order below is by cluster id
    work = sorted(jobs, key=lambda j: -sum(len(t["pads"]) for t in j[1]))
    if nproc == 1:
        outs = map(run_cluster, work)
    else:
        pool = multiprocessing.get_context("fork").Pool(nproc)
        outs = pool.imap_unordered(run_cluster, work)
    for cid, res, lines in outs:
        results_by_cid[cid] = res
        logs += ["[c%d] %s" % (cid, l) for l in lines]
        print("cluster %d finished (%d nets, %.0fs elapsed)" % (cid, len(res), time.time() - t_start), flush=True)
    if nproc > 1:
        pool.close()
        pool.join()
    results = [r for cid in sorted(results_by_cid) for r in results_by_cid[cid]]

    body = emit_text(results, grid, rules, classes)
    tail = "\t(embedded_fonts no)\n)"
    if text.count(tail) != 1:
        raise SystemExit("route_regular: %s does not end with the expected '(embedded_fonts no)' trailer; the file layout changed. Insert the copper before the final ')' by hand or update the trailer check." % board)
    new = text.replace(tail, body + tail)
    open(dst, "w", encoding="utf-8").write(new)
    if a.log:
        open(a.log, "w").write("\n".join(logs) + "\n")
    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    for l in sorted(set(left)):
        print("LEFT " + l)
    lf = a.left_file or (None if a.out else os.path.join(here, "left_pads.txt"))
    if lf:
        open(lf, "w").write("".join("%s\t%s\t%s\n" % t for t in sorted(left_pads)))
    print("removed %d old router items; routed %d, failed %d" % (removed, len(ok), len(bad)))
    for r in bad:
        print("FAILED net %s (%s): left unrouted, no copper written for it" % (r["net"], r["cls"]))
    print("wrote %s in %.0fs" % (dst, time.time() - t_start))
    return 0


def run_fanout(grid, rules, prof, results, pads_by_net, logs):
    """Connect each chip pin of a routed row/column bus to its tree (one attempt per pin)."""
    out = []
    P = PROFILES[prof]["fan"]
    for r in results:
        if not r["ok"] or r["cls"] not in ("row", "col"):
            continue
        chips = [p for p in pads_by_net[r["net"]] if is_chip(p["ref"])]
        tree = set()
        for (L, a, b, c, d) in r["segs"]:
            n = max(abs(c - a), abs(d - b))
            for s in range(n + 1):
                tree.add((a + (c - a) * s // n if n else a, b + (d - b) * s // n if n else b, L))
        for p in chips:
            res = route_net(grid, r["net"], [p], P, rules, lambda s: logs.append("fan " + s), anchor_cells=sorted(tree))
            if res is None:
                continue
            segs, vias, protect = res
            segs, vias = merge_collinear(segs, vias, protect)
            for (L, a, b, c, d) in segs:
                grid.add_seg(r["net"], L, grid.cx(a), grid.cy(b), grid.cx(c), grid.cy(d), rules["width"])
            for (a, b) in vias:
                grid.add_via(r["net"], grid.cx(a), grid.cy(b), rules["via_d"], rules["via_drill"])
            out.append(dict(cls=r["cls"], net=r["net"], fan=True, ok=True, segs=segs, vias=vias))
    return out


if __name__ == "__main__":
    sys.exit(main())
