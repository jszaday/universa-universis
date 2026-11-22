// Host test for mcp23017_matrix.c with a fake MCP23017 (IOCON.BANK=0 register
// model, sequential addressing). Build and run: see Makefile (`make test`).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef SPEC_PATH
#define SPEC_PATH "../docs/rev1-spec.md"
#endif

#include "matrix_config.h"
#include "mcp23017_matrix.h"

static int failures, checks;
#define CHECK(cond, ...)                                  \
    do {                                                  \
        checks++;                                         \
        if (!(cond)) {                                    \
            failures++;                                   \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);   \
            printf(__VA_ARGS__);                          \
            printf("\n");                                 \
        }                                                 \
    } while (0)

// ---- fake extender ---------------------------------------------------------
typedef struct {
    bool present;
    uint8_t iodir[2], gppu[2], olat[2];
} fake_chip_t;
typedef struct {
    uint8_t row_pin, col_pin;
} press_t;
typedef struct {
    fake_chip_t chip[MX_MAX_CHIPS]; // index = addr - 0x20
    press_t pressed[MX_MAX_CHIPS][8];
    uint8_t n_pressed[MX_MAX_CHIPS];
    int calls[MX_MAX_CHIPS]; // bus calls per address, including failed ones
    int row_high_drives;     // writes that left a matrix row driven high (forbidden by the spec)
    int multi_row_selects;   // writes that left more than one row of a chip as an output
} fake_t;

static void fake_reset_chip(fake_chip_t *c) {
    c->iodir[0] = c->iodir[1] = 0xFF; // power-on: all inputs
    c->gppu[0] = c->gppu[1] = 0;
    c->olat[0] = c->olat[1] = 0;
}
static void fake_init(fake_t *f) {
    memset(f, 0, sizeof *f);
    for (int i = 0; i < MX_MAX_CHIPS; i++) fake_reset_chip(&f->chip[i]);
}
static uint16_t u16(const uint8_t *p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }

static uint16_t pin_levels(const fake_t *f, int ci) {
    const fake_chip_t *c = &f->chip[ci];
    uint16_t iodir = u16(c->iodir), gppu = u16(c->gppu), olat = u16(c->olat), v = 0;
    for (int p = 0; p < 16; p++) {
        uint16_t b = (uint16_t)1 << p;
        int level;
        if (!(iodir & b)) level = (olat & b) != 0;      // output: drives OLAT
        else level = (gppu & b) != 0;                   // input: pull-up or floating(0)
        if ((iodir & b) && (gppu & b)) {
            for (int k = 0; k < f->n_pressed[ci]; k++) {
                uint16_t rb = (uint16_t)1 << f->pressed[ci][k].row_pin;
                if (f->pressed[ci][k].col_pin == p && !(iodir & rb) && !(olat & rb)) level = 0; // diode conducts, row low
            }
        }
        if (level) v |= b;
    }
    return v;
}

// BANK=0 map: register r covers port A (even) / B (odd); sequential access
// auto-increments, so 2 bytes at the A register cover both ports.
static uint8_t *reg_ptr(fake_chip_t *c, uint8_t reg) {
    switch (reg) {
        case 0x00: return &c->iodir[0];
        case 0x01: return &c->iodir[1];
        case 0x0C: return &c->gppu[0];
        case 0x0D: return &c->gppu[1];
        case 0x12: case 0x14: return &c->olat[0]; // GPIO write -> OLAT
        case 0x13: case 0x15: return &c->olat[1];
        default: return 0;
    }
}
static bool fake_write(void *ctx, uint8_t addr, uint8_t reg, const uint8_t *d, uint8_t len) {
    fake_t *f = ctx;
    if (addr < 0x20 || addr > 0x27) return false;
    f->calls[addr - 0x20]++;
    if (!f->chip[addr - 0x20].present) return false;
    for (uint8_t i = 0; i < len; i++) {
        uint8_t *p = reg_ptr(&f->chip[addr - 0x20], reg + i);
        if (!p) return false; // unmodelled register: treat as NACK so a wrong address fails loudly
        *p = d[i];
    }
    // Invariant monitor (uses the real table): rows may be outputs only as the single active low row.
    for (int k = 0; k < MX_NUM_CHIPS; k++) {
        if (mx_chips[k].addr != addr) continue;
        const fake_chip_t *c = &f->chip[addr - 0x20];
        uint16_t iodir = u16(c->iodir), olat = u16(c->olat);
        int outs = 0;
        for (int r = 0; r < mx_chips[k].n_rows; r++) {
            uint16_t b = (uint16_t)1 << mx_chips[k].row_pins[r];
            if (!(iodir & b)) {
                outs++;
                if (olat & b) f->row_high_drives++;
            }
        }
        if (outs > 1) f->multi_row_selects++;
    }
    return true;
}
static bool fake_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *d, uint8_t len) {
    fake_t *f = ctx;
    if (addr < 0x20 || addr > 0x27) return false;
    f->calls[addr - 0x20]++;
    if (!f->chip[addr - 0x20].present) return false;
    if (reg != 0x12 || len != 2) return false; // only GPIO reads are modelled
    uint16_t v = pin_levels(f, addr - 0x20);
    d[0] = v & 0xFF;
    d[1] = v >> 8;
    return true;
}

