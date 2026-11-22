"""Geometric short detector: different-net copper items whose shapes overlap on a shared layer. Usage: shortdet.py board.kicad_pcb"""
import sys,pcbnew
from pcbnew import *
b=LoadBoard(sys.argv[1])
items=[]  # (item, netcode, layers)
for t in b.GetTracks(): items.append(t)
for fp in b.GetFootprints():
  for p in fp.Pads(): items.append(p)
for z in b.Zones(): items.append(z)
cu=[l for l in b.GetEnabledLayers().CuStack()]
def lay(i):
  return [l for l in cu if i.IsOnLayer(l)]
found=set()
n=0
for l in cu:
  L=[i for i in items if i.IsOnLayer(l) and i.GetNetCode()>0 and not (i.GetClass()=='ZONE')]
  bbs=[(i,i.GetBoundingBox()) for i in L]
  for a in range(len(bbs)):
    ia,ba=bbs[a]
    sa=ia.GetEffectiveShape(l)
    for c in range(a+1,len(bbs)):
      ic,bc=bbs[c]
      if ia.GetNetCode()==ic.GetNetCode(): continue
      if not ba.Intersects(bc): continue
      if ia.GetClass()=='PAD' and ic.GetClass()=='PAD' and ia.GetParent()==ic.GetParent(): continue
      if sa.Collide(ic.GetEffectiveShape(l),0):
        found.add((b.GetLayerName(l),ia.GetClass(),ia.GetNetname(),ic.GetClass(),ic.GetNetname(),ia.m_Uuid.AsString()[:8],ic.m_Uuid.AsString()[:8]))
print("SHORTS",len(found), "zones",len(list(b.Zones())))
for f in sorted(found)[:8]: print(" ",f[:5])
