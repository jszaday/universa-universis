#!/usr/bin/env python3
"""Fill the nets the grid router left, with Freerouting, without touching the grid router's copper.

  prep  BOARD DSN [--left FILE] [NET ...]  (never routes *_GND nets or nets in the left-pads FILE) export a Specctra DSN in which every net that is already one copper component is removed
                        from the network (its pads, tracks and vias stay as obstacles) and the rest are routed
                        with the board's net class (0.25 mm track, 0.8/0.4 via, 0.2 mm clearance)
                        (NET ... are routed too even though they are one component: nets with a rule violation)
  merge BOARD SES OUT [--keep]  add the wires and vias of the SES to a copy of BOARD as text, tagged 46726565- ("Free");
                        earlier 46726565- items are removed first unless --keep (second pass)
  bad-nets BOARD DRC    print the nets of 46726565- tracks named in clearance or track_width violations of a DRC json
  drop-nets BOARD OUT [--broken] NET ...  remove the 46726565- items of the named nets (and of every net that is not one component with --broken)
  strip BOARD OUT       remove every 46726565- item (the fill step's own copper) and nothing else

Run under KiCad's Python (pcbnew): see tools/FILL.md for the full sequence.
"""
import os
import re
import sys
import hashlib

FILL_PREFIX = "46726565-"
BLOCK = re.compile(r"\t\((?:segment|via)\n(?:\t\t.*\n|\t\t\t.*\n)+?\t\)\n")
TRAILER = "\t(embedded_fonts no)\n)"
VIA_NAME = "Via[0-1]_800:400_um"
TRACK_UM = 250
CLEARANCE_UM = 200


def uuid_for(key):
    h = hashlib.sha1(key.encode()).hexdigest()
    return "%s%s-4%s-8%s-%s" % (FILL_PREFIX, h[0:4], h[4:7], h[7:10], h[10:22])


def strip_fill_copper(text):
    n = 0

    def sub(m):
        nonlocal n
        if '(uuid "%s' % FILL_PREFIX in m.group(0):
            n += 1
            return ""
        return m.group(0)

    return BLOCK.sub(sub, text), n


def split_dsn_network(dsn):
    """Return (before, nets, class_tail, after): nets = [(name, block_text)], class_tail = text after the class list."""
    i = dsn.index("  (network\n")
    j = dsn.index("    (class ", i)
    k = dsn.index("\n  (wiring", j)
    head = dsn[: i + len("  (network\n")]
    body = dsn[i + len("  (network\n"): j]
    nets = re.findall(r'    \(net ("[^"]*"|\S+)\n      \(pins [^)]*\)\n    \)\n', body)
    blocks = re.findall(r'(    \(net (?:"[^"]*"|\S+)\n      \(pins [^)]*\)\n    \)\n)', body)
    if len(nets) != len(blocks) or "".join(blocks) != body:
        raise SystemExit("fill_freerouting: the DSN network section has an unexpected layout; the KiCad exporter changed. Update split_dsn_network.")
    return head, [(n.strip('"'), b) for n, b in zip(nets, blocks)], dsn[k:]


def rewrite_dsn(dsn, keep, pins_for=None):
    """Drop every net not in `keep` from the network and the class; constrain the rules; fix existing wires."""
    head, nets, tail = split_dsn_network(dsn)
    kept = [(n, b) for n, b in nets if n in keep]
    for i, (n, b) in enumerate(kept):
        if pins_for and n in pins_for:
            allowed = pins_for[n]
            m = re.search(r"\(pins ([^)]*)\)", b)
            kept[i] = (n, b.replace(m.group(0), "(pins %s)" % " ".join(x for x in m.group(1).split() if x in allowed)))
    names = " ".join('"%s"' % n if re.search(r"[^\w]", n) else n for n, _ in kept)
    cls = '    (class kicad_default %s\n      (circuit\n        (use_via "%s")\n      )\n      (rule\n        (width %d)\n        (clearance %d)\n      )\n    )\n  )' % (names, VIA_NAME, TRACK_UM, CLEARANCE_UM)
    out = head + "".join(b for _, b in kept) + cls + tail
    out = re.sub(r'\(via "Via\[0-1\]_600:300_um" "Via\[0-1\]_800:400_um"\)', '(via "%s")' % VIA_NAME, out, count=1)
    out = re.sub(r"(    \(rule\n      \(width )200(\)\n      \(clearance 200\))", r"\g<1>%d\2" % TRACK_UM, out, count=1)
    w = out.index("  (wiring")
    out = out[:w] + out[w:].replace("(type route)", "(type fix)")
    return out, [n for n, _ in kept]