// ---- helpers ---------------------------------------------------------------
static mx_bus_t bus_for(fake_t *f) { return (mx_bus_t){fake_write, fake_read, f}; }
static bool key(const mx_row_t *m, int r, int c) { return (m[r] >> c) & 1; }
static int count_keys(const mx_row_t *m) {
    int n = 0;
    for (int r = 0; r < MX_LOGICAL_ROWS; r++) n += __builtin_popcount(m[r]);
    return n;
}
static const mx_chip_cfg_t *chip_by_addr(uint8_t addr) {
    for (int i = 0; i < MX_NUM_CHIPS; i++)
        if (mx_chips[i].addr == addr) return &mx_chips[i];
    return 0;
}
static void all_present(fake_t *f) {
    for (int i = 0; i < MX_NUM_CHIPS; i++) f->chip[mx_chips[i].addr - 0x20].present = true;
}
static void start(fake_t *f, mx_state_t *s) {
    mx_bus_t bus = bus_for(f);
    mx_init(s, &bus, mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS);
}
// pin helpers for hand-written expectations: GPA n = n, GPB n = 8 + n
#define GPA(n) (n)
#define GPB(n) (8 + (n))
static void press(fake_t *f, uint8_t addr, uint8_t row_pin, uint8_t col_pin) {
    int ci = addr - 0x20;
    f->pressed[ci][f->n_pressed[ci]++] = (press_t){row_pin, col_pin};
}

// ---- tests -----------------------------------------------------------------
static const char *validate_real(void) { return mx_validate(mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS); }

static void test_validate(void) {
    const char *e = validate_real();
    CHECK(e == 0, "real table must validate: %s", e ? e : "");
    mx_chip_cfg_t bad[MX_NUM_CHIPS];
    memcpy(bad, mx_chips, sizeof bad);
    bad[1].addr = bad[0].addr;
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "duplicate address must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[1].col_pins[0] = bad[1].row_pins[0];
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "pin as both row and column must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[1].addr = 0x30;
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "address outside 0x20..0x27 must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[1].col_pins[6] = GPB(7); // U3 last column onto GPB7: output-only pin
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "column on GPB7 must be rejected");
    bad[1].col_pins[6] = GPA(7);
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "column on GPA7 must be rejected");
    memcpy(bad, mx_chips, sizeof bad);
    bad[1].row_pins[4] = GPB(7); // GPB7 as a row is allowed (the real table already has U3 row 2 on GPA7)
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) == 0, "row on GPB7 must be accepted");
    memcpy(bad, mx_chips, sizeof bad);
    bad[4].ind_pins[0] = bad[4].col_pins[0]; // indicator on a column pin
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "indicator overlapping a column must be rejected");
    CHECK(mx_validate(mx_chips, MX_NUM_CHIPS, MX_LOGICAL_ROWS, 20) != 0, "map entry outside logical size must be rejected");
    // two positions on one logical cell: point U4's first cell at U3's first cell
    mx_pos_t dup[5 * 7];
    memcpy(dup, mx_chips[2].map, sizeof dup);
    dup[0] = mx_chips[1].map[0];
    memcpy(bad, mx_chips, sizeof bad);
    bad[2].map = dup;
    CHECK(mx_validate(bad, MX_NUM_CHIPS, MX_LOGICAL_ROWS, MX_LOGICAL_COLS) != 0, "duplicate logical cell must be rejected");
}

