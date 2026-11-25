# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# pyre-unsafe

"""Unit tests for the release desensitizer.

Pure Python — exercises each redaction class (abspath, username, ip, mac,
gpu_uuid, email), the allowlists, idempotence, and the fail-loud check/apply
modes. Imports the tool by path from ``scripts/``.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_SPEC = importlib.util.spec_from_file_location(
    "release_desensitizer", _SCRIPTS / "release_desensitizer.py"
)
rd = importlib.util.module_from_spec(_SPEC)
sys.modules["release_desensitizer"] = rd
_SPEC.loader.exec_module(rd)


@pytest.fixture
def rules(tmp_path):
    return rd.Rules.build(tmp_path / "workspace" / "monarch", extra_users=[])


def _redact(line, rules, keep_private=False):
    out, findings = rd.redact_line(line, rules, keep_private)
    return out, [(f[0], f[1], f[2]) for f in findings]


def test_workspace_root_becomes_placeholder(tmp_path):
    root = tmp_path / "workspace" / "monarch"
    rules = rd.Rules.build(root, extra_users=[])
    line = f"repo: {root}/scripts/run\n"
    out, findings = _redact(line, rules)
    assert str(root) not in out
    assert "$MONARCH_ROOT/scripts/run" in out
    assert any(k == "abspath" for k, _, _ in findings)


def test_generic_home_path_redacted(rules):
    out, findings = _redact("path=/data02/home/synthetic.operator/x\n", rules)
    assert "/data02/home/synthetic.operator" not in out
    assert "$HOME/x" in out
    assert any(k == "abspath" for k, _, _ in findings)


def test_home_path_covers_plain_home(rules):
    out, _ = _redact("/home/someone/notes.md\n", rules)
    assert "$HOME/notes.md" in out


def test_username_word_boundary(tmp_path):
    root = tmp_path / "ws"
    rules = rd.Rules.build(root, extra_users=["alice"])
    out, findings = _redact("owner alice ran it; malice untouched\n", rules)
    assert "<user> ran it" in out
    assert "malice untouched" in out
    assert any(k == "username" for k, _, _ in findings)


def test_routable_ip_redacted(rules):
    out, findings = _redact("connect 8.8.8.8:443\n", rules)
    assert "8.8.8.8" not in out
    assert "<ip>:443" in out
    assert any(k == "ip" for k, _, _ in findings)


def test_loopback_kept(rules):
    out, findings = _redact("bind 127.0.0.1:8080\n", rules)
    assert "127.0.0.1" in out
    assert not any(k == "ip" for k, _, _ in findings)


def test_unspecified_ip_kept(rules):
    out, _ = _redact("listen 0.0.0.0\n", rules)
    assert "0.0.0.0" in out


def test_private_ip_redacted_by_default(rules):
    out, findings = _redact("pod 10.244.1.230:26600\n", rules)
    assert "10.244.1.230" not in out
    assert any(k == "ip" for k, _, _ in findings)


def test_private_ip_kept_with_flag(rules):
    out, findings = _redact(
        "pod 192.168.1.5\n", rules, keep_private=True
    )
    assert "192.168.1.5" in out
    assert not any(k == "ip" for k, _, _ in findings)


def test_version_string_not_treated_as_ip(rules):
    out, findings = _redact("torch 2.13.0+cu132\n", rules)
    assert "2.13.0" in out
    assert not any(k == "ip" for k, _, _ in findings)


def test_real_mac_redacted(rules):
    out, findings = _redact("mac 3c:ec:ef:12:34:56\n", rules)
    assert "3c:ec:ef:12:34:56" not in out
    assert "<mac>" in out
    assert any(k == "mac" for k, _, _ in findings)


def test_doc_mac_kept(rules):
    out, findings = _redact("mac 00:00:5e:00:53:01\n", rules)
    assert "00:00:5e:00:53:01" in out
    assert not any(k == "mac" for k, _, _ in findings)


def test_gpu_uuid_redacted(rules):
    out, findings = _redact(
        "GPU-11111111-2222-3333-4444-555555555555\n", rules
    )
    assert "11111111" not in out
    assert "GPU-<uuid>" in out
    assert any(k == "gpu_uuid" for k, _, _ in findings)


def test_gpu_uuid_zero_kept(rules):
    line = "GPU-00000000-0000-0000-0000-000000000000\n"
    out, findings = _redact(line, rules)
    assert line == out
    assert not any(k == "gpu_uuid" for k, _, _ in findings)


def test_personal_email_redacted(rules):
    out, findings = _redact("contact jane.doe@gmail.com\n", rules)
    assert "jane.doe@gmail.com" not in out
    assert "<email>" in out
    assert any(k == "email" for k, _, _ in findings)


@pytest.mark.parametrize(
    "addr",
    [
        "opensource+crates-hyperactor@fb.com",
        "oncall+monarch@xmail.facebook.com",
        "foo@bar.com",
        "noreply@bytedance.com",
        "traecli@bytedance.com",
    ],
)
def test_allowlisted_emails_kept(rules, addr):
    out, findings = _redact(f"author {addr}\n", rules)
    assert addr in out
    assert not any(k == "email" for k, _, _ in findings)


def test_idempotent_apply(tmp_path):
    root = tmp_path / "ws"
    rules = rd.Rules.build(root, extra_users=[])
    line = "path=/data02/home/bob/x 8.8.8.8\n"
    once, _ = rd.redact_line(line, rules, keep_private=False)
    twice, findings = rd.redact_line(once, rules, keep_private=False)
    assert once == twice
    assert findings == []


@pytest.mark.parametrize("name", ["user", "ip", "mac", "email", "uuid", "HOME", "MONARCH_ROOT"])
def test_login_matching_a_placeholder_is_idempotent(tmp_path, name):
    rules = rd.Rules.build(tmp_path / "ws", [name])
    line = f"owner {name}; $HOME $MONARCH_ROOT <user> <ip> <mac> <email> GPU-<uuid>\n"
    once, _ = rd.redact_line(line, rules, keep_private=False)
    assert once == "owner <user>; $HOME $MONARCH_ROOT <user> <ip> <mac> <email> GPU-<uuid>\n"
    twice, findings = rd.redact_line(once, rules, keep_private=False)
    assert once == twice
    assert findings == []


def test_scan_file_apply_rewrites(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("run at /data02/home/bob/monarch on 8.8.8.8\n")
    rules = rd.Rules.build(tmp_path / "monarch", extra_users=[])
    findings = rd.scan_file(f, rules, keep_private=False, apply=True)
    assert findings
    after = f.read_text()
    assert "8.8.8.8" not in after
    assert "/data02/home/bob" not in after
    # Second pass is clean (idempotent).
    again = rd.scan_file(f, rules, keep_private=False, apply=True)
    assert again == []


def test_check_mode_returns_nonzero(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("leak 8.8.8.8\n")
    rc = rd.main(["--root", str(f), "--repo-root", str(tmp_path)])
    assert rc == 1
    # Unmodified in check mode.
    assert "8.8.8.8" in f.read_text()


def test_apply_mode_returns_zero_and_scrubs(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("leak 8.8.8.8\n")
    rc = rd.main(["--root", str(f), "--apply", "--repo-root", str(tmp_path)])
    assert rc == 0
    assert "8.8.8.8" not in f.read_text()


def test_clean_tree_returns_zero(tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("nothing sensitive here, loopback 127.0.0.1 only\n")
    rc = rd.main(["--root", str(f), "--repo-root", str(tmp_path)])
    assert rc == 0


def test_excluded_dirs_skipped(tmp_path):
    venv = tmp_path / "root" / "site-packages"
    venv.mkdir(parents=True)
    (venv / "mod.py").write_text("addr 8.8.8.8\n")
    rc = rd.main(["--root", str(tmp_path / "root"), "--repo-root", str(tmp_path)])
    assert rc == 0  # skipped, nothing found


@pytest.mark.parametrize("prefix", ["/Users", "/data05", "/data05/home", "/home"])
def test_home_families_with_explicit_login(tmp_path, prefix):
    rules = rd.Rules.build(tmp_path / "ws", ["synthetic.operator"])
    out, _ = _redact(f"path={prefix}/synthetic.operator/work\n", rules)
    assert out == "path=$HOME/work\n"


def test_data_directories_are_not_assumed_to_be_homes(rules):
    line = "/data05/datasets/train /data06/models /root/data/results\n"
    out, _ = _redact(line, rules)
    assert out == line


@pytest.mark.parametrize("user", ["root", "monarch", "nobody"])
def test_generic_runtime_login_is_not_a_bare_identifier(tmp_path, monkeypatch, user):
    monkeypatch.setattr(rd.getpass, "getuser", lambda: user)
    rules = rd.Rules.build(tmp_path / "ws", [])
    assert _redact(f"{user} owns this", rules)[0] == f"{user} owns this"
    explicit = rd.Rules.build(tmp_path / "ws", [user])
    assert _redact(f"{user} owns this", explicit)[0] == "<user> owns this"


@pytest.mark.parametrize(
    "addr",
    [
        "synthetic.operator@fb.com",
        "synthetic.operator@meta.com",
        "synthetic.operator@bytedance.com",
        "synthetic.operator@pytorch.org",
        "noreply@personal.invalid",
        "traecli@personal.invalid",
        "opensource+person@personal.invalid",
        "oncall+person@personal.invalid",
    ],
)
def test_corporate_and_prefix_addresses_are_not_blanket_allowlisted(rules, addr):
    out, _ = _redact(addr, rules)
    assert out == "<email>"


@pytest.mark.parametrize("addr", ["user@example.org", "123+bot@users.noreply.github.com"])
def test_documentation_and_github_noreply_addresses_kept(rules, addr):
    out, _ = _redact(addr, rules)
    assert out == addr


def test_check_output_does_not_repeat_secrets(tmp_path, capsys):
    f = tmp_path / "8.8.8.8-synthetic.operator@personal.invalid.txt"
    f.write_text("/Users/synthetic.operator/work 8.8.8.8\n")
    rc = rd.main(["--root", str(f), "--repo-root", str(tmp_path)])
    output = capsys.readouterr().out
    assert rc == 1
    assert "synthetic.operator" not in output
    assert "8.8.8.8" not in output
    assert str(tmp_path) not in output
    assert "fingerprint=" in output
    assert "abspath" in output


def test_harvested_login_scrubbed_across_files(tmp_path):
    (tmp_path / "identity.md").write_text("owner synthetic.operator\n")
    (tmp_path / "path.md").write_text("/Users/synthetic.operator/work\n")
    (tmp_path / "data.md").write_text("/data05/synthetic.operator/work\n")
    assert rd.main(["--root", str(tmp_path), "--apply"]) == 0
    assert (tmp_path / "identity.md").read_text() == "owner <user>\n"
    assert (tmp_path / "data.md").read_text() == "$HOME/work\n"


def test_apply_checks_written_files_again(tmp_path, monkeypatch, capsys):
    f = tmp_path / "note.md"
    f.write_text("8.8.8.8\n")
    calls = []
    scan_file = rd.scan_file

    def unchanged_file(path, rules, keep_private, apply, **kwargs):
        calls.append(apply)
        return scan_file(path, rules, keep_private, apply=False, **kwargs)

    monkeypatch.setattr(rd, "scan_file", unchanged_file)
    assert rd.main(["--root", str(f), "--apply"]) == 1
    assert calls == [True, False]
    assert "verification failed" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("data", "kind"), [(b"image\x00data", "binary"), (b"\xffdata", "non-utf8")]
)
def test_unscanned_files_make_coverage_incomplete(tmp_path, capsys, data, kind):
    f = tmp_path / "asset.bin"
    f.write_bytes(data)
    assert rd.main(["--root", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert kind in output
    assert "incomplete" in output
    assert "clean:" not in output


def test_unreadable_file_reports_coverage_gap(tmp_path, monkeypatch, capsys):
    f = tmp_path / "unreadable.md"
    f.write_text("text\n")
    read_bytes = Path.read_bytes

    def deny_read(path):
        if path == f:
            raise PermissionError("synthetic secret in exception")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deny_read)
    assert rd.main(["--root", str(f)]) == 2
    output = capsys.readouterr().out
    assert "unreadable" in output
    assert "incomplete" in output
    assert "synthetic secret" not in output
