# Honor CARGO_TARGET_DIR (absolute or workspace-relative) so a rootfs-overridden
# target tree is respected; default to the workspace target dir.
TARGET_DIR ?= $(if $(CARGO_TARGET_DIR),$(CARGO_TARGET_DIR),../target)
LIB     = $(TARGET_DIR)/debug/libmonarch_mini.a
INCLUDE = .
OUT     = $(TARGET_DIR)/debug/hello

# Shared execution-contract guard. Every target that compiles or runs native
# code funnels through it, so the Makefile refuses to work outside a controlled
# execution domain.
GUARD = ../../scripts/rootfs/execution_contract.sh require-controlled

.PHONY: all run clean cargo

all: $(OUT)

# Always invoke cargo — it tracks Rust source changes itself.
cargo:
	$(GUARD)
	cargo build -p monarch_mini

$(OUT): examples/hello.c cargo
	$(GUARD)
	cc examples/hello.c $(LIB) -I$(INCLUDE) -o $(OUT)

run: $(OUT)
	$(GUARD)
	$(OUT)

clean:
	$(GUARD)
	rm -f $(OUT)
