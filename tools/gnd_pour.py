#!/usr/bin/env python3
"""Ground pours: one zone pair (F.Cu + B.Cu) per breakaway piece GND net, plus stitching vias.

Run with KiCad's Python (pcbnew builds the geometry; the board file is edited as text):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
      tools/gnd_pour.py [--board PATH] [--out PATH] [--pitch MM] [--extra-vias FILE]

Zones carry uuids starting with GND_UUID_PREFIX, stitching vias too, so a re-run removes exactly
its own zones and vias first. The zones are written unfilled; fill them with
  kicad-cli pcb drc --refill-zones --save-board --schematic-parity -o drc.json BOARD
which also saves the filled polygons into the board file. Rules (tools/GND.md): each pour stays
POUR_EDGE mm inside its piece outline and POUR_SLOT mm from mouse-bite slots (and the popout
ring), 0.5 mm clear of other nets; stitching vias sit on a regular pitch where both layers are open.
"""
import argparse
import hashlib
import math
import os
import re
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

import pcbnew  # noqa: E402
import route_regular as rr  # noqa: E402

GND_UUID_PREFIX = "474e4420-"  # ASCII "GND "
POUR_EDGE = 1.0  # mm, pour edge to board outline
POUR_SLOT = 2.0  # mm, pour edge to mouse-bite slot or popout ring
POUR_CLEAR = 0.5  # mm, pour to other nets
mm = pcbnew.ToMM
nm = pcbnew.FromMM

# breakaway pieces: GND net -> box (mm) that cuts the outline polygon at the seam gaps
PIECES = {
    "FROW_GND": (130.0, 28.0, 415.93, 47.4),
    "MAIN_GND": (130.0, 52.4, 415.93, 147.7),
    "NAV_GND": (420.93, 52.38, 478.1, 147.7),
    "NUMPAD_GND": (483.1, 52.39, 559.4, 147.7),
}
BLOCK_ZONE = re.compile(r"\t\(zone\n(?:\t\t.*\n|\t\t\t.*\n|\t\t\t\t.*\n|\t\t\t\t\t.*\n|\t\t\t\t\t\t.*\n)+?\t\)\n")
BLOCK_VIA = rr.BLOCK


def poly_box(x0, y0, x1, y1):
    s = pcbnew.SHAPE_POLY_SET()
    s.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        s.Append(nm(x), nm(y))
    return s


def poly_disc(cx, cy, r, n=48):
    s = pcbnew.SHAPE_POLY_SET()
    s.NewOutline()
    for k in range(n):
        a = 2 * math.pi * k / n
        s.Append(nm(cx + r * math.cos(a)), nm(cy + r * math.sin(a)))
    return s


def keepouts(b):
    """Polygons (mm discs and boxes) a pour must stay POUR_SLOT away from: mouse-bite slots, popout ring."""
    out = []
    for f in b.GetFootprints():
        n = str(f.GetFPID().GetLibItemName())
        if "mouse-bite" in n:
            xs = [mm(p.GetX()) for p in f.Pads()]
            ys = [mm(p.GetY()) for p in f.Pads()]
            r = POUR_SLOT + 0.25
            out.append(poly_box(min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r))
        elif "popout-ring" in n:
            cx, cy = mm(f.GetX()), mm(f.GetY())
            rad = max(math.hypot(mm(p.GetX()) - cx, mm(p.GetY()) - cy) for p in f.Pads())
            out.append(poly_disc(cx, cy, rad + POUR_SLOT))
    return out


def piece_regions(b):
    """{net: SHAPE_POLY_SET} the pour outline of each piece."""
    outline = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(outline, True)
    kos = keepouts(b)
    res = {}
    for net, (x0, y0, x1, y1) in PIECES.items():
        s = pcbnew.SHAPE_POLY_SET(outline)
        s.BooleanIntersection(poly_box(x0, y0, x1, y1))
        s.Inflate(-nm(POUR_EDGE), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.01))
        for k in kos:
            s.BooleanSubtract(k)
        s.Simplify()
        res[net] = s
    return res


