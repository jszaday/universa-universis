"""Written-vs-loaded net check. KiCad re-derives item nets from copper contact at load, silently
overriding a net a script wrote. Compare the net text of every segment/arc/via/pad with what pcbnew
holds after LoadBoard. Any mismatch means the written file contains a short (or net conflict).
Usage: netcheck.py board.kicad_pcb ; exit 1 on mismatch."""
import re,sys,pcbnew
path=sys.argv[1]
txt=open(path).read()
tok=re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')
stack=[];root=None
for m in tok.finditer(txt):
  t=m.group(0)
  if t=='(': n=[]; (stack[-1].append(n) if stack else None); stack.append(n); root=root or n
  elif t==')': stack.pop()
  else: stack[-1].append(t.strip('"') if t[0]=='"' else t)
want={}
def walk(n):
  if not isinstance(n,list) or not n: return
  h=n[0]
  if h in('segment','arc','via','pad'):
    net=uu=None
    for c in n[1:]:
      if isinstance(c,list) and c:
        if c[0]=='net': net=c[1] if len(c)>1 else None
        if c[0]=='uuid': uu=c[1]
    if uu: want[uu]=(h,net or '')
  for c in n[1:]:
    walk(c)
walk(root)
b=pcbnew.LoadBoard(path)
got={}
for t in b.GetTracks(): got[t.m_Uuid.AsString()]=t.GetNetname()
for fp in b.GetFootprints():
  for p in fp.Pads(): got[p.m_Uuid.AsString()]=p.GetNetname()
bad=[(k,w[0],w[1],got.get(k)) for k,w in want.items() if k in got and got[k]!=w[1]]
print("items compared",len([k for k in want if k in got]),"of",len(want),"mismatches",len(bad))
for x in bad[:6]: print("  ",x)
sys.exit(1 if bad else 0)
