# Universa Universis rev1: electrical design spec

Status: draft for review. Scope: the electrical design of rev1 only (matrix, GPIO extenders, inter-piece bus, power, indicators). Mechanical outline, switch footprints and routing are out of scope except where they constrain the electrical design.

## 1. Basis and terms

Rev0 is a passive diode matrix: 111 key positions, one 1N4148 per position, 150 switch footprints (some positions carry up to four alternative footprints), five breakaway pieces and no controller. The rev0 numbers used here were derived from the rev0 netlist (each footprint's column net and its diode's row net): 111 diodes, 111 distinct (column, row) cells, one diode per cell. Source of the rev0 per-piece key counts: the same netlist, split by the rev0 column and row nets.

Terms. A **position** is one diode cell (named by its rev0 diode reference, D1 to D111), which may carry several alternative switch footprints of which exactly one is populated. A **piece** is one of the five breakaway sections of the panel. A **seam** is the slot between two pieces. An **extender** is a GPIO expander chip (MCP23017, with 16 I/O lines in two 8-bit banks, GPA0 to GPA7 and GPB0 to GPB7) reached over I2C (a two-wire bus: SDA data, SCL clock). A **local matrix** is the row and column grid of one extender, wired only inside one piece. A **line** is one extender I/O pin used as a row, a column or an indicator output. COL2ROW means the diode cathode faces the row line: current flows column, switch, diode anode, diode cathode, row. The **controller** is the off-board MCU module that runs QMK and is the I2C master. **Bus** means the six-wire cable set defined in section 5.

## 2. Locked decisions (inputs, not reopened here)

- Each piece must work fully separated, so no row or column line crosses a seam. Each piece has its own extender(s) and a purely local matrix; only the I2C bus crosses seams.
- Extender is through-hole DIP-28 in a socket. Part: MCP23018 was the locked primary and MCP23017 the locked fallback; the fallback trigger was met (decision D4a), so rev1 uses MCP23017 on all six chips. All headers and connectors are 2.54 mm pitch. Diodes stay through-hole 1N4148, one orientation everywhere, COL2ROW.
- Wired, QMK-compatible firmware; the MCU is a separate module reached by a 4 to 6 wire cable; pull-ups are on the controller side only; extender address is set by solder jumpers on A0 to A2.

## 3. Decisions made in this spec

Each decision lists its rationale and the trigger that would reopen it.

**D1. Six extenders, one per piece except Main, which has two.** The Main piece has 67 positions. One extender has 16 lines, and r + c <= 16 allows at most 8 x 8 = 64 cells, so one chip cannot hold Main. Main is therefore split into two chip-local sub-matrices (Main-L: rev0 columns C0 to C6, Main-R: C7 to C13), each 5 rows x 7 columns = 12 lines. The alternative, one 5 x 14 matrix (19 lines) spread over two chips, would need a row driven by one chip and read by the other, which defeats the chip-local property and doubles the scan traffic per row. Reopen if an extender with more than 16 lines per chip is adopted, which would allow Main on one chip.

**D2. Local matrix shapes.** Chosen to keep each key one trace from its chip and to keep row counts equal to physical rows (rev0 row labels R0 to R5 are kept only as traceability data, not as a constraint). F-row: 1 row x 13 columns. F-nav: 1 x 3. Main-L and Main-R: 5 x 7 each. Nav: 4 x 3 (rev0 row R3 has no keys, so it is dropped). Numpad: 5 x 4. Rationale: smallest line counts that keep wiring local; every chip is at or under 14 lines including indicators (section 4). Reopen if a donor board needs a key position that does not fit (section 9).

**D3. F-nav (three keys) keeps its own extender.** The locked rule (no line crosses a seam) leaves no way to share a chip with Nav. Cost: one socket and chip for three keys. Reopen if the locked rule is relaxed or a cheaper 8-bit expander in the same I2C family is accepted for this piece.

