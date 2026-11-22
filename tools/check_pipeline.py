#!/usr/bin/env python3
"""Pipeline checks that count zone fills as copper (KiCad's Python; the board must carry filled zones).

  connectivity BOARD LEFT [ALLOW]  every net's pads, tracks, vias and zone-fill islands as one copper graph; exit 1
                                   if a net outside the allowed list is more than one component. LEFT is
                                   tools/left_pads.txt (pads left on purpose, ignored); ALLOW is an optional file of
                                   'net<TAB>reason' lines for nets that may stay split.
  zone-clearance BOARD             every zone-fill island keeps the design clearance from every foreign-net pad, track
                                   and via on its layer (shortdet.py skips zones); exit 1 on a violation
  selftest BOARD LEFT              negative controls: a deleted zone must split a GND net, and a foreign via dropped
                                   into a fill must fail zone-clearance

Connectivity model: a pad (not NPTH), track or via joins a same-net item when their copper touches on a shared layer;
a via joins both layers; a zone fill island joins every same-net item its polygon touches. Different nets never join.
"""
import collections
import os
import sys
import tempfile

import pcbnew

mm = pcbnew.ToMM
nm = pcbnew.FromMM
CLEARANCE = 0.2  # mm, the board's design clearance (Default net class)


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


def islands(z, layer):
    """One SHAPE_POLY_SET per fill island of zone z on layer."""
    ps = z.GetFilledPolysList(layer)
    out = []
    for i in range(ps.OutlineCount()):
        q = pcbnew.SHAPE_POLY_SET()
        q.AddOutline(ps.COutline(i))
        for h in range(ps.HoleCount(i)):
            q.AddHole(ps.CHole(i, h), 0)
        out.append(q)
    return out


def layers_of(it):
    return [L for L in (pcbnew.F_Cu, pcbnew.B_Cu) if it.IsOnLayer(L)]


def collect(b):
    """[(kind, obj, layer_or_None, shape_by_layer, bbox, netname)]; vias are on both layers."""
    items = []
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or not p.GetNetname():
                continue
            items.append(("pad", p, p.GetNetname()))
    for t in b.GetTracks():
        if t.GetNetname():
            items.append(("via" if t.GetClass() == "PCB_VIA" else "trk", t, t.GetNetname()))
    return items


def touching(shape_item, poly, layer, clearance=0):
    return poly.Collide(shape_item.GetEffectiveShape(layer), clearance)


def build(b):
    """Return (nodes, by_net): node = dict(kind, obj, net, layers, shapes{layer: shape}, bb, poly)."""
    nodes = []
    for kind, o, net in collect(b):
        Ls = layers_of(o)
        nodes.append(dict(kind=kind, obj=o, net=net, layers=Ls, shapes={L: o.GetEffectiveShape(L) for L in Ls}, bb=o.GetBoundingBox(), poly=None))
    for z in b.Zones():
        if not z.GetNetname() or z.GetIsRuleArea():
            continue
        for L in (pcbnew.F_Cu, pcbnew.B_Cu):
            if not z.IsOnLayer(L):
                continue
            for q in islands(z, L):
                nodes.append(dict(kind="zone", obj=z, net=z.GetNetname(), layers=[L], shapes={}, bb=q.BBox(), poly=q))
    by = collections.defaultdict(list)
    for n in nodes:
        by[n["net"]].append(n)
    return by


def join(a, c):
    if set(a["layers"]) & set(c["layers"]) == set():
        return False
    if a["kind"] == "pad" and c["kind"] == "pad":
        return False
    if a["kind"] == "zone" and c["kind"] == "zone":
        return False
    if not a["bb"].Intersects(c["bb"]):
        return False
    for L in set(a["layers"]) & set(c["layers"]):
        if a["kind"] == "zone":
            if a["poly"].Collide(c["shapes"][L], 0):
                return True
        elif c["kind"] == "zone":
            if c["poly"].Collide(a["shapes"][L], 0):
                return True
        elif a["shapes"][L].Collide(c["shapes"][L], 0):
            return True
    return False


def components(b, left=frozenset()):
    """{net: list of components, each a list of node descriptions}; pads in `left` are dropped."""
    by = build(b)
    out = {}
    for net, nodes in by.items():
        nodes = [n for n in nodes if not (n["kind"] == "pad" and (net, n["obj"].GetParentFootprint().GetReference(), n["obj"].GetNumber()) in left)]
        d = DSU(len(nodes))
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if join(nodes[i], nodes[j]):
                    d.union(i, j)
        comp = collections.defaultdict(list)
        for i, n in enumerate(nodes):
            comp[d.find(i)].append(n)
        out[net] = [c for c in comp.values() if any(n["kind"] == "pad" for n in c)]
    return out


def describe(c):
    pads = sorted("%s.%s" % (n["obj"].GetParentFootprint().GetReference(), n["obj"].GetNumber()) for n in c if n["kind"] == "pad")
    return ",".join(pads[:6]) + ("..." if len(pads) > 6 else "")


def read_pairs(path, cols):
    if not path or not os.path.exists(path):
        return {}
    out = {}
    for l in open(path):
        if l.strip():
            t = l.rstrip("\n").split("\t")
            out[tuple(t[:cols])] = t[cols:]
    return out