def link_pins(b, nets):
    """For a net that already has grid-router copper but several components: only the pad pairs that bridge the
    components (each smaller component to its nearest pad of the largest one), so Freerouting adds the missing
    branch instead of re-routing the whole bus. Nets with no copper (power, I2C) keep every pin."""
    import math
    import check_fill
    by = check_fill.items_by_net(b)
    out = {}
    for net in nets:
        items = by.get(net, [])
        if not any(it.kind != "pad" for it in items):
            continue
        roots = check_fill.net_components(items)
        comps = {}
        for it, r in zip(items, roots):
            if it.kind == "pad":
                comps.setdefault(r, []).append(it.obj)
        comps = sorted(comps.values(), key=len, reverse=True)
        if len(comps) < 2:
            continue
        name = lambda pad: "%s-%s" % (pad.GetParentFootprint().GetReference(), pad.GetNumber())
        keep = set()
        for c in comps[1:]:
            best = min(((math.dist(tuple(x.GetPosition()), tuple(y.GetPosition())), x, y) for x in c for y in comps[0]), key=lambda t: t[0])
            keep |= {name(best[1]), name(best[2])}
        out[net] = keep
    return out


def excluded_nets(board, left_file):
    """Nets Freerouting must never route: the ground pours (`*_GND`, joined by tools/gnd_pour.py) and every net with a pad
    left on purpose (tools/left_pads.txt: far alternate footprints, the popout ring), whose open branch is deliberate."""
    ex = set()
    if left_file and os.path.exists(left_file):
        ex |= {l.split("\t")[0] for l in open(left_file) if l.strip()}
    return ex


def cmd_prep(board, dsn_out, extra=(), left_file=None):
    import pcbnew
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import check_fill
    b = pcbnew.LoadBoard(board)
    broken = check_fill.broken_nets(b)
    raw = dsn_out + ".raw"
    if not pcbnew.ExportSpecctraDSN(b, raw):
        raise SystemExit("fill_freerouting: pcbnew could not export the DSN from %s. Open the board in KiCad once to check it loads, then retry." % board)
    raw_text = open(raw).read()
    ex = excluded_nets(board, left_file)
    keep = {n for n in set(broken) | set(extra) if n not in ex and not n.endswith("_GND")}
    out, kept = rewrite_dsn(raw_text, keep, link_pins(b, keep))
    open(dsn_out, "w").write(out)
    os.remove(raw)
    print("prep: %d nets to route, %d completed nets removed from the network" % (len(kept), len(split_dsn_network(raw_text)[1]) - len(kept)))
    return 0


def parse_ses(text):
    """Yield ('wire', net, layer, width_um, [(x_mm, y_mm), ...]) and ('via', net, name, x_mm, y_mm) from a Specctra SES."""
    m = re.search(r"\(resolution (\w+) (\d+)\)", text)
    unit_um = {"um": 1.0, "mm": 1000.0, "mil": 25.4}[m.group(1)]
    scale = unit_um / int(m.group(2)) / 1000.0  # SES unit -> mm
    s = text.index("(network_out")
    out = []
    for nm in re.finditer(r'\(net ("[^"]*"|[^\s()]+)\s*((?:\(wire\s*\(path[^)]*\)\s*\)\s*|\(via[^)]*\)\s*)*)\)', text[s:]):
        net = nm.group(1).strip('"')
        for wm in re.finditer(r"\(wire\s*\(path\s+(\S+)\s+(\d+)\s+([^)]*)\)", nm.group(2)):
            v = [float(t) for t in wm.group(3).split()]
            pts = [(v[i] * scale, -v[i + 1] * scale) for i in range(0, len(v), 2)]
            out.append(("wire", net, wm.group(1), int(wm.group(2)) * scale, pts))
        for vm in re.finditer(r'\(via\s+("[^"]*"|\S+)\s+(-?[\d.]+)\s+(-?[\d.]+)', nm.group(2)):
            out.append(("via", net, vm.group(1).strip('"'), float(vm.group(2)) * scale, -float(vm.group(3)) * scale))
    return out