# ----------------------------------------------------------------------------- stitching vias
class Obstacles:
    """Foreign copper and holes as (kind, geometry) in 5 mm buckets; distance from a point to the nearest edge."""

    B = 5.0

    def __init__(self, b, net):
        self.cells = {}
        for f in b.GetFootprints():
            for p in f.Pads():
                if p.GetNetname() == net:
                    if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:  # own plated hole: via drill must keep its distance
                        self.add(("disc", mm(p.GetX()), mm(p.GetY()), max(mm(p.GetDrillSizeX()), mm(p.GetDrillSizeY())) / 2.0, 0.0))
                    continue
                bb = p.GetBoundingBox()
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    d = max(mm(p.GetDrillSizeX()), mm(p.GetDrillSizeY())) / 2.0
                    self.add(("disc", mm(p.GetX()), mm(p.GetY()), d, 0.0))  # holes: pour clearance applies, drill only
                else:
                    self.add(("rect", mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetX() + bb.GetWidth()), mm(bb.GetY() + bb.GetHeight())))
        for t in b.GetTracks():
            if t.GetNetname() == net:
                continue
            if t.GetClass() == "PCB_VIA":
                self.add(("disc", mm(t.GetX()), mm(t.GetY()), mm(t.GetWidth(pcbnew.F_Cu)) / 2.0, 0.0))
            else:
                self.add(("seg", mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y), mm(t.GetWidth()) / 2.0))

    def box(self, o):
        if o[0] == "rect":
            return o[1], o[2], o[3], o[4]
        if o[0] == "disc":
            return o[1] - o[3], o[2] - o[3], o[1] + o[3], o[2] + o[3]
        return min(o[1], o[3]) - o[5], min(o[2], o[4]) - o[5], max(o[1], o[3]) + o[5], max(o[2], o[4]) + o[5]

    def add(self, o):
        x0, y0, x1, y1 = self.box(o)
        for i in range(int(x0 // self.B), int(x1 // self.B) + 1):
            for j in range(int(y0 // self.B), int(y1 // self.B) + 1):
                self.cells.setdefault((i, j), []).append(o)

    @staticmethod
    def dist(o, x, y):
        if o[0] == "rect":
            return math.hypot(max(o[1] - x, 0, x - o[3]), max(o[2] - y, 0, y - o[4]))
        if o[0] == "disc":
            return max(math.hypot(x - o[1], y - o[2]) - o[3], 0.0)
        ax, ay, bx, by, hw = o[1:]
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2))
        return max(math.hypot(x - ax - t * vx, y - ay - t * vy) - hw, 0.0)

    def clear(self, x, y, need):
        i, j = int(x // self.B), int(y // self.B)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for o in self.cells.get((i + di, j + dj), ()):
                    if self.dist(o, x, y) < need:
                        return False
        return True


def contains(poly, x, y):
    return poly.Contains(pcbnew.VECTOR2I(nm(x), nm(y)))


def stitch_points(b, regions, pitch, via_d):
    """{net: [(x, y)]} stitching via positions: lattice points moved to the nearest valid spot."""
    out = {}
    need = POUR_CLEAR + via_d / 2.0 + 0.15  # via centre to foreign copper on either layer
    for net, reg in regions.items():
        inner = pcbnew.SHAPE_POLY_SET(reg)
        inner.Inflate(-nm(via_d / 2.0 + 0.6), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.01))
        obs = Obstacles(b, net)
        bb = reg.BBox()
        x0, y0, x1, y1 = mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetX() + bb.GetWidth()), mm(bb.GetY() + bb.GetHeight())
        pts = []
        taken = []
        ny = int((y1 - y0) // pitch) + 1
        nx = int((x1 - x0) // pitch) + 1
        for jy in range(ny + 1):
            for ix in range(nx + 1):
                cx = x0 + pitch / 2.0 + ix * pitch
                cy = y0 + pitch / 2.0 + jy * pitch
                best = None
                for r in [0.0] + [0.25 * k for k in range(1, 13)]:
                    cand = [(cx, cy)] if r == 0 else [
                        (cx + r * math.cos(a * math.pi / 8), cy + r * math.sin(a * math.pi / 8)) for a in range(16)]
                    for (px, py) in cand:
                        px, py = round(px * 20) / 20.0, round(py * 20) / 20.0
                        if contains(inner, px, py) and obs.clear(px, py, need) and all(math.hypot(px - qx, py - qy) > via_d + 0.8 for qx, qy in taken):
                            best = (px, py)
                            break
                    if best:
                        break
                if best:
                    taken.append(best)
                    pts.append(best)
        out[net] = pts
    return out


# ----------------------------------------------------------------------------- text
def det_uuid(key):
    h = hashlib.sha1(key.encode()).hexdigest()
    return "%s%s-4%s-8%s-%s" % (GND_UUID_PREFIX, h[0:4], h[4:7], h[7:10], h[10:22])


def strip_own(text):
    n = 0

    def sub(m):
        nonlocal n
        if '(uuid "%s' % GND_UUID_PREFIX in m.group(0):
            n += 1
            return ""
        return m.group(0)

    text = BLOCK_VIA.sub(sub, text)
    text = BLOCK_ZONE.sub(sub, text)
    return text, n


PAD_BLOCK = re.compile(r'\t\t\(pad "([^"]*)" (smd|thru_hole) .*\n(?:\t\t\t.*\n)+?\t\t\)\n')
REF_PROP = re.compile(r'\(property "Reference" "([^"]+)"')


def solid_pads(text, solid_pth):
    """Give every SMD pad of a piece GND net, and the listed through-hole pads (REF:NUM), a solid zone connection."""
    refs = [(m.start(), m.group(1)) for m in REF_PROP.finditer(text)]
    import bisect
    starts = [s for s, _ in refs]
    n = 0

    def sub(m):
        nonlocal n
        blk = m.group(0)
        net = re.search(r'\(net "([^"]+)"\)', blk)
        if not net or net.group(1) not in PIECES or "(zone_connect" in blk:
            return blk
        k = bisect.bisect_right(starts, m.start()) - 1
        ref = refs[k][1]
        if m.group(2) == "smd" or "%s:%s" % (ref, m.group(1)) in solid_pth:
            n += 1
            return blk.replace("\t\t\t(uuid ", "\t\t\t(zone_connect 2)\n\t\t\t(uuid ", 1)
        return blk

    return PAD_BLOCK.sub(sub, text), n


def make_zone_text(b, net, region, layer, tmpdir):
    """Build the zone with the pcbnew API on a scratch board and return its text block."""
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(b.FindNet(net))
    z.SetZoneName(net)
    z.SetLocalClearance(nm(POUR_CLEAR))
    z.SetMinThickness(nm(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(nm(0.5))
    z.SetThermalReliefSpokeWidth(nm(0.5))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetAssignedPriority(0)
    zo = z.Outline()
    for oi in range(region.OutlineCount()):
        zo.AddOutline(region.Outline(oi))
        for hi in range(region.HoleCount(oi)):
            zo.AddHole(region.Hole(oi, hi), oi)
    b.Add(z)
    path = os.path.join(tmpdir, "z_%s_%d.kicad_pcb" % (net, layer))
    b.Save(path)
    b.Remove(z)
    txt = open(path, encoding="utf-8").read()
    m = [x for x in BLOCK_ZONE.finditer(txt) if '(name "%s")' % net in x.group(0)]
    if len(m) != 1:
        raise SystemExit("gnd_pour: could not extract the zone for %s from the scratch save (%d matches); the zone text layout changed." % (net, len(m)))
    blk = m[0].group(0)
    layname = "F.Cu" if layer == pcbnew.F_Cu else "B.Cu"
    return re.sub(r'\(uuid "[^"]+"\)', '(uuid "%s")' % det_uuid("zone|%s|%s" % (net, layname)), blk, count=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", default=os.path.join(here, "..", "fkb-109j-big", "fkb-109j-big.kicad_pcb"))
    ap.add_argument("--out")
    ap.add_argument("--pitch", type=float, default=8.0, help="stitching via lattice pitch, mm")
    ap.add_argument("--extra-vias", help="file of 'net x y' lines: more stitching vias (islands found after a fill)")
    ap.add_argument("--solid-pth", default="", help="comma list REF:NUM of through-hole GND pads to connect solid (default: thermal relief); use for pads KiCad reports as starved")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    board = os.path.abspath(a.board)
    dst = os.path.abspath(a.out) if a.out else board
    if not a.force and rr.kicad_running():
        raise SystemExit("gnd_pour: KiCad is running and a save from it would overwrite %s. Quit KiCad or pass --force for a scratch --out copy." % dst)
    text = open(board, encoding="utf-8").read()
    text, removed = strip_own(text)
    text, nsolid = solid_pads(text, set(x for x in a.solid_pth.split(",") if x))
    td = tempfile.mkdtemp()
    tmp = os.path.join(td, "in.kicad_pcb")
    open(tmp, "w", encoding="utf-8").write(text)
    rules = rr.read_rules(board.replace(".kicad_pcb", ".kicad_pro"))
    b = pcbnew.LoadBoard(tmp)
    regions = piece_regions(b)
    vias = stitch_points(b, regions, a.pitch, rules["via_d"])
    if a.extra_vias:
        for l in open(a.extra_vias):
            if l.strip():
                n, x, y = l.split()
                vias[n].append((float(x), float(y)))
    out = []
    for net, reg in regions.items():
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
            out.append(make_zone_text(b, net, reg, layer, td))
    fm = rr.fmt
    nv = 0
    for net, pts in vias.items():
        for (x, y) in sorted(set(pts)):
            nv += 1
            out.append("\t(via\n\t\t(at %s %s)\n\t\t(size %s)\n\t\t(drill %s)\n\t\t(layers \"F.Cu\" \"B.Cu\")\n\t\t(net %s)\n\t\t(uuid %s)\n\t)\n"
                       % (fm(x), fm(y), fm(rules["via_d"]), fm(rules["via_drill"]), rr.q(net), rr.q(det_uuid("via|%s|%s,%s" % (net, fm(x), fm(y))))))
    tail = "\t(embedded_fonts no)\n)"
    if text.count(tail) != 1:
        raise SystemExit("gnd_pour: %s does not end with the expected '(embedded_fonts no)' trailer; the file layout changed, update the trailer check." % board)
    open(dst, "w", encoding="utf-8").write(text.replace(tail, "".join(out) + tail))
    print("%d pads set to solid connection" % nsolid)
    print("removed %d old pour items; wrote %d zones and %s stitching vias (%s) to %s" % (
        removed, len(regions) * 2, nv, {n: len(p) for n, p in vias.items()}, dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