**D4a. Part: MCP23017 on all six chips; MCP23018 only as an option.** Rationale: per the vendor datasheets read by the coordinator (MCP23017 rev D, DS20001952D, and the MCP23018 datasheet), the MCP23018 gets its eight addresses from a single ADDR pin set by an analog resistor divider (two resistors per chip), which conflicts with the locked solder-jumper addressing; the MCP23017 has three digital address pins A0 to A2 (pins 15 to 17) giving eight addresses, so solder jumpers work unchanged. Cost: the MCP23017 has push-pull outputs, not open-drain, which the matrix handles by direction switching (D4). KiCad symbol: `MCP23017x-x-SP`, DIP-28 socket. MCP23018 stays an option only with a per-chip divider (two resistors, tolerances to be checked against the datasheet table) replacing the A0-A2 jumpers; the parts are NOT pin-compatible (MCP23017: GPB0 to GPB7 pins 1 to 8, VDD 9, VSS 10, NC 11, SCL 12, SDA 13, NC 14, A0 to A2 15 to 17, RESET 18, INTB 19, INTA 20, GPA0 to GPA7 21 to 28), so a swap is a schematic and layout change. Reopen if: open-drain row outputs prove necessary (for example the diode-drop test in D4 fails), or divider addressing is accepted.

**D4. Matrix electrical convention.** Rows are extender outputs used in two states: driven low to select a row, and input (high impedance) or driven high otherwise; the firmware picks one deselect state and keeps it. Columns are extender inputs with the internal pull-ups (GPPU) enabled. Datasheet figures (source label WEB: MCP23017 DS20001952 rev D): pull-up current IPU 40 / 75 / 115 uA (min / typ / max) at VDD = 5 V; by arithmetic (author, 5 V divided by that current) this is about 125 / 67 / 43 kOhm (max / typ / min resistance). Both parts operate from 1.8 V to 5.5 V (WEB, same datasheet). This reading of "pull-ups on the controller side only" means: no external pull-up resistor on any piece, for I2C or for the matrix. Input low threshold: VIL max = 0.2 x VDD (WEB), 0.66 V at 3.3 V. A closed key drops the column to the row's output-low level (VOL) plus the 1N4148 forward drop; the author infers about 0.4 V for the diode at tens of microamps (inference, not measured), which leaves little margin under 0.66 V at 3.3 V once VOL is added. This must be bench-tested on the first board (open item). Output-only pins: the MCP23017 datasheet rev D lists GPA7 and GPB7 as output only, and rev C does not state it. Treat the limit as real: no column (input) uses GPA7 or GPB7; the mapping in section 8 respects this and the check script asserts it. Reopen if: the bench test fails (then raise VDD to 5 V, use a lower-drop diode, or move to open-drain output parts), or the internal pull-up value is unsuitable for the longest column trace.

**D5. Extender addresses.** Table in section 6. Address jumpers are 3-pad solder jumpers (pad for the A pin, one pad to GND, one to VCC) delivered bridged to GND by a thin trace; to set a 1 the builder cuts the trace and bridges the VCC side. Rationale: a chip address pin must never float, and a default of 0x20 makes an unmodified board work alone. Reopen if more than 8 extenders are needed on one bus.

**D6. Decoupling and reset.** One 100 nF ceramic capacitor (through-hole, 2.54 mm lead pitch) from VDD to VSS within 5 mm of every extender, plus one 10 uF capacitor per piece near its first bus port. RESET (active low) is tied directly to VCC on each extender, with no resistor. Rationale: the chip has a power-on reset; a direct tie avoids a floating pin and adds no pull-up resistor to a design that forbids them (D4). Reopen if: the controller must be able to reset a hung extender without power cycling the whole bus (then route RESET to bus pin 6, section 5), or I2C bus recovery by clocking fails in testing.

**D7. INT is optional and off by default.** Each extender's INT output (INTA and INTB mirrored in firmware) goes to bus pin 5 through a solder jumper that is open by default. Rationale: at power-up the INT pins of the chip are push-pull and would fight each other on a shared line; firmware must set open-drain INT mode (IOCON.ODR) on every extender before any INT jumper is closed. Scanning does not need INT. Reopen if: sleep or wake-on-keypress or lower scan latency is wanted.

**D8. Extender placement: service strip.** Rev0 pieces have no margin around the keys and the 14 mm switch cutouts leave about 5 mm between keys, so a 36 x 10 mm socket (28-pin, 0.3 inch row spacing) cannot sit between keys. Each piece gets a 14 mm deep service strip along one outer edge (the edge not facing another piece; F-row and F-nav: top, Main, Nav and Numpad: bottom), at least 42 mm long, carrying its extender socket(s), decoupling, address and INT jumpers and bus ports. Main has one socket in the strip under each half. Fallback: the bottom copper side under a key-free region. Not verified: whether any donor case has the clearance for a strip or for a 8 mm tall socket on the bottom side. Reopen on measuring the first donor case (README lists AEK, DELL AT101W, DELL AT101, Strong Man SMK-8851).