def fmt(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


def blocks_for(items):
    segs, vias = [], []
    for it in items:
        if it[0] == "wire":
            _, net, layer, w, pts = it
            for a, c in zip(pts, pts[1:]):
                if a == c:
                    continue
                key = "seg %s %s %s %s %s %s" % (net, layer, fmt(a[0]), fmt(a[1]), fmt(c[0]), fmt(c[1]))
                segs.append('\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width %s)\n\t\t(layer "%s")\n\t\t(net "%s")\n\t\t(uuid "%s")\n\t)\n'
                            % (fmt(a[0]), fmt(a[1]), fmt(c[0]), fmt(c[1]), fmt(TRACK_UM / 1000.0), layer, net, uuid_for(key)))
        else:
            _, net, name, x, y = it
            key = "via %s %s %s" % (net, fmt(x), fmt(y))
            vias.append('\t(via\n\t\t(at %s %s)\n\t\t(size 0.8)\n\t\t(drill 0.4)\n\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "%s")\n\t\t(uuid "%s")\n\t)\n'
                        % (fmt(x), fmt(y), net, uuid_for(key)))
    return segs, vias


def cmd_merge(board, ses, out, keep=False):
    text = open(board).read()
    if not keep:
        text, _ = strip_fill_copper(text)
    items = parse_ses(open(ses).read())
    segs, vias = blocks_for(items)
    if not text.endswith(TRAILER + "\n") and not text.endswith(TRAILER):
        raise SystemExit("fill_freerouting: %s does not end with the expected '(embedded_fonts no)' trailer; the file layout changed. Insert the copper before the final ')' by hand or update TRAILER." % board)
    i = text.rindex(TRAILER)
    text = text[:i] + "".join(sorted(segs) + sorted(vias)) + text[i:]
    open(out, "w").write(text)
    print("merge: %d segments, %d vias added" % (len(segs), len(vias)))
    return 0


def cmd_bad_nets(board, drc_json):
    import json
    bad = set()
    for v in json.load(open(drc_json)).get("violations", []):
        if v["type"] not in ("clearance", "track_width", "shorting_items", "copper_edge_clearance", "hole_clearance", "via_dangling", "track_dangling"):
            continue
        for it in v["items"]:
            m = re.match(r"(?:Track|Via) \[([^\]]*)\]", it["description"])
            if m and it["uuid"].startswith(FILL_PREFIX):
                bad.add(m.group(1))
    print(" ".join(sorted(bad)))
    return 0


def cmd_drop_nets(board, out, nets):
    import pcbnew
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import check_fill
    drop = {n for n in nets if n != "--broken"}
    if "--broken" in nets:
        drop |= set(check_fill.broken_nets(pcbnew.LoadBoard(board)))
    text = open(board).read()
    n = 0

    def sub(m):
        nonlocal n
        blk = m.group(0)
        if '(uuid "%s' % FILL_PREFIX in blk and re.search(r'\(net "([^"]*)"\)', blk).group(1) in drop:
            n += 1
            return ""
        return blk

    open(out, "w").write(BLOCK.sub(sub, text))
    print("drop-nets: removed %d fill items of %d nets" % (n, len(drop)))
    return 0


def cmd_strip(board, out):
    text, n = strip_fill_copper(open(board).read())
    open(out, "w").write(text)
    print("strip: removed %d items tagged %s" % (n, FILL_PREFIX))
    return 0


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "prep":
        rest = a[3:]
        left = None
        if "--left" in rest:
            k = rest.index("--left")
            left = rest[k + 1]
            rest = rest[:k] + rest[k + 2:]
        return cmd_prep(a[1], a[2], rest, left)
    if len(a) >= 3 and a[0] == "bad-nets":
        return cmd_bad_nets(a[1], a[2])
    if len(a) >= 4 and a[0] == "drop-nets":
        return cmd_drop_nets(a[1], a[2], a[3:])
    if len(a) in (4, 5) and a[0] == "merge":
        return cmd_merge(a[1], a[2], a[3], keep="--keep" in a[4:])
    if len(a) == 3 and a[0] == "strip":
        return cmd_strip(a[1], a[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
