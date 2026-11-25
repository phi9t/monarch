# Frontend Dependency Locks

This frontend has two locked dependency install paths, one per execution domain:

- **Local rootfs (OSS):** the deterministic frontend build inside the bwrap
  rootfs installs with `npm ci` from `package-lock.json`. This is the path
  `scripts/run uv pip install -e .` drives when it builds the frontend as
  package data.
- **Buck (Meta-internal):** Buck builds install with Yarn from `yarn.lock`. This
  lockfile is owned by the Buck build; do not edit it in an OSS checkout.

Keep both lockfiles in sync when changing `package.json`, and verify they resolve
the same versions with the parity check in `README.fb`. Do not delete either
lockfile until every supported build path uses the same package manager.