def cmd_connectivity(path, left_path, allow_path=None, quiet=False):
    b = pcbnew.LoadBoard(path)
    left = set(read_pairs(left_path, 3))
    allow = {k[0] for k in read_pairs(allow_path, 1)}
    comp = components(b, left)
    bad = []
    n_zone = sum(1 for _ in b.Zones())
    for net, cs in sorted(comp.items()):
        if len(cs) > 1:
            bad.append((net, cs))
    split = [(n, cs) for n, cs in bad if n not in allow]
    if not quiet:
        print("connectivity: %d nets with pads, %d zones loaded, %d nets split, %d of them not allowed" % (
            sum(1 for c in comp.values() if c), n_zone, len(bad), len(split)))
        for n, cs in bad:
            print("  %s%s: %d components: %s" % ("" if n not in allow else "(allowed) ", n, len(cs), " | ".join(describe(c) for c in cs)))
    return [n for n, _ in split]


def cmd_zone_clearance(path, quiet=False):
    b = pcbnew.LoadBoard(path)
    nodes = [n for ns in build(b).values() for n in ns]
    zones = [n for n in nodes if n["kind"] == "zone"]
    others = [n for n in nodes if n["kind"] != "zone"]
    bad = []
    cl = nm(CLEARANCE)
    for z in zones:
        for o in others:
            if o["net"] == z["net"]:
                continue
            L = z["layers"][0]
            if L not in o["layers"]:
                continue
            bb = o["bb"]
            zb = z["bb"]
            if not zb.Intersects(bb) and not zb.Inflate(cl).Intersects(bb):
                continue
            if z["poly"].Collide(o["shapes"][L], cl):
                bad.append((z["net"], b.GetLayerName(L), o["kind"], o["net"], mm(o["obj"].GetPosition().x), mm(o["obj"].GetPosition().y)))
    if not quiet:
        print("zone-clearance: %d fill islands, %d foreign items closer than %.2f mm" % (len(zones), len(bad), CLEARANCE))
        for x in bad[:10]:
            print("  zone %s %s too close to %s of net %s at (%.2f, %.2f)" % x)
    return bad


def cmd_selftest(path, left_path):
    ok = True
    left = set(read_pairs(left_path, 3))
    base = cmd_connectivity(path, left_path, quiet=True)
    print("selftest: undamaged board has %d disallowed split nets, %d zone-clearance hits" % (len(base), len(cmd_zone_clearance(path, quiet=True))))
    with tempfile.TemporaryDirectory() as td:
        # 1. delete every FROW_GND zone: the net must split (its pads lose the pour)
        b = pcbnew.LoadBoard(path)
        gone = [z for z in b.Zones() if z.GetNetname() == "FROW_GND"]
        for z in gone:
            b.Remove(z)
        dmg = os.path.join(td, "nozone.kicad_pcb")
        pcbnew.SaveBoard(dmg, b)
        n0 = len(components(pcbnew.LoadBoard(path), left)["FROW_GND"])
        n1 = len(components(pcbnew.LoadBoard(dmg), left)["FROW_GND"])
        good = bool(gone) and n1 > n0
        print("negative control connectivity (deleted %d FROW_GND zones): %s" % (len(gone), "PASS (FROW_GND components %d -> %d)" % (n0, n1) if good else "FAIL (components %d -> %d)" % (n0, n1)))
        ok &= good
        # 2. move a foreign-net capacitor (C1, FROW_VCC/FROW_GND, on B.Cu) into a MAIN_GND B.Cu fill island: zone-clearance
        #    must report it. (A via written into a fill would be re-netted by KiCad on load, so it would prove nothing.)
        b = pcbnew.LoadBoard(path)
        z = [z for z in b.Zones() if z.GetNetname() == "MAIN_GND" and z.IsOnLayer(pcbnew.B_Cu)][0]
        q = max(islands(z, pcbnew.B_Cu), key=lambda s: s.Area())
        bb = q.BBox()
        pt = None
        for k in range(1, 40):
            for m in range(1, 40):
                p = pcbnew.VECTOR2I(bb.GetX() + bb.GetWidth() * k // 40, bb.GetY() + bb.GetHeight() * m // 40)
                if all(q.Contains(pcbnew.VECTOR2I(p.x + dx, p.y + dy)) for dx in (-nm(2.0), nm(2.0)) for dy in (-nm(2.0), nm(2.0))):
                    pt = p
                    break
            if pt:
                break
        if pt is None:
            print("negative control zone-clearance: FAIL (no point found inside a MAIN_GND fill)")
            return 1
        cap = [f for f in b.GetFootprints() if f.GetReference() == "C1"][0]
        cap.SetPosition(pt)
        dmg = os.path.join(td, "cap.kicad_pcb")
        pcbnew.SaveBoard(dmg, b)
        hits = cmd_zone_clearance(dmg, quiet=True)
        good = len(hits) > 0 and not cmd_zone_clearance(path, quiet=True)
        print("negative control zone-clearance (FROW capacitor moved into a MAIN_GND fill): %s" % ("PASS (%d hits)" % len(hits) if good else "FAIL"))
        ok &= good
    return 0 if ok else 1


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "connectivity":
        return 1 if cmd_connectivity(a[1], a[2], a[3] if len(a) > 3 else None) else 0
    if len(a) == 2 and a[0] == "zone-clearance":
        return 1 if cmd_zone_clearance(a[1]) else 0
    if len(a) == 3 and a[0] == "selftest":
        return cmd_selftest(a[1], a[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