static void test_init_registers(void) {
    fake_t f;
    fake_init(&f);
    all_present(&f);
    mx_state_t s;
    start(&f, &s);
    CHECK(mx_chips_up(&s) == MX_NUM_CHIPS, "all chips up, got %u", mx_chips_up(&s));
    for (int i = 0; i < MX_NUM_CHIPS; i++) {
        const mx_chip_cfg_t *c = &mx_chips[i];
        const fake_chip_t *fc = &f.chip[c->addr - 0x20];
        uint16_t rows = 0, cols = 0, ind = 0;
        for (int k = 0; k < c->n_rows; k++) rows |= 1u << c->row_pins[k];
        for (int k = 0; k < c->n_cols; k++) cols |= 1u << c->col_pins[k];
        for (int k = 0; k < c->n_ind; k++) ind |= 1u << c->ind_pins[k];
        uint16_t iodir = u16(fc->iodir), gppu = u16(fc->gppu), olat = u16(fc->olat);
        CHECK((iodir & rows) == rows, "0x%02X: unselected rows must be inputs (high-Z), IODIR=%04X", c->addr, iodir);
        CHECK((gppu & rows) == 0, "0x%02X: row pull-ups must be off, GPPU=%04X", c->addr, gppu);
        CHECK(gppu == cols, "0x%02X: pull-ups on exactly the columns, GPPU=%04X want %04X", c->addr, gppu, cols);
        CHECK((olat & rows) == 0, "0x%02X: row output latches must be low, OLAT=%04X", c->addr, olat);
        CHECK((iodir & cols) == cols, "0x%02X: columns are inputs", c->addr);
        CHECK((iodir & ind) == 0 && (olat & ind) == ind, "0x%02X: indicators are outputs driven high (LED off)", c->addr);
    }
    CHECK(f.row_high_drives == 0 && f.multi_row_selects == 0, "init must not drive any row high");
}

static void test_rows_high_z_during_scan(void) {
    fake_t f;
    fake_init(&f);
    all_present(&f);
    mx_state_t s;
    start(&f, &s);
    press(&f, 0x22, GPA(2), GPA(3));
    mx_row_t m[MX_LOGICAL_ROWS];
    for (int i = 0; i < 50; i++) mx_scan(&s, m);
    CHECK(f.row_high_drives == 0, "a row was driven high %d times: unselected rows must be high-Z", f.row_high_drives);
    CHECK(f.multi_row_selects == 0, "more than one row was an output at once %d times", f.multi_row_selects);
    CHECK(key(m, 1, 1) && count_keys(m) == 1, "key still read with high-Z deselect");
}

static void test_keys_at_logical_positions(void) {
    fake_t f;
    fake_init(&f);
    all_present(&f);
    mx_state_t s;
    start(&f, &s);
    mx_row_t m[MX_LOGICAL_ROWS];
    CHECK(!mx_scan(&s, m) && count_keys(m) == 0, "idle matrix is empty and unchanged");

    // Expectations are hand-derived from the spec CSV rows, not read from the table.
    press(&f, 0x20, GPB(6), GPA(0)); // D1   ESC          -> (0,0)
    press(&f, 0x20, GPB(6), GPB(1)); // D71  F11          -> (0,12)
    press(&f, 0x22, GPA(2), GPA(3)); // D7   1            -> (1,1)
    press(&f, 0x23, GPB(5), GPB(6)); // D43  7            -> (1,7)
    press(&f, 0x24, GPB(7), GPB(5)); // D85  ScrLk (F-nav row 4) -> (0,15)
    press(&f, 0x24, GPA(7), GPB(5)); // D88  Up           -> (4,15)
    press(&f, 0x25, GPB(0), GPB(5)); // D107 KP.          -> (5,19)
    CHECK(mx_scan(&s, m), "first press reports a change");
    CHECK(count_keys(m) == 7, "exactly 7 keys, got %d", count_keys(m));
    CHECK(key(m, 0, 0), "D1 -> (0,0)");
    CHECK(key(m, 0, 12), "D71 -> (0,12)");
    CHECK(key(m, 1, 1), "D7 -> (1,1)");
    CHECK(key(m, 1, 7), "D43 -> (1,7)");
    CHECK(key(m, 0, 15), "D85 (F-nav) -> (0,15)");
    CHECK(key(m, 4, 15), "D88 -> (4,15)");
    CHECK(key(m, 5, 19), "D107 -> (5,19)");
    CHECK(!mx_scan(&s, m), "steady state reports no change");
}

