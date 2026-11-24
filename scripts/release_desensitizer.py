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
  ``/data*/home/<user>`` or ``/Users/<user>`` prefix becomes ``$HOME``.
  ``/dataN/<user>`` is recognized for explicit or harvested login names.
* **username** — the current login name (and any name harvested from a home
  path) becomes ``<user>``.
* **ip** — IPv4 becomes ``<ip>``, except loopback, unspecified, and broadcast
  addresses. ``--keep-private`` also retains RFC1918 addresses.
* **mac** — hardware MAC addresses become ``<mac>``. The IANA documentation
  ranges (``00:00:5e:...``, all-zero, broadcast) are left alone.
* **gpu_uuid** — ``GPU-<uuid>`` serials become ``GPU-<uuid>`` placeholder,
  except the all-zero simulator UUID.
* **email** — addresses become ``<email>``, except an allowlist of public
  project aliases, documentation domains, and known bot/noreply addresses.

The tool is dry-run by default: it reports counts and a bounded sample of
fingerprints, never original values. Exit 1 means findings remain; exit 2 means
coverage is incomplete (binary, non-UTF8, unreadable, or unwritable files).
``--apply`` rewrites in place and verifies a second pass. ``--check`` never
mutates. Excluded directories (vendored venvs, caches, ``.git``) are outside the
scan's scope. This is a text-artifact check, not a full repository privacy audit.

Run through the gateway: ``scripts/run python scripts/release_desensitizer.py
--root .scratch/production-release-readiness``.
"""

import argparse
import getpass
import hashlib
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

# Public documentation domains and explicit project/bot addresses only.
_EMAIL_ALLOW_SUFFIXES = (
    "@example.com",
    "@example.org",
    "@example.net",
    "@users.noreply.github.com",
)
_EMAIL_ALLOW_EXACT = frozenset(
    {
        "foo@bar.com",
        "opensource+crates-hyperactor@fb.com",
        "oncall+monarch@xmail.facebook.com",
        "noreply@bytedance.com",
        "traecli@bytedance.com",
        "noreply@github.com",
    }
)

_GENERIC_USERS = frozenset({"root", "monarch", "nobody"})
_RE_HOME = re.compile(r"/(?:data\d+/home|home|Users)/(?P<user>[A-Za-z0-9._-]+)")

# IPv4 kept as-is: loopback, unspecified, and broadcast.
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
        names = set(extra_users)
        if user not in _GENERIC_USERS:
            names.add(user)
        names.discard("")

        # Most specific first.
        rules.literal_map.append(
            (
                re.compile(re.escape(str(repo_root)) + r"(?![A-Za-z0-9._-])"),
                "$MONARCH_ROOT",
                "abspath",
            )
        )
        rules.literal_map.append(
            (
                re.compile(re.escape(home) + r"(?![A-Za-z0-9._-])"),
                "$HOME",
                "abspath",
            )
        )
        rules.literal_map.append(
            (
                _RE_HOME,
                "$HOME",
                "abspath",
            )
        )
        for name in sorted(names, key=lambda name: (-len(name), name)):
            rules.literal_map.append(
                (
                    re.compile(rf"/data\d+/{re.escape(name)}(?![A-Za-z0-9._-])"),
                    "$HOME",
                    "abspath",
                )
            )
        for name in sorted(names, key=lambda name: (-len(name), name)):
            # Generated tokens must survive a second pass, even for these logins.
            left = r"(?<![A-Za-z0-9._-])"
            if name in {"user", "email", "ip", "mac", "uuid"}:
                left = r"(?<![A-Za-z0-9._<-])"
            elif name in {"HOME", "MONARCH_ROOT"}:
                left = r"(?<![A-Za-z0-9._$-])"
            rules.literal_map.append(
                (
                    re.compile(left + re.escape(name) + r"(?![A-Za-z0-9._-])"),
                    "<user>",
                    "username",
                )
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


def _read_text(path: Path, coverage: list | None = None) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        kind = "unreadable"
    else:
        if b"\x00" in data:
            kind = "binary"
        else:
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                kind = "non-utf8"
    if coverage is not None:
        coverage.append((path, kind))
    return None


def scan_file(
    path: Path,
    rules: Rules,
    keep_private: bool,
    apply: bool,
    coverage: list | None = None,
) -> list:
    """Scan one UTF-8 file, optionally rewriting and collecting coverage gaps."""
    findings = []
    text = _read_text(path, coverage)
    if text is None:
        return findings

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
        try:
            path.write_text("".join(new_lines), encoding="utf-8")
        except OSError:
            if coverage is not None:
                coverage.append((path, "unwritable"))
            else:
                raise

    return findings


def iter_target_files(root: Path, coverage: list | None = None):
    """Yield files within scope, recording directories that cannot be listed."""
    def onerror(error):
        if coverage is not None:
            coverage.append((Path(error.filename), "unreadable-directory"))

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
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
            yield p


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _location(path: Path, root: Path, rules: Rules) -> str:
    relative = path.name if root.is_file() else str(path.relative_to(root))
    return repr(redact_line(relative, rules, keep_private=False)[0])


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

    root = args.root.resolve()
    if not root.exists():
        print("error: scan root does not exist", file=sys.stderr)
        return 2

    coverage = []
    targets = [root] if root.is_file() else list(iter_target_files(root, coverage))
    users = set(args.extra_user)
    # Harvest first so a login on an earlier line or in another file is covered.
    for path in targets:
        text = _read_text(path)
        if text is not None:
            users.update(
                match["user"]
                for match in _RE_HOME.finditer(text)
                if match["user"] not in _GENERIC_USERS | {".", ".."}
            )
    rules = Rules.build(repo_root, list(users))

    all_findings = []
    for path in targets:
        all_findings.extend(
            scan_file(
                path, rules, args.keep_private, apply=args.apply, coverage=coverage
            )
        )

    print("scope: UTF-8 text files; VCS, dependency, and cache directories excluded")

    by_kind = {}
    for f in all_findings:
        by_kind.setdefault(f.kind, 0)
        by_kind[f.kind] += 1

    action = "matched for redaction" if args.apply else "found"
    print(f"{action} {len(all_findings)} sensitive identifier(s):")
    for kind in sorted(by_kind):
        print(f"  {kind}: {by_kind[kind]}")

    # Show a bounded sample so gate logs stay readable.
    if all_findings:
        print("\nsample:")
    seen = 0
    for f in all_findings:
        if seen >= 40:
            print(f"  ... and {len(all_findings) - seen} more")
            break
        location = _location(f.path, root, rules)
        print(f"  {location}:{f.line}: {f.kind}: fingerprint={_fingerprint(f.original)}")
        seen += 1

    if args.apply:
        remaining = []
        verified_targets = (
            [root] if root.is_file() else list(iter_target_files(root, coverage))
        )
        for path in verified_targets:
            remaining.extend(
                scan_file(
                    path, rules, args.keep_private, apply=False, coverage=coverage
                )
            )
        if remaining:
            print(f"verification failed: {len(remaining)} sensitive identifier(s) remain")
        else:
            print("verification: no sensitive identifiers remain in scanned text")
    else:
        remaining = all_findings

    if coverage:
        gaps = sorted(set(coverage), key=lambda gap: (str(gap[0]), gap[1]))
        print(f"coverage incomplete: {len(gaps)} file/directory gap(s)")
        for path, kind in gaps[:40]:
            print(f"  {_location(path, root, rules)}: {kind}")
        return 2

    if remaining:
        return 1
    print("clean: no sensitive identifiers found in scanned text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
