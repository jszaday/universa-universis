#!/usr/bin/env python3
"""Independent checks for the routed board (pcbnew Python; does not use the router's geometry).

  connectivity BOARD [LEFT]     per-net copper connectivity (pads + tracks + vias), by class
  metrics BOARD                 segments, bends and vias per net and class
  same-as-base BASE BOARD       Edge.Cuts set and every footprint position/angle/layer unchanged
  selftest BOARD BASE [LEFT]    negative controls: each of the checks above must fail on a damaged copy

Exit code 0 means every claim held; 1 means a check failed (the message names the net or item).
"""
import collections
import math
import os
import re
import sys
import tempfile

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_regular import ROUTER_UUID_PREFIX, classify_net, is_chip  # noqa: E402  (class rule only)

mm = pcbnew.ToMM


# ----------------------------------------------------------------------------- connectivity
class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def components(b):
    """{net: (items, DSU)} with items = ('pad'|'trk'|'via', object)."""
    by = collections.defaultdict(list)
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                by[p.GetNetname()].append(("pad", p))
    for t in b.GetTracks():
        by[t.GetNetname()].append(("via" if t.GetClass() == "PCB_VIA" else "trk", t))
    out = {}
    for net, items in by.items():
        d = DSU(len(items))
        for a in range(len(items)):
            for c in range(a + 1, len(items)):
                if touches(items[a], items[c]):
                    d.union(a, c)
        out[net] = (items, d)
    return out


def _on(kind, o, layer):
    if kind == "trk":
        return o.GetLayer() == layer
    return o.IsOnLayer(layer)  # pads and vias


def _ends(o):
    return [o.GetStart(), o.GetEnd()]


def touches(A, B):
    (ka, a), (kb, b) = A, B
    if ka == "pad" and kb == "pad":
        return False  # two pads connect only through copper
    layers = (pcbnew.F_Cu, pcbnew.B_Cu)
    if not any(_on(ka, a, L) and _on(kb, b, L) for L in layers):
        return False
    if ka == "trk":
        pts_a = _ends(a)
    else:
        pts_a = [a.GetPosition()]
    if kb == "trk":
        pts_b = _ends(b)
    else:
        pts_b = [b.GetPosition()]
    if kb != "trk" and any(b.HitTest(p) for p in pts_a if ka == "trk"):
        return True
    if ka != "trk" and any(a.HitTest(p) for p in pts_b if kb == "trk"):
        return True
    if ka == "trk" and kb == "trk":
        return any(b.HitTest(p) for p in pts_a) or any(a.HitTest(p) for p in pts_b)
    if ka != "trk" and kb != "trk":  # via on a pad
        return a.HitTest(b.GetPosition()) if ka == "pad" else b.HitTest(a.GetPosition())
    return False


def read_left(path):
    """Pads the router leaves on purpose: set of (net, ref, pad number)."""
    if not path:
        return set()
    return {tuple(l.rstrip("\n").split("\t")) for l in open(path) if l.strip()}


def net_status(items, d, left=frozenset()):
    """(bus_connected, all_connected) where bus ignores chip (U*) pins and pads in `left`."""
    pads = [
        k for k, (kind, o) in enumerate(items)
        if kind == "pad" and (o.GetNetname(), o.GetParentFootprint().GetReference(), o.GetNumber()) not in left
    ]
    allroots = {d.find(k) for k in pads}
    busroots = {d.find(k) for k in pads if not is_chip(items[k][1].GetParentFootprint().GetReference())}
    return len(busroots) <= 1, len(allroots) <= 1