**D9. Lock indicators (Num, Caps, Scroll).** Three active-low outputs on the Numpad extender (GPA5 Num, GPA6 Caps, GPA7 Scroll) with a 470 Ohm series resistor each, brought to a 2.54 mm 1x04 header (pin 1 VCC for the LED anodes, pins 2 to 4 the three sink lines through the resistors). LEDs are off-board and wired by the builder. Rationale: an output driven low sinks the LED current (driven high, the LED is off because its anode is at VCC), and GPA7 may be used as it is output only; the Numpad piece sits at the top-right where the donor lock LEDs usually are (inference, unverified); a header suits donor boards with different LED colours and positions. The 470 Ohm value gives about 2 mA at 3.3 V with a 2 V LED (calculated; adjust for LED colour). The ScrLk key (position D85) becomes a plain no-LED switch; the rev0 `MX-LED` symbols are replaced by the no-LED symbol. Lock state reaches the firmware over I2C writes (not through the matrix). Reopen if: a donor keeps its LEDs on a different piece, or LEDs must be on-board.

**D10. Alternate switch footprints on one position.** All alternate footprints of a position connect the same two nets: the position's column line and the position's anode node (switch pad to the single diode's anode). Footprints are wired in parallel, one diode per position, and the rev0 pad swaps in the 90-degree duplicates are kept (switch pads are interchangeable). The builder populates exactly one switch per position; populating two would act as one key and cause no ghosting. Reopen if: footprints with different electrical pad pairs are introduced.

## 4. Per-chip line counts

Each chip's lines are its rows, columns and indicator outputs. Every chip must have at most 16 lines; the done check in the scratchpad recomputes this from the mapping in section 8, not from this table.

| chip | piece | positions | rows | columns | indicator lines | total lines | limit |
|---|---|---|---|---|---|---|---|
| U1 | F-row | 13 | 1 | 13 | 0 | 14 | 16 |
| U2 | F-nav | 3 | 1 | 3 | 0 | 4 | 16 |
| U3 | Main-L | 35 | 5 | 7 | 0 | 12 | 16 |
| U4 | Main-R | 32 | 5 | 7 | 0 | 12 | 16 |
| U5 | Nav | 10 | 4 | 3 | 0 | 7 | 16 |
| U6 | Numpad | 18 | 5 | 4 | 3 | 12 | 16 |
| total | | 111 | | | | | |

Pin assignment: rows on GPA0 upward and columns on GPB0 upward, except U1, whose 13 columns use GPB0 to GPB6 then GPA1 to GPA6 (row on GPA0). No column or other input uses GPA7 or GPB7 (output only, see D4); the only use of GPA7 is the Scroll indicator output. U6 indicators: GPA5, GPA6, GPA7 (Num, Caps, Scroll).

## 5. Seam connector and bus

One connector type everywhere: a 2x03 shrouded (boxed) pin header, 2.54 mm pitch, with a polarising notch, male on every piece (the MCU module end uses whatever connector the module has, wired to this pinout). Mating is a 6-way flat ribbon cable with female IDC sockets, wired 1:1 (pin n to pin n). The notch gives keying and prevents reversal. The 4 to 6 wire MCU cable uses the same pinout.

| pin | signal | notes |
|---|---|---|
| 1 | VCC | logic supply from the controller module; 3.3 V recommended; 1.8 to 5.5 V on MCP23017 and MCP23018 (WEB, datasheets) |
| 2 | GND | |
| 3 | SDA | I2C data; pull-up on the controller side only |
| 4 | SCL | I2C clock; pull-up on the controller side only |
| 5 | INT | wired-OR open-drain interrupt, each chip joins through a jumper that is open by default (D7); optional |
| 6 | RSV | reserved, passed through all ports, connected to no chip in rev1 (candidate for RESET, D6) |

Every piece carries three ports wired in parallel (pin n of port A = pin n of ports B and C), so a piece can join up to three neighbours or the controller. Topology (a tree, one cable per seam): controller to Main port C; Main port A to F-row; Main port B to Nav; Nav port A to F-nav; Nav port B to Numpad. Ports sit on the service strip (D8).

Bus load. Six chips plus ribbon: the estimate uses about 10 pF per chip pin and about 50 to 100 pF per metre of ribbon (typical values, not measured), giving well under the 400 pF I2C limit for total cable under about 2 m; start at 400 kHz and fall back to 100 kHz if the run is longer. Scan cost estimate (assumptions: 400 kHz, about 7 bytes of traffic per row step, 9 clocks per byte): 21 row steps across all chips, about 63 clocks each, about 3.3 ms per full scan. Not measured. Both estimates are the author's arithmetic.

## 6. Address table

Address is 0x20 plus (A2 A1 A0 as a binary number), 7-bit. Jumper: 0 = bridged to GND (default), 1 = bridged to VCC.

| chip | piece | A2 | A1 | A0 | 7-bit address |
|---|---|---|---|---|---|
| U1 | F-row | 0 | 0 | 0 | 0x20 |
| U2 | F-nav | 0 | 0 | 1 | 0x21 |
| U3 | Main-L | 0 | 1 | 0 | 0x22 |
| U4 | Main-R | 0 | 1 | 1 | 0x23 |
| U5 | Nav | 1 | 0 | 0 | 0x24 |
| U6 | Numpad | 1 | 0 | 1 | 0x25 |
| spare | | 1 | 1 | x | 0x26, 0x27 |

## 7. Firmware-facing notes

Firmware drives each chip as an independent scan unit: for each local row, drive that row's pin low and set every other row of that chip to its deselect state (input or driven high, D4), read the column bank, and treat a low column bit as a closed key. Rows are GPA outputs (push-pull on the MCP23017, switched between output-low and input), columns are GPB inputs with GPPU enabled. The six local matrices are joined into one QMK layout in firmware; the mapping has no cross-chip row or column. The positions column uses rev0 diode references; `key_footprints` lists the rev0 switch footprint names on that position (alternatives separated by a vertical bar), with the rev0 prefix `MX_` removed. `rev0_col` and `rev0_row` are the rev0 column and row for traceability (rev0 R0 is the F-row), not electrical in rev1. The mapping below is the single definition of the matrix; every chip block starts with a `# chip=` line.

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

### U2, F-nav, address 0x21 (3 positions, 1 x 3)

```csv
# chip=U2
position,key_footprints,rev0_col,rev0_row,local_row,local_col,row_pin,col_pin
D81,PSCRN1|PSCRN2,C14,R0,0,0,GPA0,GPB0
D85,SCRLK1|SCRLK2,C15,R0,0,1,GPA0,GPB1
D90,PSBRK1|PSBRK2,C16,R0,0,2,GPA0,GPB2
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

### U5, Nav, address 0x24 (10 positions, 4 x 3)

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

- Closed: MCP23018 address pins and MCP23017/MCP23018 pin compatibility. Both resolved by the datasheet check (D4a): rev1 uses MCP23017, A0 to A2 as in section 6; the parts are not pin-compatible.
- Diode drop against VIL (D4). Inference only: 1N4148 forward drop about 0.4 V at tens of uA plus row VOL must stay under 0.66 V at 3.3 V. Trigger: bench test on the first board; reopen D4a and D4 if it fails.
- GPA7 and GPB7 output-only (D4). Taken from datasheet rev D; rev C does not state it, so it is treated as real for any silicon. Trigger: a datasheet or measurement showing these pins read as inputs on a part in hand (then the constraint can be relaxed).
- Service strip clearance in donor cases (D8). Trigger: measure the first donor case.
- Indicator location and LED electrical values (D9). Trigger: donor LED position or colour known.
- INT use and RESET routing (D6, D7). Trigger: sleep, wake or recovery requirements from firmware.
- Cable length and I2C speed (section 5): estimates only. Trigger: bench test with the intended cable run.
- Alternate-footprint rows that physically sit in a different row than their electrical row (rev0: backspace, backslash and Enter cells) keep their rev0 electrical position; a donor needing a different layout is a firmware keymap change, not a hardware change, because every position is its own cell.
- Not covered here: switch footprint cleanup, panel outline, silkscreen, case fit, BOM costing.
