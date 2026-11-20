# Host test: `make test` (needs only a C compiler; override with CC=clang).
# `make mutants` is the negative control: it builds copies of the module with a
# deliberately wrong register address or row/col index swap, and succeeds only
# if the test FAILS on every one.
CC ?= cc
CFLAGS = -std=c11 -Wall -Wextra -Werror -O1
BUILD = build

test: $(BUILD)/test_matrix
	./$(BUILD)/test_matrix

$(BUILD)/test_matrix: test_matrix.c mcp23018_matrix.c mcp23018_matrix.h matrix_config.h
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -I. test_matrix.c mcp23018_matrix.c -o $@

mutants:
	@mkdir -p $(BUILD)
	@set -e; for m in gppu_reg gpio_reg iodir_reg rowcol_swap; do \
	  case $$m in \
	    gppu_reg) hdr=1; e='s/MX_REG_GPPUA  = 0x0C/MX_REG_GPPUA  = 0x0E/';; \
	    gpio_reg) hdr=1; e='s/MX_REG_GPIOA  = 0x12/MX_REG_GPIOA  = 0x13/';; \
	    iodir_reg) hdr=1; e='s/MX_REG_IODIRA = 0x00/MX_REG_IODIRA = 0x01/';; \
	    rowcol_swap) hdr=0; e='s/c->map\[r \* c->n_cols + k\]/c->map[k * c->n_rows + r]/';; \
	  esac; \
	  mkdir -p $(BUILD)/$$m; cp mcp23018_matrix.h mcp23018_matrix.c matrix_config.h test_matrix.c $(BUILD)/$$m/; \
	  if [ $$hdr = 1 ]; then sed -i.bak "$$e" $(BUILD)/$$m/mcp23018_matrix.h; else sed -i.bak "$$e" $(BUILD)/$$m/mcp23018_matrix.c; fi; \
	  if cmp -s $(BUILD)/$$m/mcp23018_matrix.h mcp23018_matrix.h && cmp -s $(BUILD)/$$m/mcp23018_matrix.c mcp23018_matrix.c; then echo "mutant $$m: sed did not change the source"; exit 2; fi; \
	  $(CC) $(CFLAGS) -I$(BUILD)/$$m $(BUILD)/$$m/test_matrix.c $(BUILD)/$$m/mcp23018_matrix.c -o $(BUILD)/$$m/t; \
	  if $(BUILD)/$$m/t > $(BUILD)/$$m/log 2>&1; then echo "mutant $$m: SURVIVED (test passed, bad)"; exit 1; else echo "mutant $$m: killed (test failed as it should)"; fi; \
	done

clean:
	rm -rf $(BUILD)

.PHONY: test mutants clean