def cmd_connectivity(path, quiet=False, left=frozenset(), names_out=None):
    b = pcbnew.LoadBoard(path)
    comp = components(b)
    rows = collections.defaultdict(lambda: [0, 0, 0, 0])  # nets with copper, bus ok, complete, bad
    bad = []
    for net, (items, d) in sorted(comp.items()):
        cls = classify_net(net)
        has_track = any(k != "pad" for k, _ in items)
        if cls is None or not has_track:
            continue
        bus, full = net_status(items, d, left)
        r = rows[cls]
        r[0] += 1
        r[1] += bus
        r[2] += full
        if not bus:
            bad.append(net)
            r[3] += 1
    if not quiet:
        print("class  nets-with-copper  bus-connected  fully-connected(incl. chip pins)  broken")
        for cls in ("node", "fnav", "row", "col"):
            if cls in rows:
                print("%-6s %16d %14d %33d %7d" % (cls, *rows[cls]))
    for n in bad:
        print("DISCONNECTED: net %s has copper but its non-chip pads are not one component" % n)
    if names_out is not None:
        names_out += bad
    return 1 if bad else 0


# ----------------------------------------------------------------------------- metrics
def cmd_metrics(path, quiet=False):
    b = pcbnew.LoadBoard(path)
    per = {}
    nets = collections.defaultdict(list)
    for t in b.GetTracks():
        nets[t.GetNetname()].append(t)
    for net, items in nets.items():
        cls = classify_net(net)
        if cls is None:
            continue
        segs = [t for t in items if t.GetClass() != "PCB_VIA"]
        vias = [t for t in items if t.GetClass() == "PCB_VIA"]
        ends = collections.defaultdict(list)
        for t in segs:
            for k, p in enumerate(_ends(t)):
                ends[(t.GetLayer(), p.x, p.y)].append((t, k))
        b45 = b90 = 0
        for key, lst in ends.items():
            if len(lst) != 2:
                continue
            (t1, k1), (t2, k2) = lst
            v1 = _ends(t1)
            v2 = _ends(t2)
            o1 = v1[1 - k1]
            o2 = v2[1 - k2]
            ax, ay = o1.x - key[1], o1.y - key[2]
            bx, by = o2.x - key[1], o2.y - key[2]
            cosang = (ax * bx + ay * by) / (math.hypot(ax, ay) * math.hypot(bx, by) or 1)
            ang = math.degrees(math.acos(max(-1, min(1, cosang))))
            if abs(ang - 180) < 1:
                continue
            if abs(ang - 135) < 1:
                b45 += 1
            elif abs(ang - 90) < 1:
                b90 += 1
            else:
                b45 += 1  # any other kink counts as a bend, filed with the 45s
        per[net] = (cls, len(segs), b45 + b90, b90, len(vias))
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for net, (cls, s, bnd, b90, v) in per.items():
        a = agg[cls]
        a[0] += 1
        a[1] += s
        a[2] += bnd
        a[3] += b90
        a[4] += v
    if not quiet:
        print("class  nets  segments  seg/net  bends  bends/net  right-angle  vias  vias/net")
        for cls in ("node", "fnav", "row", "col"):
            if cls in agg:
                n, s, bn, b9, v = agg[cls]
                print("%-6s %4d %9d %8.2f %6d %10.2f %12d %5d %9.2f" % (cls, n, s, s / n, bn, bn / n, b9, v, v / n))
    return per


# ----------------------------------------------------------------------------- unchanged placement/outline
def snapshot(path):
    b = pcbnew.LoadBoard(path)
    fps = {}
    for f in b.GetFootprints():
        fps[f.GetReference() + "|" + f.GetFPIDAsString()] = (
            round(mm(f.GetX()), 4), round(mm(f.GetY()), 4), round(f.GetOrientationDegrees(), 3), f.GetLayerName())
    edge = []
    items = list(b.GetDrawings())
    for f in b.GetFootprints():
        items += list(f.GraphicalItems())
    for d in items:
        if d.GetLayer() != pcbnew.Edge_Cuts or d.GetClass() != "PCB_SHAPE":
            continue
        s = d.GetShape()
        r = lambda v: round(mm(v), 3)
        edge.append((s, r(d.GetStartX()), r(d.GetStartY()), r(d.GetEndX()), r(d.GetEndY()), r(d.GetCenter().x), r(d.GetCenter().y), r(d.GetWidth())))
    return fps, sorted(edge)