static void test_missing_chip(void) {
    fake_t f;
    fake_init(&f);
    all_present(&f);
    f.chip[0x24 - 0x20].present = false; // Nav chip absent
    mx_state_t s;
    start(&f, &s);
    CHECK(mx_chips_up(&s) == MX_NUM_CHIPS - 1, "all but the Nav chip up");
    press(&f, 0x22, GPA(2), GPA(3));
    press(&f, 0x24, GPB(7), GPB(5)); // key on the absent chip must never appear
    mx_row_t m[MX_LOGICAL_ROWS];
    mx_scan(&s, m);
    CHECK(count_keys(m) == 1 && key(m, 1, 1), "present chips work, absent chip gives no keys");
    int base = f.calls[0x24 - 0x20];
    for (int i = 0; i < 254; i++) mx_scan(&s, m);
    CHECK(f.calls[0x24 - 0x20] == base, "no bus traffic to a down chip between retries (%d extra)", f.calls[0x24 - 0x20] - base);

    f.chip[0x24 - 0x20].present = true;
    int n = 0, up = 3; // index of 0x24 in mx_chips
    while (!s.up[up] && n < 600) {
        mx_scan(&s, m);
        n++;
    }
    CHECK(s.up[up] && n <= 256, "chip reinitialised within one retry period, took %d scans", n);
    mx_scan(&s, m);
    CHECK(count_keys(m) == 2 && key(m, 0, 15), "keys of the revived chip appear");
    const mx_chip_cfg_t *c = chip_by_addr(0x24);
    CHECK(c && (u16(f.chip[0x24 - 0x20].gppu) & 0x6002) == 0x6002, "revived chip was reconfigured (columns pulled up)");
}

static void test_chip_dies_midrun(void) {
    fake_t f;
    fake_init(&f);
    all_present(&f);
    mx_state_t s;
    start(&f, &s);
    press(&f, 0x22, GPA(2), GPA(3));
    press(&f, 0x23, GPB(5), GPB(6));
    mx_row_t m[MX_LOGICAL_ROWS];
    mx_scan(&s, m);
    CHECK(count_keys(m) == 2, "both keys seen");
    f.chip[0x23 - 0x20].present = false; // piece cut off or unplugged
    CHECK(mx_scan(&s, m), "loss of a key is a change");
    CHECK(count_keys(m) == 1 && key(m, 1, 1) && !key(m, 1, 7), "dead chip's key released, other chip unaffected");
    fake_reset_chip(&f.chip[0x23 - 0x20]); // power-cycled piece returns with default registers
    f.chip[0x23 - 0x20].present = true;
    for (int i = 0; i < 256; i++) mx_scan(&s, m);
    mx_scan(&s, m);
    CHECK(count_keys(m) == 2, "chip rejoins after a retry period");
}

static void test_all_down_no_hang(void) {
    fake_t f;
    fake_init(&f);
    mx_state_t s;
    start(&f, &s);
    mx_row_t m[MX_LOGICAL_ROWS];
    for (int i = 0; i < 2000; i++) mx_scan(&s, m); // returns, i.e. no hang
    CHECK(count_keys(m) == 0 && mx_chips_up(&s) == 0, "no chips: empty matrix");
    for (int i = 0; i < MX_NUM_CHIPS; i++) CHECK(f.calls[i] < 40, "bounded bus traffic with all chips down (%d calls)", f.calls[i]);
}

