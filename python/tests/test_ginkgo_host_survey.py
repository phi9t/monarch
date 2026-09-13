from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SURVEY_PATH = REPO_ROOT / "scripts" / "ginkgo_host_survey.py"

spec = importlib.util.spec_from_file_location("ginkgo_host_survey", SURVEY_PATH)
assert spec is not None
assert spec.loader is not None
ginkgo_host_survey = importlib.util.module_from_spec(spec)
sys.modules["ginkgo_host_survey"] = ginkgo_host_survey
spec.loader.exec_module(ginkgo_host_survey)


def test_survey_candidate_path_records_storage_and_executable_bit(tmp_path: Path) -> None:
    candidate = tmp_path / "cache"
    report = ginkgo_host_survey.survey_candidate_path(candidate)

    assert report["path"] == str(candidate)
    assert report["exists"] is True
    assert report["is_writable"] is True
    assert report["executable_bit_supported"] is True
    assert report["free_bytes"] > 0
    assert report["free_inodes"] >= 0


def test_build_host_survey_records_required_sections(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        ginkgo_host_survey.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"bwrap", "nvidia-smi"} else None,
    )
    monkeypatch.setattr(ginkgo_host_survey, "detect_nvidia_devices", lambda: ["/dev/nvidia0", "/dev/nvidiactl"])
    monkeypatch.setattr(
        ginkgo_host_survey,
        "run_command",
        lambda command: "535.104.05"
        if command[0].endswith("nvidia-smi")
        and command[1:] == ["--query-gpu=driver_version", "--format=csv,noheader"]
        else "",
    )

    report = ginkgo_host_survey.build_host_survey(
        repo_root=tmp_path / "repo",
        rootfs_root=tmp_path / "rootfs",
        cache_root=tmp_path / "cache",
        temp_root=tmp_path / "tmp",
        run_root=tmp_path / "run",
        results_root=tmp_path / "results",
        shm_root=tmp_path / "shm",
        ports=[19000, 19001],
    )

    assert report["schema_version"] == 1
    assert set(report["paths"]) == {"repo", "rootfs", "cache", "temp", "run", "results", "shared_memory"}
    assert report["tools"]["bwrap"]["path"] == "/usr/bin/bwrap"
    assert report["gpu"]["nvidia_devices"] == ["/dev/nvidia0", "/dev/nvidiactl"]
    assert report["gpu"]["driver_version"] == "535.104.05"
    assert report["ports"]["checked"] == [19000, 19001]
    assert all(item["available"] for item in report["ports"]["results"])


def test_cli_writes_json_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ginkgo_host_survey.shutil, "which", lambda name: None)
    monkeypatch.setattr(ginkgo_host_survey, "detect_nvidia_devices", lambda: [])
    monkeypatch.setattr(ginkgo_host_survey, "run_command", lambda command: "")
    output = tmp_path / "survey.json"

    rc = ginkgo_host_survey.main(
        [
            "--repo-root",
            str(tmp_path / "repo"),
            "--rootfs-root",
            str(tmp_path / "rootfs"),
            "--cache-root",
            str(tmp_path / "cache"),
            "--temp-root",
            str(tmp_path / "tmp"),
            "--run-root",
            str(tmp_path / "run"),
            "--results-root",
            str(tmp_path / "results"),
            "--shm-root",
            str(tmp_path / "shm"),
            "--port",
            "19000",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text())
    assert rc == 0
    assert payload["ports"]["checked"] == [19000]
    assert payload["tools"]["bwrap"]["path"] is None
