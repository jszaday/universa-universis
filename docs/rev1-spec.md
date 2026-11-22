# Universa Universis rev1: electrical design spec

Status: draft for review. Scope: the electrical design of rev1 only (matrix, GPIO extenders, inter-piece bus, power, indicators). Mechanical outline, switch footprints and routing are out of scope except where they constrain the electrical design.

## 1. Basis and terms

Rev0 is a passive diode matrix: 111 key positions, one 1N4148 per position, 150 switch footprints (some positions carry up to four alternative footprints), five breakaway pieces and no controller. The rev0 numbers used here were derived from the rev0 netlist (each footprint's column net and its diode's row net): 111 diodes, 111 distinct (column, row) cells, one diode per cell. Source of the rev0 per-piece key counts: the same netlist, split by the rev0 column and row nets.

Terms. A **position** is one diode cell (named by its rev0 diode reference, D1 to D111), which may carry several alternative switch footprints of which exactly one is populated. A **piece** is one of the five breakaway sections of the panel. A **seam** is the slot between two pieces. An **extender** is a GPIO expander chip (MCP23017, with 16 I/O lines in two 8-bit banks, GPA0 to GPA7 and GPB0 to GPB7) reached over I2C (a two-wire bus: SDA data, SCL clock). A **local matrix** is the row and column grid of one extender, wired inside one piece (the one exception is the F-nav keys, D3). A **line** is one extender I/O pin used as a row, a column or an indicator output. COL2ROW means the diode cathode faces the row line: current flows column, switch, diode anode, diode cathode, row. The **controller** is the off-board MCU module that runs QMK and is the I2C master. **Bus** means the four-wire I2C cable defined in section 5. The **F-nav matrix header** is the separate four-wire cable joining the F-nav piece to the Nav piece (D3).

## 2. Locked decisions (inputs, not reopened here)

- Each piece except F-nav must work fully separated, so no row or column line crosses a seam, each such piece has its own extender(s) and a purely local matrix, and only the four-wire I2C bus crosses its seams. Director decision, round 3: the F-nav piece has no extender; its three keys are a row on the Nav extender, reached over a four-wire matrix cable (D3).
- Extender is the MCP23017 (the locked MCP23018 primary was dropped by D4a), SMD, on the back of the board, SOIC-28W on all five chips (D4b; the fit on the F-row piece is open). No DIP sockets. All headers and connectors are 2.54 mm pitch. Diodes stay through-hole 1N4148, one orientation everywhere, COL2ROW.
- Wired, QMK-compatible firmware; the MCU is a separate module reached by a 4-wire cable (the bus); pull-ups are on the controller side only; each extender's address pins A0 to A2 are hardwired (D5).

## 3. Decisions made in this spec

Each decision lists its rationale and the trigger that would reopen it.

**D1. Five extenders: one per piece except Main (two) and F-nav (none).** The Main piece has 67 positions. One extender has 16 lines, and r + c <= 16 allows at most 8 x 8 = 64 cells, so one chip cannot hold Main. Main is therefore split into two chip-local sub-matrices (Main-L: rev0 columns C0 to C6, Main-R: C7 to C13), each 5 rows x 7 columns = 12 lines. The alternative, one 5 x 14 matrix (19 lines) spread over two chips, would need a row driven by one chip and read by the other, which defeats the chip-local property and doubles the scan traffic per row. Reopen if an extender with more than 16 lines per chip is adopted, which would allow Main on one chip.

**D2. Local matrix shapes.** Chosen to keep each key one trace from its chip (rev0 row labels R0 to R5 are kept only as traceability data, not as a constraint). F-row: 1 row x 13 columns. Main-L and Main-R: 5 x 7 each. Nav: 5 rows x 3 columns, being rev0 rows R1, R2, R4, R5 (rev0 R3 has no keys, so it is dropped) plus the F-nav keys as a fifth row. Numpad: 5 x 4. Every chip is at or under 14 lines including indicators (section 4). Reopen if a donor board needs a key position that does not fit (section 9).