// ---- spec cross-check ------------------------------------------------------
// Parses the CSV blocks of docs/rev1-spec.md section 8 and compares every entry
// with mx_chips. Returns the number of mismatches; *entries gets the CSV row count.
static int pin_of(const char *s) { // "GPA4" -> 4, "GPB2" -> 10; -1 if malformed
    if (s[0] != 'G' || s[1] != 'P' || (s[2] != 'A' && s[2] != 'B') || s[3] < '0' || s[3] > '7') return -1;
    return (s[2] == 'B' ? 8 : 0) + (s[3] - '0');
}
static int quiet;
static int check_spec(const char *text, int *entries) {
    int bad = 0, in_csv = 0, addr = -1;
    *entries = 0;
    const char *p = text;
    while (*p) {
        const char *e = strchr(p, '\n');
        size_t n = e ? (size_t)(e - p) : strlen(p);
        char line[256];
        if (n >= sizeof line) n = sizeof line - 1;
        memcpy(line, p, n);
        line[n] = 0;
        p = e ? e + 1 : p + n;
        char *a;
        if (!strncmp(line, "### U", 5) && (a = strstr(line, "address 0x"))) addr = (int)strtol(a + 8, 0, 16);
        else if (!strncmp(line, "# chip=", 7)) in_csv = 1;
        else if (!strncmp(line, "```", 3)) in_csv = 0;
        else if (in_csv && line[0] == 'D' && line[1] >= '0' && line[1] <= '9') {
            char *f[8];
            int nf = 0;
            for (char *t = line; nf < 8; ) {
                f[nf++] = t;
                t = strchr(t, ',');
                if (!t) break;
                *t++ = 0;
            }
            (*entries)++;
            if (nf != 8) { bad++; printf("  malformed spec row %s\n", f[0]); continue; }
            int rcol = atoi(f[2] + 1), rrow = atoi(f[3] + 1), lr = atoi(f[4]), lc = atoi(f[5]);
            int rp = pin_of(f[6]), cp = pin_of(f[7]);
            const mx_chip_cfg_t *c = chip_by_addr((uint8_t)addr);
            int ok = c && lr < c->n_rows && lc < c->n_cols && rp == c->row_pins[lr] && cp == c->col_pins[lc] && c->map[lr * c->n_cols + lc].row == rrow && c->map[lr * c->n_cols + lc].col == rcol;
            if (!ok) { bad++; if (!quiet) printf("  spec/config mismatch at %s (chip 0x%02X)\n", f[0], addr); }
        }
    }
    return bad;
}
static char *slurp(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) return 0;
    char *buf = malloc(1 << 20);
    size_t n = buf ? fread(buf, 1, (1 << 20) - 1, fp) : 0;
    fclose(fp);
    if (buf) buf[n] = 0;
    return buf;
}
static void test_matches_spec(void) {
    char *text = slurp(SPEC_PATH);
    CHECK(text != 0, "cannot read the spec at %s: run `make test` from firmware/firmware or build with -DSPEC_PATH=<path to docs/rev1-spec.md>", SPEC_PATH);
    if (!text) return;
    int entries;
    int bad = check_spec(text, &entries);
    CHECK(bad == 0, "%d spec entries differ from matrix_config.h", bad);
    int cells = 0;
    for (int i = 0; i < MX_NUM_CHIPS; i++)
        for (int k = 0; k < mx_chips[i].n_rows * mx_chips[i].n_cols; k++) cells += mx_chips[i].map[k].row != MX_POS_NONE;
    CHECK(entries > 100 && entries == cells, "config has %d positions, spec CSV has %d: they must match", cells, entries);

    // Negative control: corrupt one spec entry (D81 row pin GPB7 -> GPB6); the checker must notice.
    char *d81 = strstr(text, "D81,PSCRN1|PSCRN2,C14,R0,4,0,GPB7,GPB6");
    CHECK(d81 != 0, "D81 row not found in spec: update this negative control to an existing entry");
    if (d81) {
        char *pin = strstr(d81, "GPB7");
        pin[3] = '6';
        int e2;
        quiet = 1;
        int mutated_bad = check_spec(text, &e2);
        quiet = 0;
        CHECK(mutated_bad >= 1, "mutated spec entry went undetected: the cross-check cannot fail");
    }
    free(text);
}

int main(void) {
    test_validate();
    test_init_registers();
    test_rows_high_z_during_scan();
    test_keys_at_logical_positions();
    test_missing_chip();
    test_chip_dies_midrun();
    test_all_down_no_hang();
    test_matches_spec();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
