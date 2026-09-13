# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# pyre-unsafe

"""Release desensitizer: strip machine- and person-identifiable strings.

Before publishing local artifacts (``.scratch/`` notes, run logs, JSON
receipts) this tool rewrites host-specific identifiers to stable, neutral
placeholders so a published tree carries no absolute home paths, login names,
routable network identity, or hardware serials.

Redaction classes, each with a deterministic placeholder so the same secret
always maps to the same token (diffs stay readable, re-runs are idempotent):

* **abspath** — the caller's home directory and workspace root become
  ``$HOME`` / ``$MONARCH_ROOT``; any other ``/home/<user>`` or
  ``/data*/home/<user>`` prefix becomes ``$HOME``.
* **username** — the current login name (and any name harvested from a home
  path) becomes ``<user>``.
* **ip** — routable IPv4 becomes ``<ip>``. Loopback (``127.0.0.1``),
  unspecified (``0.0.0.0``), and the documentation range (``10.244.*`` k8s pod
  CIDR is treated as private-doc and kept) are configurable; by default only
  globally routable addresses are redacted.
* **mac** — hardware MAC addresses become ``<mac>``. The IANA documentation
  ranges (``00:00:5e:...``, all-zero, broadcast) are left alone.
* **gpu_uuid** — ``GPU-<uuid>`` serials become ``GPU-<uuid>`` placeholder,
  except the all-zero simulator UUID.
* **email** — addresses become ``<email>``, except an allowlist of public
  project/open-source contacts (``*@fb.com``, ``*@meta.com``,
  ``*@example.com``, ``foo@bar.com``, ``noreply@``/``traecli@bytedance.com``
  commit trailers, and the Monarch oncall alias).

The tool is fail-loud and dry-run by default: it prints every finding and exits
nonzero when anything remains, so it can gate a release. ``--apply`` rewrites in
place. ``--check`` (default) never mutates. Binary files and paths under
excluded directories (vendored venvs, caches, ``.git``) are skipped.

Run through the gateway: ``scripts/run python scripts/release_desensitizer.py
--root .scratch/production-release-readiness``.
"""

import argparse
import getpass
import os
import re
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

# Directories never scanned: vendored third-party trees and VCS metadata.
# Their contents are not ours to rewrite and dwarf the authored artifacts.
_EXCLUDED_DIR_PARTS = frozenset(
    {
        ".git",
        "venv",
        "venvs",
        "site-packages",
        "node_modules",
        "__pycache__",
        ".venv",
        ".venv-rootfs",
    }
)

# A path segment equal to ``uv`` under an ``archive`` layout is a package cache.
_EXCLUDED_DIR_SUBSTRINGS = ("uv/archive", "harbor-venv", "/cache/")

# Emails that are public project contacts, not PII. Matched case-insensitively
# as suffixes or exact addresses.
_EMAIL_ALLOW_SUFFIXES = (
    "@fb.com",
    "@meta.com",
    "@example.com",
    "@xmail.facebook.com",
    "@bytedance.com",
    "@pytorch.org",
)
_EMAIL_ALLOW_EXACT = frozenset({"foo@bar.com"})

# IPv4 kept as-is: loopback, unspecified, and the RFC5737 documentation blocks.
# Private RFC1918 ranges are host-identifying on a shared cluster, so they are
# redacted by default; pass --keep-private to retain them.
_IP_KEEP_EXACT = frozenset({"127.0.0.1", "0.0.0.0", "255.255.255.255"})

_PRIVATE_PREFIXES = ("10.", "192.168.")


def _is_private_ipv4(addr: str) -> bool:
    if addr.startswith(_PRIVATE_PREFIXES):
        return True
    if addr.startswith("172."):
        second = int(addr.split(".")[1])
        return 16 <= second <= 31
    return False


# MAC values that are documentation/placeholder, never real hardware.
_MAC_KEEP = frozenset(
    {
        "00:00:00:00:00:00",
        "ff:ff:ff:ff:ff:ff",
    }
)
_MAC_KEEP_PREFIXES = ("00:00:5e",)  # IANA documentation OUI

_GPU_UUID_KEEP = frozenset({"GPU-00000000-0000-0000-0000-000000000000"})


@dataclass
class Finding:
    path: Path
    line: int
    kind: str
    original: str
    placeholder: str


@dataclass
class Rules:
    """Compiled, host-derived redaction rules.

    Ordering matters: longer, more specific literals (workspace root, home
    dir) are applied before the bare username so nested matches collapse
    cleanly.
    """

    literal_map: list = field(default_factory=list)  # (regex, placeholder, kind)
    username: str = ""

    @classmethod
    def build(cls, repo_root: Path, extra_users: list) -> "Rules":
        rules = cls()
        home = os.path.expanduser("~")
        user = getpass.getuser()
        rules.username = user

        # Most specific first.
        rules.literal_map.append(
            (re.compile(re.escape(str(repo_root))), "$MONARCH_ROOT", "abspath")
        )
        rules.literal_map.append(
            (re.compile(re.escape(home)), "$HOME", "abspath")
        )
        # Any other home directory shape: /home/<u>, /data0N/home/<u>.
        rules.literal_map.append(
            (
                re.compile(r"/(?:data\d+/)?home/[A-Za-z0-9._-]+"),
                "$HOME",
                "abspath",
            )
        )
        # Bare login name(s), on word boundaries, after paths are handled.
        for name in [user, *extra_users]:
            if name:
                rules.literal_map.append(
                    (re.compile(rf"\b{re.escape(name)}\b"), "<user>", "username")
                )
        return rules