**D3. F-nav (PrtSc, ScrLk, Pause) has no extender; it is a fifth row of the Nav extender (director decision).** The F-nav piece carries only its 3 switches, their 3 diodes and one 1x04 2.54 mm header (pin 1 row line, pins 2 to 4 the three column lines C14, C15, C16). A 4-wire cable joins it straight (pin n to pin n) to a matching 1x04 header on the Nav piece, where the row line goes to U5 GPA4 and the three column lines are the same nets as U5's columns GPB0 to GPB2. Rationale: the F-nav piece (3 keys, about 960 square mm) has no room for a chip and the bus ports on the back; the feasibility study found nothing fits. Consequences: this is the one place where matrix lines (not only the I2C bus) cross a seam, so the F-nav keys do not work when the cable is absent (the other four pieces still do). If that cable is plugged in rotated 180 degrees, the F-nav row meets Nav column C16 and the F-nav column lines C14, C15, C16 meet Nav column C15, column C14 and the F-nav row pin (U5 GPA4). Every diode then faces the wrong way, so the three keys read as dead (a concurrent Nav key press can ghost one column), and nothing is damaged provided the deselect state of the rows is input (high impedance) as required by D4; with a driven-high deselect state a concurrent press could connect a driven-high output to a driven-low output through a diode (current not computed). U5 stays at 8 lines. Reopen if the F-nav keys must work without the cable, or a package small enough for that piece is found.

**D4a. Part: MCP23017 on all five chips; MCP23018 only as an option.** Rationale: per the vendor datasheets read by the coordinator (MCP23017 rev D, DS20001952D, and the MCP23018 datasheet), the MCP23018 gets its eight addresses from a single ADDR pin set by an analog resistor divider (two resistors per chip), which does not fit hardwired digital addressing; the MCP23017 has three digital address pins A0 to A2 (pins 15 to 17) giving eight addresses, each tied straight to VCC or GND (D5). Cost: the MCP23017 has push-pull outputs, not open-drain, which the matrix handles by direction switching (D4). MCP23018 stays an option only with a per-chip divider (two resistors, tolerances to be checked against the datasheet table) replacing the A0-A2 ties; the parts are NOT pin-compatible (MCP23017: GPB0 to GPB7 pins 1 to 8, VDD 9, VSS 10, NC 11, SCL 12, SDA 13, NC 14, A0 to A2 15 to 17, RESET 18, INTB 19, INTA 20, GPA0 to GPA7 21 to 28), so a swap is a schematic and layout change. Reopen if: open-drain row outputs prove necessary (for example the diode-drop test in D4 fails), or divider addressing is accepted.

**D4b. Packages and symbols.** All five chips are MCP23017, SMD, on the back, with one IC and one footprint for the BOM: SOIC-28W (KiCad symbol `MCP23017x-x-SO`, footprint `Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm`) for U1, U3, U4, U5, U6. Open: whether SOIC-28W physically fits the F-row piece is an undecided judgement call under study; it is not claimed to fit. Fallback: SSOP-28 (symbol `MCP23017x-x-SS`, footprint `Package_SO:SSOP-28_5.3x10.2mm_P0.65mm`) on F-row only, or on all five to keep one footprint. Pin numbers are the same in all three packages: the datasheet (rev D) draws one pinout for SOIC, SPDIP and SSOP, and the KiCad stock symbol `MCP23017x-x-SS` extends `MCP23017x-x-SO` (checked in `Interface_Expansion.kicad_sym`), so the pin list in D4a holds for either. Rationale: the feasibility study (below, D8) found a socketed DIP-28 fits only on Nav; a single package keeps the BOM to one part. Reopen if SOIC-28W does not fit F-row (use the fallback), or a donor case cannot take back-side parts (D8).

