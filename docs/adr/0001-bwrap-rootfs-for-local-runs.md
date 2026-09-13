# Use the bwrap rootfs for local runs

Monarch local runs use the Hermetic Rootfs as the canonical execution envelope
because host toolchains can target a different loader and glibc than the system
loader that Rust and Python extension builds actually use. This trades host
convenience for reproducible control-plane and tensor-engine validation, and it
keeps local run failures tied to Monarch behavior instead of Nix/glibc/compiler
drift.
