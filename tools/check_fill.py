#!/usr/bin/env python3
"""Independent checks for the Freerouting fill step (pcbnew Python; uses nothing from Freerouting).

  components BOARD            list nets that are not one copper component; exit 1 if any
  script-copper BASE BOARD    every item tagged 52757465- (grid router) is identical in both boards
  metrics BOARD [PREFIX]      per net: segments, vias, length, 45 and 90 degree corners of items tagged PREFIX (default 46726565-)
  selftest BOARD BASE         negative controls: each check above must fail on a damaged copy

Connectivity model: pads (not NPTH), segments and vias of one net touch when their copper overlaps on a shared
layer (segment ends and mid-points count; a via joins both layers). Copper of different nets never joins.
"""
import collections
import math
import os
import re
import sys
import tempfile

import pcbnew

SCRIPT_PREFIX = "52757465-"
FILL_PREFIX = "46726565-"
SEGMENT = re.compile(r"\t\(segment\n(?:\t\t.*\n)+?\t\)\n")


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def seg_seg_dist(s, t):
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if o(s[0], s[1], t[0]) * o(s[0], s[1], t[1]) < 0 and o(t[0], t[1], s[0]) * o(t[0], t[1], s[1]) < 0:
        return 0
    return min(seg_dist(s[0], t[0], t[1]), seg_dist(s[1], t[0], t[1]), seg_dist(t[0], s[0], s[1]), seg_dist(t[1], s[0], s[1]))


class Item:
    def __init__(self, kind, obj, layers, ends=None, w=0):
        self.kind, self.obj, self.layers, self.ends, self.w = kind, obj, layers, ends, w


def touches(a, b):
    if not (a.layers & b.layers) or (a.kind == "pad" and b.kind == "pad"):
        return False
    if b.kind == "pad":
        a, b = b, a
    if a.kind == "pad":
        pad = a.obj
        if any(pad.HitTest(pcbnew.VECTOR2I(int(x), int(y))) for x, y in b.ends):
            return True
        c = pad.GetPosition()
        return seg_dist((c.x, c.y), b.ends[0], b.ends[1]) <= b.w / 2
    return seg_seg_dist(a.ends, b.ends) <= min(a.w, b.w) / 2


def items_by_net(b):
    by = collections.defaultdict(list)
    both = {pcbnew.F_Cu, pcbnew.B_Cu}
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                by[p.GetNetname()].append(Item("pad", p, {l for l in both if p.IsOnLayer(l)}))
    for t in b.GetTracks():
        if not t.GetNetname():
            continue
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            by[t.GetNetname()].append(Item("via", t, both, ((p.x, p.y), (p.x, p.y)), t.GetWidth()))
        else:
            s, e = t.GetStart(), t.GetEnd()
            by[t.GetNetname()].append(Item("trk", t, {t.GetLayer()}, ((s.x, s.y), (e.x, e.y)), t.GetWidth()))
    return by


def net_components(items):
    p = list(range(len(items)))

    def find(a):
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if touches(items[i], items[j]):
                p[find(i)] = find(j)
    return [find(i) for i in range(len(items))]


def broken_nets(b):
    """{net: number of separate copper components}, only nets with more than one (pad-less copper counts too)."""
    out = {}
    for net, items in items_by_net(b).items():
        n = len(set(net_components(items)))
        if n > 1:
            out[net] = n
    return out


def signature(t):
    if t.GetClass() == "PCB_VIA":
        p = t.GetPosition()
        return ("via", p.x, p.y, t.GetWidth(), t.GetDrill(), t.GetNetname(), t.m_Uuid.AsString())
    s, e = t.GetStart(), t.GetEnd()
    return ("trk", s.x, s.y, e.x, e.y, t.GetWidth(), t.GetLayerName(), t.GetNetname(), t.m_Uuid.AsString())


def tagged(b, prefix):
    return {signature(t) for t in b.GetTracks() if t.m_Uuid.AsString().startswith(prefix)}


def cmd_components(path):
    bad = broken_nets(pcbnew.LoadBoard(path))
    for n, k in sorted(bad.items()):
        print("%s: %d components" % (n, k))
    print("nets not in one component: %d" % len(bad))
    return bad


def cmd_script_copper(base, board):
    a, c = tagged(pcbnew.LoadBoard(base), SCRIPT_PREFIX), tagged(pcbnew.LoadBoard(board), SCRIPT_PREFIX)
    print("script copper items: base %d, board %d, missing %d, changed or extra %d" % (len(a), len(c), len(a - c), len(c - a)))
    return a == c and len(a) > 0