**D4. Matrix electrical convention.** Rows are extender outputs used in two states: driven low to select a row, and input (high impedance) or driven high otherwise; the deselect state is input (high impedance), never driven high, so that no two outputs can be joined through a closed key and diode (see D3 and section 5). Columns are extender inputs with the internal pull-ups (GPPU) enabled. Datasheet figures (source label WEB: MCP23017 DS20001952 rev D): pull-up current IPU 40 / 75 / 115 uA (min / typ / max) at VDD = 5 V; by arithmetic (author, 5 V divided by that current) this is about 125 / 67 / 43 kOhm (max / typ / min resistance). Both parts operate from 1.8 V to 5.5 V (WEB, same datasheet). This reading of "pull-ups on the controller side only" means: no external pull-up resistor on any piece, for I2C or for the matrix. Input low threshold: VIL max = 0.2 x VDD (WEB), 0.66 V at 3.3 V. A closed key drops the column to the row's output-low level (VOL) plus the 1N4148 forward drop; the author infers about 0.4 V for the diode at tens of microamps (inference, not measured), which leaves little margin under 0.66 V at 3.3 V once VOL is added. This must be bench-tested on the first board (open item). Output-only pins: the MCP23017 datasheet rev D lists GPA7 and GPB7 as output only, and rev C does not state it. Treat the limit as real: no column (input) uses GPA7 or GPB7; the mapping in section 8 respects this and the check script asserts it. Reopen if: the bench test fails (then raise VDD to 5 V, use a lower-drop diode, or move to open-drain output parts), or the internal pull-up value is unsuitable for the longest column trace.

**D5. Extender addresses.** Table in section 6. Each chip's A0 to A2 are hardwired straight to the piece's VCC (1) or GND (0) per that table; there are no address jumpers. Rationale: each piece's role is fixed in firmware, so re-addressing flexibility was not needed, and an address pin never floats. Reopen if more than 8 extenders are needed on one bus, or a chip must be re-addressed in the field.

**D6. Decoupling and reset.** One 100 nF 0805 SMD ceramic capacitor on the back next to each extender, from VDD to VSS within 5 mm of the pins (pins 9 and 10 are adjacent). There are no bulk capacitors. Rationale: 0805 is the smallest size that is comfortable to hand-solder and keeps back-side height low. RESET (active low) is tied directly to VCC on each extender, with no resistor. Rationale: the chip has a power-on reset; a direct tie avoids a floating pin and adds no pull-up resistor to a design that forbids them (D4). Reopen if: hot-plug inrush or supply droop is seen on the bench (then add a bulk ceramic per piece near its first bus port); the controller must be able to reset a hung extender without power cycling the whole bus (needs a fifth bus wire), or I2C bus recovery by clocking fails in testing.

**D7. No interrupt line.** The INT jumpers and INT nets are dropped; INTA and INTB of every extender are left unconnected and the firmware polls (the scan cost is estimated in section 5). Rationale: the director-approved bus has four wires. Reopen if interrupt-driven scanning or wake-on-keypress is needed (then add a fifth bus wire and wire-OR the INT outputs in open-drain mode, IOCON.ODR set on every chip before connecting).

