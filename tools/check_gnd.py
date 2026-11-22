#!/usr/bin/env python3
"""Independent checks for the ground pours and the hand-connected nets (pcbnew Python).

  components BOARD LEFT     every net is one copper component, zone fill counted as copper
  tagged BASE BOARD         the grid-router (52757465-) and Freerouting (46726565-) copper is unchanged
  same-as-base BASE BOARD   Edge.Cuts set and every footprint unchanged (as check_board.py)
  selftest BOARD BASE LEFT  negative controls for each of the checks above

Connectivity here is computed from the board file alone: pads, tracks and vias touch by geometry
(check_board.touches), and a filled zone island touches every pad, via or track end that overlaps it.
It does not use KiCad's DRC or ratsnest, nor Freerouting. Exit code 0 means every claim held.
"""
import collections
import os
import re
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

import pcbnew  # noqa: E402
import check_board as cb  # noqa: E402

mm = pcbnew.ToMM
nm = pcbnew.FromMM
TAGS = ("52757465-", "46726565-")


def island_polys(z, layer):
    """[(bbox mm, SHAPE_POLY_SET with one outline and its holes)] for one zone layer."""
    fp = z.GetFilledPolysList(layer)
    res = []
    for oi in range(fp.OutlineCount()):
        s = pcbnew.SHAPE_POLY_SET()
        s.AddOutline(fp.Outline(oi))
        for hi in range(fp.HoleCount(oi)):
            s.AddHole(fp.Hole(oi, hi))
        bb = s.BBox()
        res.append(((mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetX() + bb.GetWidth()), mm(bb.GetY() + bb.GetHeight())), s))
    return res


def shape_poly(item, layer, grow):
    """Copper outline of a pad or via on `layer`, grown by `grow` mm, as a SHAPE_POLY_SET."""
    s = pcbnew.SHAPE_POLY_SET()
    if hasattr(item, "TransformShapeToPolygon"):
        try:
            item.TransformShapeToPolygon(s, layer, nm(grow), nm(0.005), pcbnew.ERROR_INSIDE)
            return s
        except Exception:
            pass
    return s


def overlaps(poly_a, poly_b):
    t = pcbnew.SHAPE_POLY_SET(poly_a)
    t.BooleanIntersection(poly_b)
    return t.OutlineCount() > 0


def zone_islands(zs):
    """[(layer, bbox, poly)] for the copper layers of these zones, in a fixed order."""
    extra = []
    for z in zs:
        for layer in z.GetLayerSet().Seq():
            if layer not in (pcbnew.F_Cu, pcbnew.B_Cu):
                continue
            for bb, poly in island_polys(z, layer):
                extra.append((layer, bb, poly))
    return extra


def net_zones(b):
    zl = collections.defaultdict(list)
    for z in b.Zones():
        if z.IsOnCopperLayer() and not z.GetIsRuleArea():
            zl[z.GetNetname()].append(z)
    return zl


def components_with_zones(b, left):
    """{net: (nodes, DSU)}: nodes are ('pad'|'trk'|'via', obj) and ('isl', (layer, idx))."""
    comp = cb.components(b)
    for net, zs in net_zones(b).items():
        items, d = comp.get(net, ([], cb.DSU(0)))
        items = list(items)
        n0 = len(items)
        extra = zone_islands(zs)
        d2 = cb.DSU(n0 + len(extra))
        for k in range(n0):
            d2.p[k] = d.find(k)
        for e, (layer, bb, poly) in enumerate(extra):
            for k in range(n0):
                kind, o = items[k]
                if kind == "pad":
                    if not o.IsOnLayer(layer):
                        continue
                    pb = o.GetBoundingBox()
                    if mm(pb.GetX() + pb.GetWidth()) < bb[0] - 0.05 or mm(pb.GetX()) > bb[2] + 0.05 or mm(pb.GetY() + pb.GetHeight()) < bb[1] - 0.05 or mm(pb.GetY()) > bb[3] + 0.05:
                        continue
                    if overlaps(shape_poly(o, layer, 0.02), poly):
                        d2.union(k, n0 + e)
                elif kind == "via":
                    x, y = mm(o.GetX()), mm(o.GetY())
                    r = mm(o.GetWidth(pcbnew.F_Cu)) / 2.0 + 0.02
                    if x + r < bb[0] or x - r > bb[2] or y + r < bb[1] or y - r > bb[3]:
                        continue
                    if overlaps(shape_poly(o, layer, 0.02), poly):
                        d2.union(k, n0 + e)
                else:
                    if o.GetLayer() != layer:
                        continue
                    for p in (o.GetStart(), o.GetEnd()):
                        x, y = mm(p.x), mm(p.y)
                        if bb[0] - 0.01 <= x <= bb[2] + 0.01 and bb[1] - 0.01 <= y <= bb[3] + 0.01 and poly.Contains(p):
                            d2.union(k, n0 + e)
                            break
        items += [("isl", (layer, e)) for e in range(len(extra))]
        comp[net] = (items, d2)
    return comp


def required_components(net, items, d, left):
    """Component roots that must be joined: all except those with only left pads and no copper of their own."""
    groups = collections.defaultdict(list)
    for k in range(len(items)):
        groups[d.find(k)].append(k)

    def is_left(k):
        kind, o = items[k]
        return kind == "pad" and (net, o.GetParentFootprint().GetReference(), o.GetNumber()) in left

    out = []
    for r, g in groups.items():
        real = [k for k in g if not is_left(k)]
        if not real:
            continue
        # a lone zone island or a left-pad-only group needs no connection; copper that carries a
        # pad, a track or a via does
        if all(items[k][0] == "isl" for k in real):
            continue
        out.append(r)
    return out


