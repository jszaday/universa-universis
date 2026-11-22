"""Geometric short detector: different-net copper items (pads, tracks, vias) whose shapes overlap on a shared layer.

  shortdet.py BOARD            exit 1 if any overlap is found, 0 if none
  shortdet.py --selftest BOARD negative control: move one footprint so a pad lands on a foreign-net pad; the detector must exit 1

Division of labour: KiCad re-nets a track or via written in the file when it touches other-net copper, so such a short
shows no overlap here; tools/netcheck.py catches that case by comparing the written nets with the loaded ones. Zone
fills are not tested here; tools/check_pipeline.py zone-clearance covers them.
"""
import sys, tempfile, os
import pcbnew
from pcbnew import *


def detect(b):
    items = []  # (item, netcode, layers)
    for t in b.GetTracks():
        items.append(t)
    for fp in b.GetFootprints():
        for p in fp.Pads():
            items.append(p)
    cu = [l for l in b.GetEnabledLayers().CuStack()]
    found = set()
    for l in cu:
        L = [i for i in items if i.IsOnLayer(l) and i.GetNetCode() > 0]
        bbs = [(i, i.GetBoundingBox()) for i in L]
        for a in range(len(bbs)):
            ia, ba = bbs[a]
            sa = ia.GetEffectiveShape(l)
            for c in range(a + 1, len(bbs)):
                ic, bc = bbs[c]
                if ia.GetNetCode() == ic.GetNetCode():
                    continue
                if not ba.Intersects(bc):
                    continue
                if ia.GetClass() == 'PAD' and ic.GetClass() == 'PAD' and ia.GetParent() == ic.GetParent():
                    continue
                if sa.Collide(ic.GetEffectiveShape(l), 0):
                    found.add((b.GetLayerName(l), ia.GetClass(), ia.GetNetname(), ic.GetClass(), ic.GetNetname(), ia.m_Uuid.AsString()[:8], ic.m_Uuid.AsString()[:8]))
    return sorted(found)


def report(found, zones):
    print("SHORTS", len(found), "zones", zones)
    for f in found[:8]:
        print(" ", f[:5])


def selftest(path):
    b = LoadBoard(path)
    clean = detect(b)
    # move a two-pad footprint (a capacitor) so its first pad lands on a foreign-net pad elsewhere
    cap = [f for f in b.GetFootprints() if f.GetReference() == "C1"][0]
    p0 = [p for p in cap.Pads()][0]
    target = [p for f in b.GetFootprints() if f.GetReference() == "C3" for p in f.Pads() if p.GetNetname() and p.GetNetname() != p0.GetNetname()][0]
    cap.SetPosition(VECTOR2I(cap.GetX() + target.GetX() - p0.GetX(), cap.GetY() + target.GetY() - p0.GetY()))
    hit = detect(b)
    print("selftest: undamaged board %d overlaps; after moving C1 onto C3 pad %s: %d overlaps" % (len(clean), target.GetNetname(), len(hit)))
    return 0 if (not clean and hit) else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    b = LoadBoard(sys.argv[1])
    f = detect(b)
    report(f, len(list(b.Zones())))
    sys.exit(1 if f else 0)