**D8. Extender placement: on the back, inside the original outline.** The original rev0 outline is unchanged. Each extender, its 100 nF capacitor and the bus ports sit on the back of the board, in free space under large keys and between key groups; a SOIC-28W is 7.5 x 17.9 mm and an SSOP-28 5.3 x 10.2 mm. Intent, not yet done in the layout: the bus headers sit on a common edge line on each piece, none in the interior. The feasibility study (a file-based greedy packing, so a miss is not proof of impossibility) found: a socketed DIP-28 fits only on Nav, SOIC-28W fits Main (both chips) and Numpad on the back, SSOP-28 fits F-row (SOIC-28W on F-row is open, D4b), and F-nav fits nothing with the earlier 2x3 ports (hence D3). Candidate coordinates (KiCad board millimetres) from that study: Main around (141, 123) and (391, 128); F-row around (409.5, 40.8); Nav around (466, 111) (the study's DIP spot, now a SOIC); Numpad around (490.6, 135.2) or (510, 67). Final coordinates are the PCB worker's call. Source: the feasibility notes in the author's session scratchpad (`inside/NOTES.md`). Not verified: height of back-side parts against donor cases (open item).

**D9. Lock indicators (Num, Caps, Scroll).** Three active-low outputs on the Numpad extender (GPA5 Num, GPA6 Caps, GPA7 Scroll) brought straight to a 2.54 mm 1x04 header on the Numpad piece (pin 1 VCC for the LED anodes, pins 2 to 4 the three sink lines). The series resistors and LEDs are off-board, in the builder's LED harness, and the builder picks each resistor for the LED colour; without one the LED current is not limited. Rationale: an output driven low sinks the LED current (driven high, the LED is off because its anode is at VCC), and GPA7 may be used as it is output only; the Numpad piece sits at the top-right where the donor lock LEDs usually are (inference, unverified); a header suits donor boards with different LED colours and positions. For scale, 470 Ohm gave about 2 mA at 3.3 V with a 2 V LED (earlier calculation). The ScrLk key (position D85) becomes a plain no-LED switch; the rev0 `MX-LED` symbols are replaced by the no-LED symbol. Lock state reaches the firmware over I2C writes (not through the matrix). Reopen if: a donor keeps its LEDs on a different piece, or LEDs must be on-board.

**D10. Alternate switch footprints on one position.** All alternate footprints of a position connect the same two nets: the position's column line and the position's anode node (switch pad to the single diode's anode). Footprints are wired in parallel, one diode per position, and the rev0 pad swaps in the 90-degree duplicates are kept (switch pads are interchangeable). The builder populates exactly one switch per position; populating two would act as one key and cause no ghosting. Reopen if: footprints with different electrical pad pairs are introduced.

## 4. Per-chip line counts

Each chip's lines are its rows, columns and indicator outputs. Every chip must have at most 16 lines; the done check in the scratchpad recomputes this from the mapping in section 8, not from this table. U2 is retired (the reference is not reused).

| chip | piece | package | positions | rows | columns | indicator lines | total lines | limit |
|---|---|---|---|---|---|---|---|---|
| U1 | F-row | SOIC-28W (fit open, D4b) | 13 | 1 | 13 | 0 | 14 | 16 |
| U3 | Main-L | SOIC-28W | 35 | 5 | 7 | 0 | 12 | 16 |
| U4 | Main-R | SOIC-28W | 32 | 5 | 7 | 0 | 12 | 16 |
| U5 | Nav and F-nav | SOIC-28W | 13 | 5 | 3 | 0 | 8 | 16 |
| U6 | Numpad | SOIC-28W | 18 | 5 | 4 | 3 | 12 | 16 |
| total | | | 111 | | | | | |

Pin assignment: rows on GPA0 upward and columns on GPB0 upward, except U1, whose 13 columns use GPB0 to GPB6 then GPA1 to GPA6 (row on GPA0), and U5, whose fifth row (the F-nav keys) is GPA4 (rows GPA0 to GPA3 are rev0 R1, R2, R4, R5). No column or other input uses GPA7 or GPB7 (output only, see D4); the only use of GPA7 is the Scroll indicator output. U6 indicators: GPA5, GPA6, GPA7 (Num, Caps, Scroll). The F-nav keys (D81, D85, D90) are U5 row 4 on columns 0 to 2, shared with Nav columns C14 to C16.

## 5. Bus and connectors

Bus connector: a plain 1x04 pin header, 2.54 mm pitch (`Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical`), male on every piece, mated by a 4-wire cable with female housings, wired 1:1 (pin n to pin n). The MCU cable is the same four wires. The header is unkeyed; pin 1 is marked by a square pad and silkscreen (see the reversal hazard in section 9).

| pin | signal | notes |
|---|---|---|
| 1 | VCC | logic supply from the controller module; 3.3 V recommended; 1.8 to 5.5 V (WEB, MCP23017 datasheet rev D) |
| 2 | GND | |
| 3 | SDA | I2C data; pull-up on the controller side only |
| 4 | SCL | I2C clock; pull-up on the controller side only |

Reversal analysis (a plug rotated 180 degrees, so pin n meets pin 5-n). Pin pairs are (1,4) and (2,3). Because power must not meet ground, the two pairs must each hold one power pin and one signal pin, so every possible 4-pin order produces one supply-to-signal and one ground-to-signal contact; the candidate order SDA, VCC, SCL, GND has exactly the same reversed contacts (VCC to SCL, GND to SDA) as the order above, so no 4-pin order is reversal-safe. There is no VCC to GND contact in either order. What a reversed cable does, with controller side X (supply VCC_X, open-drain SDA and SCL with pull-ups R to VCC_X) and far side Y (chips, no supply of its own): Y's VDD is X's SCL line, Y's VSS is X's SDA line, Y's SCL pin is VCC_X and Y's SDA pin is GND_X. Assumption for the numbers: pull-ups 4.7 kOhm to 3.3 V on the controller. (1) Pull-up paths only: 3.3 V / 4.7 kOhm is 0.70 mA per line at most; the SDA clamp path (VCC_X, pull-up, Y's VSS, the SDA pin's clamp diode, GND_X) carries about (3.3 - 0.6) V / 4.7 kOhm = 0.57 mA, far under the chip's 20 mA input clamp rating (WEB: DS20001952D absolute maximums: voltage on pins other than VDD -0.6 V to VDD + 0.6 V; IIK and IOK plus or minus 20 mA; VDD -0.3 V to 5.5 V). (2) Not limited by the pull-ups: whenever the controller drives SCL low (every clock pulse), Y's VDD is pulled to 0 V while Y's SCL pin is at VCC_X, so VCC_X is connected through the clamp diode (pin to VDD) and Y's decoupling capacitors straight to the controller's open-drain SCL pin. That current is limited only by the supply, the diode and the MCU pin on-resistance (not known; for example 3.3 V minus 0.6 V over 50 Ohm would be about 54 mA, an illustration, not a datasheet value), which exceeds the 20 mA clamp rating of the chip and likely the MCU pin rating, and Y's pins exceed VDD + 0.6 V. So a reversed cable can damage the chips or the MCU, and the spec does not claim pull-up current limiting. (3) If both ends of a 1:1 cable are rotated 180 degrees, the two rotations cancel (pin n of one piece meets pin n of the other), which is benign; only a single rotated end is hazardous. Whether the MCU pin or the supply tolerates (2) was not verified (no MCU part is chosen).

Recommendation (needs a director decision, because the 1x04 plain header was approved): use a keyed polarised connector so reversal is impossible, at the locked 2.54 mm pitch: Molex KK-254 header, stock footprint `Connector_Molex:Molex_KK-254_AE-6410-04A_1x04_P2.54mm_Vertical`. JST XH (`Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical`) is available in stock KiCad but has 2.50 mm pitch, which breaks the locked pitch. Until decided, the baseline stays the plain header `PinHeader_1x04_P2.54mm_Vertical` with pin 1 marked by a square pad and silkscreen and a colour-coded cable.

INT and the reserved sixth wire of the earlier 2x03 connector are dropped (D7). The F-nav matrix header is a separate 1x04 (row, C14, C15, C16) and is not part of the bus (D3).

Ports per piece. Ports on one piece are wired in parallel. The tree has four cables: controller to Main, Main to F-row, Main to Nav, Nav to Numpad. The minimum ports are therefore Main 3 (controller, F-row, Nav), Nav 2 (from Main, to Numpad), F-row 1, Numpad 1, F-nav 0 (it has no extender and no bus), plus one 1x04 F-nav matrix header on each of F-nav and Nav. No spare ports in this spec; the PCB worker may add one spare to Main or Nav only if the area exists. Rationale: port area is what overflowed the small pieces.

Bus load. Five chips plus cable: the estimate uses about 10 pF per chip pin and about 50 to 100 pF per metre of cable (typical values, not measured), giving well under the 400 pF I2C limit for total cable under about 2 m; start at 400 kHz and fall back to 100 kHz if the run is longer. Scan cost estimate (assumptions: 400 kHz, about 7 bytes of traffic per row step, 9 clocks per byte): 21 row steps across all chips, about 63 clocks each, about 3.3 ms per full scan. Not measured. Both estimates are the author's arithmetic.

## 6. Address table

Address is 0x20 plus (A2 A1 A0 as a binary number), 7-bit. Pins are hardwired: 0 = tied to GND, 1 = tied to VCC (D5). U2's address 0x21 is freed by retiring U2; the other addresses are unchanged to avoid churn.

| chip | piece | A2 | A1 | A0 | 7-bit address |
|---|---|---|---|---|---|
| U1 | F-row | 0 | 0 | 0 | 0x20 |
| (U2 retired) | | 0 | 0 | 1 | 0x21 free |
| U3 | Main-L | 0 | 1 | 0 | 0x22 |
| U4 | Main-R | 0 | 1 | 1 | 0x23 |
| U5 | Nav and F-nav | 1 | 0 | 0 | 0x24 |
| U6 | Numpad | 1 | 0 | 1 | 0x25 |
| spare | | 1 | 1 | x | 0x26, 0x27 |

## 7. Firmware-facing notes

Firmware drives each chip as an independent scan unit: for each local row, drive that row's pin low and set every other row of that chip to input (high impedance, D4), read the column bank, and treat a low column bit as a closed key. Rows are GPA outputs (push-pull on the MCP23017, switched between output-low and input; never driven high), columns are GPB inputs with GPPU enabled. The five chip-local matrices are joined into one QMK layout in firmware; the mapping has no cross-chip row or column. The positions column uses rev0 diode references; `key_footprints` lists the rev0 switch footprint names on that position (alternatives separated by a vertical bar), with the rev0 prefix `MX_` removed. `rev0_col` and `rev0_row` are the rev0 column and row for traceability (rev0 R0 is the F-row), not electrical in rev1. The mapping below is the single definition of the matrix; every chip block (U1, U3, U4, U5, U6; there is no U2) starts with a `# chip=` line.

## 8. Mapping: key to (extender, local row, local column)

### U1, F-row, address 0x20 (13 positions, 1 x 13)

```csv
# chip=U1
position,key_footprints,rev0_col,rev0_row,local_row,local_col,row_pin,col_pin
D1,ESC1|ESC2,C0,R0,0,0,GPA0,GPB0
D12,F1|F14,C2,R0,0,1,GPA0,GPB1
D18,F15|F2,C3,R0,0,2,GPA0,GPB2
D24,F16|F3,C4,R0,0,3,GPA0,GPB3
D30,F17|F4,C5,R0,0,4,GPA0,GPB4
D36,F18|F5,C6,R0,0,5,GPA0,GPB5
D42,F19|F6,C7,R0,0,6,GPA0,GPB6
D48,F20|F7,C8,R0,0,7,GPA0,GPA1
D54,F21|F8,C9,R0,0,8,GPA0,GPA2
D60,F22|F9,C10,R0,0,9,GPA0,GPA3
D66,F10|F23,C11,R0,0,10,GPA0,GPA4
D71,F11|F24,C12,R0,0,11,GPA0,GPA5
D76,F12|F25,C13,R0,0,12,GPA0,GPA6
```

### U3, Main-L, address 0x22 (35 positions, 5 x 7)

```csv
# chip=U3
position,key_footprints,rev0_col,rev0_row,local_row,local_col,row_pin,col_pin
D2,TILDE1,C0,R1,0,0,GPA0,GPB0
D7,1,C1,R1,0,1,GPA0,GPB1
D13,2,C2,R1,0,2,GPA0,GPB2
D19,3,C3,R1,0,3,GPA0,GPB3
D25,4,C4,R1,0,4,GPA0,GPB4
D31,5,C5,R1,0,5,GPA0,GPB5
D37,6,C6,R1,0,6,GPA0,GPB6
D3,TAB1,C0,R2,1,0,GPA1,GPB0
D8,Q1,C1,R2,1,1,GPA1,GPB1
D14,W1,C2,R2,1,2,GPA1,GPB2
D20,E1,C3,R2,1,3,GPA1,GPB3
D26,R1,C4,R2,1,4,GPA1,GPB4
D32,T1,C5,R2,1,5,GPA1,GPB5
D38,Y1,C6,R2,1,6,GPA1,GPB6
D4,CPSLK1|CPSLK2,C0,R3,2,0,GPA2,GPB0
D9,A1,C1,R3,2,1,GPA2,GPB1
D15,S1,C2,R3,2,2,GPA2,GPB2
D21,D1,C3,R3,2,3,GPA2,GPB3
D27,F13,C4,R3,2,4,GPA2,GPB4
D33,G1,C5,R3,2,5,GPA2,GPB5
D39,H1,C6,R3,2,6,GPA2,GPB6
D5,LSHFT1|LSHFT2,C0,R4,3,0,GPA3,GPB0
D10,Z1,C1,R4,3,1,GPA3,GPB1
D16,X1,C2,R4,3,2,GPA3,GPB2
D22,C1,C3,R4,3,3,GPA3,GPB3
D28,V1,C4,R4,3,4,GPA3,GPB4
D34,B1,C5,R4,3,5,GPA3,GPB5
D40,N1,C6,R4,3,6,GPA3,GPB6
D6,LCTRL1|LCTRL2,C0,R5,4,0,GPA4,GPB0
D11,LOPT1|LWIN1|LWIN2,C1,R5,4,1,GPA4,GPB1
D17,LALT1|LALT2|LSUPR1,C2,R5,4,2,GPA4,GPB2
D23,KC7B1|KC7B2,C3,R5,4,3,GPA4,GPB3
D29,SPACE1|SPACE2|SPACE3|SPACE5,C4,R5,4,4,GPA4,GPB4
D35,KC2|KC79,C5,R5,4,5,GPA4,GPB5
D41,KC1|KC70,C6,R5,4,6,GPA4,GPB6
```

### U4, Main-R, address 0x23 (32 positions, 5 x 7)

```csv
# chip=U4
position,key_footprints,rev0_col,rev0_row,local_row,local_col,row_pin,col_pin
D43,7,C7,R1,0,0,GPA0,GPB0
D49,8,C8,R1,0,1,GPA0,GPB1
D55,9,C9,R1,0,2,GPA0,GPB2
D61,0,C10,R1,0,3,GPA0,GPB3
D67,KC0C1,C11,R1,0,4,GPA0,GPB4
D72,KC0D1,C12,R1,0,5,GPA0,GPB5
D77,KC7D1,C13,R1,0,6,GPA0,GPB6
D44,U1,C7,R2,1,0,GPA1,GPB0
D50,I1,C8,R2,1,1,GPA1,GPB1
D56,O1,C9,R2,1,2,GPA1,GPB2
D62,P1,C10,R2,1,3,GPA1,GPB3
D68,KC1A1,C11,R2,1,4,GPA1,GPB4
D73,KC1B1,C12,R2,1,5,GPA1,GPB5
D78,BS1|BS2,C13,R2,1,6,GPA1,GPB6
D45,J1,C7,R3,2,0,GPA2,GPB0
D51,K1,C8,R3,2,1,GPA2,GPB1
D57,L1,C9,R3,2,2,GPA2,GPB2
D63,KC27,C10,R3,2,3,GPA2,GPB3
D69,KC28,C11,R3,2,4,GPA2,GPB4
D74,KC2B1,C12,R3,2,5,GPA2,GPB5
D79,BSLSH1|BSLSH2,C13,R3,2,6,GPA2,GPB6
D46,M1,C7,R4,3,0,GPA3,GPB0
D52,KC33,C8,R4,3,1,GPA3,GPB1
D58,KC34,C9,R4,3,2,GPA3,GPB2
D64,KC35,C10,R4,3,3,GPA3,GPB3
D70,KC73,C11,R4,3,4,GPA3,GPB4
D75,RSHFT1|RSHFT2,C12,R4,3,5,GPA3,GPB5
D80,ENTR1|RTRN1,C13,R4,3,6,GPA3,GPB6
D47,RALT1|RALT2,C7,R5,4,0,GPA4,GPB0
D53,RSUPR1|RWIN1|RWIN2,C8,R5,4,1,GPA4,GPB1
D59,MENU1|ROPT1,C9,R5,4,2,GPA4,GPB2
D65,RCTRL1|RCTRL2,C10,R5,4,3,GPA4,GPB3
```

### U5, Nav and F-nav, address 0x24 (13 positions, 5 x 3; local row 4 is the F-nav piece)

```csv
# chip=U5
position,key_footprints,rev0_col,rev0_row,local_row,local_col,row_pin,col_pin
D82,INS1,C14,R1,0,0,GPA0,GPB0
D86,HOME1,C15,R1,0,1,GPA0,GPB1
D91,PGUP1,C16,R1,0,2,GPA0,GPB2
D83,DEL1,C14,R2,1,0,GPA1,GPB0
D87,END1,C15,R2,1,1,GPA1,GPB1
D92,PGDN1,C16,R2,1,2,GPA1,GPB2
D88,UP1,C15,R4,2,1,GPA2,GPB1
D84,LEFT1,C14,R5,3,0,GPA3,GPB0
D89,DOWN1,C15,R5,3,1,GPA3,GPB1
D93,RGHT1,C16,R5,3,2,GPA3,GPB2
D81,PSCRN1|PSCRN2,C14,R0,4,0,GPA4,GPB0
D85,SCRLK1|SCRLK2,C15,R0,4,1,GPA4,GPB1
D90,PSBRK1|PSBRK2,C16,R0,4,2,GPA4,GPB2
```

### U6, Numpad, address 0x25 (18 positions, 5 x 4)

```csv
# chip=U6
position,key_footprints,rev0_col,rev0_row,local_row,local_col,row_pin,col_pin
D94,NMLK1,C17,R1,0,0,GPA0,GPB0
D99,KPEQ1,C18,R1,0,1,GPA0,GPB1
D103,KPFSL1,C19,R1,0,2,GPA0,GPB2
D108,KPAST1,C20,R1,0,3,GPA0,GPB3
D95,KP7,C17,R2,1,0,GPA1,GPB0
D100,KP8,C18,R2,1,1,GPA1,GPB1
D104,KP9,C19,R2,1,2,GPA1,GPB2
D109,KPMNS1,C20,R2,1,3,GPA1,GPB3
D96,KP4,C17,R3,2,0,GPA2,GPB0
D101,KP5,C18,R3,2,1,GPA2,GPB1
D105,KP6,C19,R3,2,2,GPA2,GPB2
D110,KPPLS1|KPPLS2,C20,R3,2,3,GPA2,GPB3
D97,KP1,C17,R4,3,0,GPA3,GPB0
D102,KP2,C18,R4,3,1,GPA3,GPB1
D106,KP3,C19,R4,3,2,GPA3,GPB2
D111,KPENT1,C20,R4,3,3,GPA3,GPB3
D98,KP0,C17,R5,4,0,GPA4,GPB0
D107,KPDOT1,C19,R5,4,2,GPA4,GPB2
```

## 9. Open items and reopen triggers

- Closed: MCP23018 address pins and MCP23017/MCP23018 pin compatibility (D4a).
- Diode drop against VIL (D4). Inference only: 1N4148 forward drop about 0.4 V at tens of uA plus row VOL must stay under 0.66 V at 3.3 V. Trigger: bench test on the first board; reopen D4a and D4 if it fails.
- GPA7 and GPB7 output-only (D4). Taken from datasheet rev D; rev C does not state it, so it is treated as real for any silicon. Trigger: a datasheet or measurement showing these pins read as inputs on a part in hand.
- Back-side part height against donor cases (D8, D4b, D6) is unmeasured. Trigger: measure the first donor case; if it fails, reopen D4b.
- Candidate placements (D8) come from a greedy study; the PCB worker must confirm each chip fits. Trigger: a layout check that fails.
- SOIC-28W on the F-row piece (D4b): fit is an open judgement call under study. Fallback: SSOP-28 (0.65 mm pitch, harder to hand-solder) on F-row only, or on all five. Trigger: the F-row placement check.
- Bus headers on a common edge line per piece (D8) are intent only; placement is not yet done.
- Bus connector reversal (section 5): no 4-pin order is reversal-safe (a rotated plug always joins a supply pin to a signal pin, and the controller driving SCL low can then push current through the chip clamp diodes beyond the 20 mA rating). Decision needed: adopt the keyed Molex KK-254 1x04 header (2.54 mm pitch). Trigger: director approval, and in any case any wiring mistake in testing. MCU pin tolerance unverified.
- F-nav keys depend on the F-nav matrix cable (D3). Trigger: a requirement that F-nav works alone.
- Polling only (D7). Trigger: interrupt-driven scanning or wake-on-keypress is wanted.
- Indicator location and LED electrical values (D9). Trigger: donor LED position or colour known.
- Cable length and I2C speed (section 5): estimates only. Trigger: bench test with the intended cable run.
- Alternate-footprint rows that physically sit in a different row than their electrical row (rev0: backspace, backslash and Enter cells) keep their rev0 electrical position; a donor needing a different layout is a firmware keymap change, not a hardware change, because every position is its own cell.
- Not covered here: switch footprint cleanup, silkscreen, case fit, BOM costing.
