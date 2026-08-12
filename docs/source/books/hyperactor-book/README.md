# Hyperactor Documentation Book

This is the development documentation for the hyperactor system, built using [`mdBook`](https://rust-lang.github.io/mdBook/).

```{toctree}
:maxdepth: 2
:caption: Contents

./src/introduction
./src/references/index
./src/mailboxes/index
./src/channels/index
./src/procs/index
./src/actors/index
./src/remote_supervision
./src/macros/index
./src/appendix/index
```

## Running the Book

Build or serve the book through `scripts/run`, the sole Linux-local gateway into
the hermetic bwrap rootfs, which carries the pinned `mdbook`. Run from the repo
root:

```bash
# One-off build (output under book/)
scripts/run mdbook build docs/source/books/hyperactor-book

# Live-reloading server on http://localhost:3000
scripts/run mdbook serve docs/source/books/hyperactor-book
```

Then open http://localhost:3000 in your browser. The server auto-reloads on
edits; stop it with Ctrl+C.

### Notes

- The source is located in src/, with structure defined in SUMMARY.md.
- The book auto-reloads in the browser on edits.

