#!/usr/bin/env python3
"""Propose extra stitching vias where filled ground pours are still split (pcbnew Python).

  gnd_islands.py FILLED_BOARD OUT_FILE [LEFT]

Reads a board whose zones are filled, builds the copper components of each pour net as
check_gnd.py does, and for each pair of components whose F.Cu and B.Cu fill overlap writes one via
position ("net x y") where both fills are open (0.5 mm pour clearance to foreign copper). Feed the
file to gnd_pour.py --extra-vias, refill, and repeat until it proposes nothing. It also prints the
pads and islands it cannot join this way, which need a track or stay open.
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

import pcbnew  # noqa: E402
import check_board as cb  # noqa: E402
import check_gnd as cg  # noqa: E402
import gnd_pour as gp  # noqa: E402

mm, nm = pcbnew.ToMM, pcbnew.FromMM


def main(path, out, leftfile):
    b = pcbnew.LoadBoard(path)
    left = cb.read_left(leftfile) if leftfile else set()
    comp = cg.components_with_zones(b, left)
    zl = cg.net_zones(b)
    via_d = 0.8
    need = gp.POUR_CLEAR + via_d / 2.0 + 0.15
    lines, stuck = [], []
    for net in sorted(zl):
        if net not in gp.PIECES:
            continue
        items, d = comp[net]
        isl = cg.zone_islands(zl[net])
        n0 = len(items) - len(isl)
        obs = gp.Obstacles(b, net)
        vias = [(mm(o.GetX()), mm(o.GetY())) for k, o in items if k == "via"]
        # inner region: a via must sit inside both fills with margin
        placed = 0
        changed = True
        while changed:
            changed = False
            for i, (li, bi, pi) in enumerate(isl):
                if li != pcbnew.F_Cu:
                    continue
                for j, (lj, bj, pj) in enumerate(isl):
                    if lj != pcbnew.B_Cu or d.find(n0 + i) == d.find(n0 + j):
                        continue
                    if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                        continue
                    ov = pcbnew.SHAPE_POLY_SET(pi)
                    ov.BooleanIntersection(pj)
                    if ov.OutlineCount() == 0:
                        continue
                    ov.Inflate(-nm(via_d / 2.0 + 0.1), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.01))
                    if ov.OutlineCount() == 0:
                        continue
                    bb = ov.BBox()
                    x0, y0 = mm(bb.GetX()), mm(bb.GetY())
                    x1, y1 = x0 + mm(bb.GetWidth()), y0 + mm(bb.GetHeight())
                    best = None
                    ny, nx = int((y1 - y0) / 0.25) + 1, int((x1 - x0) / 0.25) + 1
                    for jy in range(ny + 1):
                        for ix in range(nx + 1):
                            x, y = round((x0 + ix * 0.25) * 20) / 20.0, round((y0 + jy * 0.25) * 20) / 20.0
                            if not gp.contains(ov, x, y) or not obs.clear(x, y, need):
                                continue
                            if any((x - vx) ** 2 + (y - vy) ** 2 < 1.6 ** 2 for vx, vy in vias):
                                continue
                            best = (x, y)
                            break
                        if best:
                            break
                    if best:
                        lines.append("%s %.2f %.2f" % (net, best[0], best[1]))
                        vias.append(best)
                        d.union(n0 + i, n0 + j)
                        placed += 1
                        changed = True
        roots = {}
        for k in range(len(items)):
            roots.setdefault(d.find(k), []).append(k)
        print("%s: %d islands, %d proposed vias, %d components left" % (net, len(isl), placed, len(roots)))
        for r, g in sorted(roots.items(), key=lambda kv: -len(kv[1]))[1:]:
            what = [("%s.%s" % (items[k][1].GetParentFootprint().GetReference(), items[k][1].GetNumber())) if items[k][0] == "pad" else items[k][0] for k in g]
            stuck.append((net, what[:6]))
            print("  not joined: %s" % what[:6])
    open(out, "w").write("".join(l + "\n" for l in lines))
    print("wrote %d via lines to %s" % (len(lines), out))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