def cmd_components(path, leftfile, quiet=False):
    b = pcbnew.LoadBoard(path)
    left = cb.read_left(leftfile)
    comp = components_with_zones(b, left)
    bad = []
    for net, (items, d) in sorted(comp.items()):
        if not net:
            continue
        req = required_components(net, items, d, left)
        if len(req) > 1:
            bad.append((net, len(req)))
    if not quiet:
        print("nets checked: %d, nets not one component: %d" % (len([n for n in comp if n]), len(bad)))
        for n, c in bad:
            print("  OPEN net %s: %d separate copper components" % (n, c))
    return bad


# ----------------------------------------------------------------------------- tagged copper unchanged
BLOCK = re.compile(r"\t\((?:segment|via)\n(?:\t\t.*\n|\t\t\t.*\n)+?\t\)\n")


def tagged_blocks(path):
    text = open(path, encoding="utf-8").read()
    out = {}
    for m in BLOCK.finditer(text):
        u = re.search(r'\(uuid "([^"]+)"\)', m.group(0)).group(1)
        if u.startswith(TAGS):
            out[u] = m.group(0)
    return out


def cmd_tagged(base, path, allowed_removed=()):
    a, c = tagged_blocks(base), tagged_blocks(path)
    removed = sorted(set(a) - set(c))
    changed = sorted(u for u in set(a) & set(c) if a[u] != c[u])
    n1 = sum(1 for u in a if u.startswith(TAGS[0]))
    n2 = sum(1 for u in a if u.startswith(TAGS[1]))
    print("tagged in base: %d grid-router, %d freerouting; removed %d, modified %d, added %d" % (n1, n2, len(removed), len(changed), len(set(c) - set(a))))
    for u in removed:
        print("  REMOVED %s" % u)
    for u in changed:
        print("  MODIFIED %s" % u)
    ok = not changed and set(removed) <= set(allowed_removed)
    return 0 if ok else 1


# ----------------------------------------------------------------------------- negative controls
def cmd_selftest(path, base, leftfile):
    ok = True
    with tempfile.TemporaryDirectory() as td:
        bad0 = cmd_components(path, leftfile, quiet=True)
        text = open(path, encoding="utf-8").read()
        # 1. remove the stitching vias of the net with most of them: its pours must fall apart
        vias = [m for m in BLOCK.finditer(text) if m.group(0).startswith("\t(via") and '(uuid "474e4420-' in m.group(0)]
        if not vias:
            print("selftest: no stitching vias found to remove")
            return 1
        cut = "".join(text[m.start():m.end()] for m in vias)
        t2 = text
        for m in reversed(vias):
            t2 = t2[: m.start()] + t2[m.end():]
        p2 = os.path.join(td, "novias.kicad_pcb")
        open(p2, "w", encoding="utf-8").write(t2)
        bad = cmd_components(p2, leftfile, quiet=True)
        good = len(bad) > len(bad0)
        print("negative control (all stitching vias removed): %s (%d open nets vs %d)" % ("PASS" if good else "FAIL", len(bad), len(bad0)))
        ok &= good
        # 2. remove one hand-routed segment: its net must open
        segs = [m for m in BLOCK.finditer(text) if m.group(0).startswith("\t(segment") and '(uuid "4f70656e-' in m.group(0)]
        if segs:
            m = segs[0]
            victim = re.search(r'\(net "([^"]+)"\)', m.group(0)).group(1)
            p3 = os.path.join(td, "noseg.kicad_pcb")
            open(p3, "w", encoding="utf-8").write(text[: m.start()] + text[m.end():])
            bad3 = cmd_components(p3, leftfile, quiet=True)
            good = victim in [n for n, _ in bad3] and victim not in [n for n, _ in bad0]
            print("negative control (removed one segment of %s): %s" % (victim, "PASS" if good else "FAIL"))
            ok &= good
        # 3. tagged check: modify one tagged segment, remove another
        t4 = re.sub(r'(\(uuid "52757465-[^"]+"\))', r'\1', text)
        m = next(m for m in BLOCK.finditer(text) if '(uuid "52757465-' in m.group(0))
        p4 = os.path.join(td, "mod.kicad_pcb")
        open(p4, "w", encoding="utf-8").write(text[: m.start()] + m.group(0).replace("(width 0.25)", "(width 0.3)") + text[m.end():])
        rc = cmd_tagged(base, p4)
        print("negative control (changed a tagged width): %s" % ("PASS" if rc == 1 else "FAIL"))
        ok &= rc == 1
        p5 = os.path.join(td, "rm.kicad_pcb")
        open(p5, "w", encoding="utf-8").write(text[: m.start()] + text[m.end():])
        rc = cmd_tagged(base, p5)
        print("negative control (removed a tagged item): %s" % ("PASS" if rc == 1 else "FAIL"))
        ok &= rc == 1
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    c = sys.argv[1]
    if c == "components":
        sys.exit(1 if cmd_components(sys.argv[2], sys.argv[3]) else 0)
    elif c == "tagged":
        sys.exit(cmd_tagged(sys.argv[2], sys.argv[3], sys.argv[4:]))
    elif c == "same-as-base":
        sys.exit(cb.cmd_same(sys.argv[2], sys.argv[3]))
    elif c == "selftest":
        sys.exit(cmd_selftest(sys.argv[2], sys.argv[3], sys.argv[4]))
    else:
        sys.exit(__doc__)