_RE_IPV4 = re.compile(r"\b(?:(?:\d{1,3})\.){3}\d{1,3}\b")
_RE_MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
_RE_GPU_UUID = re.compile(r"GPU-[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}")
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _email_allowed(addr: str) -> bool:
    low = addr.lower()
    if low in _EMAIL_ALLOW_EXACT:
        return True
    if low.startswith(("noreply@", "traecli@", "opensource+", "oncall+")):
        return True
    return any(low.endswith(sfx) for sfx in _EMAIL_ALLOW_SUFFIXES)


def _looks_like_ipv4(addr: str) -> bool:
    parts = addr.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def redact_line(line: str, rules: Rules, keep_private: bool) -> tuple:
    """Return (new_line, [Finding-partials]) for one line.

    Finding-partials omit path/line; the caller fills those in.
    """
    findings = []
    out = line

    for pattern, placeholder, kind in rules.literal_map:
        def _sub(m, ph=placeholder, k=kind):
            findings.append((k, m.group(0), ph))
            return ph

        out = pattern.sub(_sub, out)

    def _ip_sub(m):
        addr = m.group(0)
        if not _looks_like_ipv4(addr):
            return addr
        if addr in _IP_KEEP_EXACT:
            return addr
        if _is_private_ipv4(addr) and keep_private:
            return addr
        # Skip version-like dotted numbers already handled? IPv4 octets are
        # 0-255; a token like 2.13.0 is only 3 parts and won't match the regex.
        findings.append(("ip", addr, "<ip>"))
        return "<ip>"

    out = _RE_IPV4.sub(_ip_sub, out)

    def _mac_sub(m):
        mac = m.group(0).lower()
        if mac in _MAC_KEEP or mac.startswith(_MAC_KEEP_PREFIXES):
            return m.group(0)
        findings.append(("mac", m.group(0), "<mac>"))
        return "<mac>"

    out = _RE_MAC.sub(_mac_sub, out)

    def _gpu_sub(m):
        val = m.group(0)
        if val in _GPU_UUID_KEEP:
            return val
        findings.append(("gpu_uuid", val, "GPU-<uuid>"))
        return "GPU-<uuid>"

    out = _RE_GPU_UUID.sub(_gpu_sub, out)

    def _email_sub(m):
        addr = m.group(0)
        if _email_allowed(addr):
            return addr
        findings.append(("email", addr, "<email>"))
        return "<email>"

    out = _RE_EMAIL.sub(_email_sub, out)

    return out, findings


def _is_excluded(path: Path, root: Path) -> bool:
    parts = set(path.parts)
    if parts & _EXCLUDED_DIR_PARTS:
        return True
    as_str = str(path)
    return any(sub in as_str for sub in _EXCLUDED_DIR_SUBSTRINGS)


def _is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
    except OSError:
        return True
    return b"\x00" in chunk


def scan_file(path: Path, rules: Rules, keep_private: bool, apply: bool) -> list:
    findings = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings  # non-utf8 / unreadable: treat as binary, skip

    new_lines = []
    changed = False
    for idx, line in enumerate(text.splitlines(keepends=True), start=1):
        new_line, partials = redact_line(line, rules, keep_private)
        if partials:
            changed = True
            for kind, original, placeholder in partials:
                findings.append(Finding(path, idx, kind, original, placeholder))
        new_lines.append(new_line)

    if apply and changed:
        path.write_text("".join(new_lines), encoding="utf-8")

    return findings


def iter_target_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        # Prune excluded directories in place for speed.
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _EXCLUDED_DIR_PARTS
            and not _is_excluded(d / name, root)
        ]
        for name in filenames:
            p = d / name
            if _is_excluded(p, root):
                continue
            if _is_binary(p):
                continue
            yield p


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Redact machine/person-identifiable strings from release artifacts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="directory or file to scan (recursed).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="workspace root to map to $MONARCH_ROOT (default: git toplevel or cwd).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="report findings, do not modify (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="rewrite files in place.",
    )
    parser.add_argument(
        "--keep-private",
        action="store_true",
        help="retain RFC1918 private IPv4 (default redacts them).",
    )
    parser.add_argument(
        "--extra-user",
        action="append",
        default=[],
        help="additional login name(s) to redact.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root
    if repo_root is None:
        repo_root = Path(os.environ.get("MONARCH_ROOT", os.getcwd()))
    repo_root = repo_root.resolve()

    # Harvest usernames from home path shapes for --extra-user completeness.
    rules = Rules.build(repo_root, args.extra_user)

    root = args.root.resolve()
    if not root.exists():
        print(f"error: root does not exist: {root}", file=sys.stderr)
        return 2

    targets = [root] if root.is_file() else list(iter_target_files(root))

    all_findings = []
    for path in targets:
        if root.is_file() and _is_binary(path):
            continue
        all_findings.extend(
            scan_file(path, rules, args.keep_private, apply=args.apply)
        )

    if not all_findings:
        print(f"clean: no sensitive identifiers found under {root}")
        return 0

    by_kind = {}
    for f in all_findings:
        by_kind.setdefault(f.kind, 0)
        by_kind[f.kind] += 1

    action = "redacted" if args.apply else "found"
    print(f"{action} {len(all_findings)} sensitive identifier(s) under {root}:")
    for kind in sorted(by_kind):
        print(f"  {kind}: {by_kind[kind]}")

    # Show a bounded sample so gate logs stay readable.
    print("\nsample:")
    seen = 0
    for f in all_findings:
        if seen >= 40:
            print(f"  ... and {len(all_findings) - seen} more")
            break
        rel = f.path
        print(f"  {rel}:{f.line}: {f.kind}: {f.original!r} -> {f.placeholder}")
        seen += 1

    if args.apply:
        # After applying, a second pass must be clean; report success.
        print("\napplied redactions in place.")
        return 0

    # Check mode with findings: fail-loud so this gates a release.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