def cmd_same(base, path):
    fa, ea = snapshot(base)
    fb, eb = snapshot(path)
    bad = 0
    if ea != eb:
        bad += 1
        print("EDGE.CUTS differs: %d items in base, %d in board, %d in base only, %d in board only" % (
            len(ea), len(eb), len(set(ea) - set(eb)), len(set(eb) - set(ea))))
    for k in sorted(set(fa) | set(fb)):
        if fa.get(k) != fb.get(k):
            bad += 1
            print("FOOTPRINT %s differs: base %s, board %s" % (k, fa.get(k), fb.get(k)))
    if not bad:
        print("same-as-base: %d Edge.Cuts items and %d footprints identical" % (len(ea), len(fa)))
    return 1 if bad else 0


# ----------------------------------------------------------------------------- negative controls
def cmd_selftest(path, base, left=frozenset()):
    ok = True
    with tempfile.TemporaryDirectory() as td:
        text = open(path, encoding="utf-8").read()
        # 1. drop one router segment of a node link: connectivity must fail
        m = re.search(r'\t\(segment\n(?:\t\t.*\n)+?\t\)\n', text)
        blocks = [m2 for m2 in re.finditer(r'\t\(segment\n(?:\t\t.*\n|\t\t\t.*\n)+?\t\)\n', text) if '(uuid "%s' % ROUTER_UUID_PREFIX in m2.group(0) and re.search(r'\(net "Net-\(D\d+-A\)"\)', m2.group(0))]
        if not blocks:
            print("selftest: no router node-link segment found to delete")
            return 1
        blk = blocks[0]
        damaged = os.path.join(td, "damaged.kicad_pcb")
        open(damaged, "w", encoding="utf-8").write(text[: blk.start()] + text[blk.end():])
        victim = re.search(r'\(net "([^"]+)"\)', blk.group(0)).group(1)
        base_bad = []
        cmd_connectivity(path, quiet=True, left=left, names_out=base_bad)
        bad = []
        cmd_connectivity(damaged, quiet=True, left=left, names_out=bad)
        good = (base_bad == [] and bad == [victim])
        print("negative control connectivity (deleted one segment of %s): %s" % (victim, "PASS (only that net reported disconnected)" if good else "FAIL (reported %s; undamaged board reported %s)" % (bad, base_bad)))
        ok &= good
        # 2. move one footprint and delete one Edge.Cuts item: same-as-base must fail on both
        b = pcbnew.LoadBoard(path)
        fp = list(b.GetFootprints())[0]
        fp.SetPosition(pcbnew.VECTOR2I(fp.GetX() + 1000000, fp.GetY()))
        moved = os.path.join(td, "moved.kicad_pcb")
        b.Save(moved)
        rc = cmd_same(base, moved)
        print("negative control moved footprint: %s" % ("PASS" if rc == 1 else "FAIL"))
        ok &= rc == 1
        b = pcbnew.LoadBoard(path)
        e = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts][0]
        b.Remove(e)
        cut = os.path.join(td, "cut.kicad_pcb")
        b.Save(cut)
        rc = cmd_same(base, cut)
        print("negative control removed Edge.Cuts item: %s" % ("PASS" if rc == 1 else "FAIL"))
        ok &= rc == 1
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    c = sys.argv[1]
    if c == "connectivity":
        sys.exit(cmd_connectivity(sys.argv[2], left=read_left(sys.argv[3] if len(sys.argv) > 3 else None)))
    if c == "metrics":
        cmd_metrics(sys.argv[2])
    elif c == "same-as-base":
        sys.exit(cmd_same(sys.argv[2], sys.argv[3]))
    elif c == "selftest":
        sys.exit(cmd_selftest(sys.argv[2], sys.argv[3], read_left(sys.argv[4] if len(sys.argv) > 4 else None)))
    else:
        sys.exit(__doc__)