def first_script_segment(text):
    for m in SEGMENT.finditer(text):
        if SCRIPT_PREFIX in m.group(0):
            return m.group(0)
    raise SystemExit("check_fill selftest: no script segment found; the board has no %s copper." % SCRIPT_PREFIX)


def cmd_selftest(board, base):
    ok = True
    if not cmd_script_copper(base, board):
        print("selftest: the clean board failed script-copper")
        ok = False
    text = open(board).read()
    blk = first_script_segment(text)
    damaged = {
        "drop-segment": text.replace(blk, "", 1),
        "nudge-segment": text.replace(blk, re.sub(r"\(end ([-\d.]+) ", lambda k: "(end %.2f " % (float(k.group(1)) + 0.01), blk, 1), 1),
    }
    with tempfile.TemporaryDirectory() as d:
        for how, t in damaged.items():
            p = os.path.join(d, how + ".kicad_pcb")
            open(p, "w").write(t)
            if cmd_script_copper(base, p):
                print("selftest: script-copper MISSED '%s'" % how)
                ok = False
            else:
                print("selftest: script-copper correctly failed on '%s'" % how)
    b = pcbnew.LoadBoard(board)
    before = broken_nets(b)
    victim = next((t for t in b.GetTracks() if t.GetClass() != "PCB_VIA" and t.GetNetname() not in before and t.GetNetname().endswith("_ROW0")), None)
    if victim is None:
        victim = next(t for t in b.GetTracks() if t.GetClass() != "PCB_VIA" and t.GetNetname() not in before)
    net = victim.GetNetname()
    b.Remove(victim)
    if net in broken_nets(b):
        print("selftest: connectivity correctly broke net %s after removing one segment" % net)
    else:
        print("selftest: connectivity MISSED a removed segment on net %s" % net)
        ok = False
    return ok


def cmd_metrics(path, prefix):
    b = pcbnew.LoadBoard(path)
    per = collections.defaultdict(lambda: {"seg": 0, "via": 0, "len": 0.0, "c45": 0, "c90": 0, "other": 0, "ends": collections.defaultdict(list)})
    for t in b.GetTracks():
        if not t.m_Uuid.AsString().startswith(prefix):
            continue
        r = per[t.GetNetname()]
        if t.GetClass() == "PCB_VIA":
            r["via"] += 1
            continue
        s, e = t.GetStart(), t.GetEnd()
        r["seg"] += 1
        r["len"] += math.hypot(s.x - e.x, s.y - e.y) / 1e6
        r["ends"][(s.x, s.y, t.GetLayer())].append((e.x - s.x, e.y - s.y))
        r["ends"][(e.x, e.y, t.GetLayer())].append((s.x - e.x, s.y - e.y))
    tot = collections.Counter()
    for net, r in sorted(per.items()):
        for v in r["ends"].values():
            if len(v) == 2:
                a = abs(math.degrees(math.atan2(v[0][1], v[0][0]) - math.atan2(v[1][1], v[1][0]))) % 360
                a = min(a, 360 - a)
                if abs(a - 180) < 1:
                    continue
                if abs(a - 135) < 1:
                    r["c45"] += 1
                elif abs(a - 90) < 1:
                    r["c90"] += 1
                else:
                    r["other"] += 1
        print("%-16s seg %3d via %2d len %7.1f mm  corners45 %2d corners90 %2d other %2d" % (net, r["seg"], r["via"], r["len"], r["c45"], r["c90"], r["other"]))
        for k in ("seg", "via", "len", "c45", "c90", "other"):
            tot[k] += r[k]
    print("TOTAL nets %d seg %d via %d len %.1f mm corners45 %d corners90 %d other %d" % (len(per), tot["seg"], tot["via"], tot["len"], tot["c45"], tot["c90"], tot["other"]))


def main():
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 2 else ("", [])
    if cmd == "components":
        return 1 if cmd_components(args[0]) else 0
    if cmd == "metrics":
        cmd_metrics(args[0], args[1] if len(args) > 1 else FILL_PREFIX)
        return 0
    if cmd == "script-copper" and len(args) == 2:
        return 0 if cmd_script_copper(*args) else 1
    if cmd == "selftest" and len(args) == 2:
        return 0 if cmd_selftest(*args) else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
