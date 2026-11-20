# Universa Universis
Retrofit PCB for various Alps full-sized keyboards.

## Planned support:
- AEK (ANSI, EUR, JPN)
- DELL AT101W (ANSI, EUR, JPN)
- DELL AT101 (ANSI, EUR, JPN)
- Strong Man SMK-8851 (BAE, JPN)

## Version History:

### Alpha Revision

Front:
![](images/rev0_front.jpeg)

Back:
![](images/rev0_back.jpeg)

#### Known Issues
- DELL AT101 support impeded by unpopable popout between RAlt and RCtrl.
- ISO Enter in wrong position (1.5u vs. 1u); can fold down leads of switch to compensate.
- Num pad plus and enter key switches rotated 180° (not a significant issue).
- No LED carrier board.

### Beta Revision (rev. 1/β, in progress)

Unbuilt and untested: nothing in this revision has been fabricated or run on a real board yet.

Design changes from the Alpha revision:
- Each keyboard piece has its own I2C GPIO extender (MCP23017) and a local key matrix, and the pieces connect through a six-pin seam connector instead of hand-wired jumpers.
- Diodes are on the back side of the board.
- The switches no longer carry the lock-LED defect.
- KiCad symbol and footprint library tables are project-local.
- On the rev1 PCB branch, the AT101 popout has a perforation ring.

Status of the Alpha known issues:

| Alpha issue | Rev. 1 status |
| --- | --- |
| AT101 popout cannot be popped out | Perforation ring added in the layout; untested on a real board |
| ISO Enter position | Not changed; under review |
| Numpad plus and Enter rotation | Not changed; see `TODO.md` |
| No LED carrier board | Four-pin header provided; carrier board not designed |

Open work is tracked in `TODO.md`; the electrical design is in `docs/rev1-spec.md`.
