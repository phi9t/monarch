# Hyperactor-mesh Book

This is the development documentation for hyperactor-mesh, built using [`mdBook`](https://rust-lang.github.io/mdBook/).

## Running the Book

Build or serve the book through `scripts/run`, the sole Linux-local gateway into
the hermetic bwrap rootfs, which carries the pinned `mdbook`. Run from the repo
root:

```bash
# One-off build (output under book/)
scripts/run mdbook build docs/source/books/hyperactor-mesh-book

# Live-reloading server on http://localhost:3001
scripts/run mdbook serve docs/source/books/hyperactor-mesh-book --port 3001
```

Open http://localhost:3001 in your browser.

### Notes

- The source is located in src/, with structure defined in SUMMARY.md.
- The book will auto-reload in the browser on edits.
