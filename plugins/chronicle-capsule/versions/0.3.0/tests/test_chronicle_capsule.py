from __future__ import annotations

import gzip
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("chronicle_capsule", ROOT / "plugin.py")
assert SPEC and SPEC.loader
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


def test_archive_is_warc_gzip_and_redacted() -> None:
    archive, summary = plugin.build_archive(
        [{"record_id": "1", "source_url": "https://example.test/a", "data": {"token": "x", "title": "A"}}],
        created_at="2026-01-01T00:00:00Z",
    )
    raw = gzip.decompress(archive)
    assert raw.startswith(b"WARC/1.1\r\n")
    assert b"https://example.test/a" in raw
    assert b"[REDACTED]" in raw
    assert b'"token":"x"' not in raw
    assert summary["records"] == 1
    assert len(summary["sha256"]) == 64


def test_invalid_operation_is_noop() -> None:
    assert plugin.handle("source.seed", {}) == {}


def test_target_uri_is_header_safe_and_unicode_encoded() -> None:
    archive, _summary = plugin.build_archive(
        [{"source_url": "https://example.test/中文\r\nInjected: yes", "data": {}}],
        created_at="2026-01-01T00:00:00Z",
    )
    raw = gzip.decompress(archive)
    assert b"%E4%B8%AD%E6%96%87Injected:%20yes" in raw
    assert b"\r\nInjected: yes\r\n" not in raw


def test_export_runs_through_real_capability_broker(tmp_path: Path) -> None:
    from omnicrawler.plugins.plugin_broker import CapabilityBroker, drive_loop
    from omnicrawler.plugins.plugin_sandbox import PluginSubprocessSession

    class State:
        @staticmethod
        def rows(_sql, _params):
            return [
                {
                    "rowid": 1,
                    "record_id": "r1",
                    "source_url": "https://example.test/a",
                    "data_json": '{"title":"A"}',
                }
            ]

    broker = CapabilityBroker(
        permissions={"records:read", "artifacts:write"},
        system_info={},
        state_store=State(),
        run_id="run-1",
        temp_root=tmp_path,
        artifact_root=tmp_path,
    )
    with PluginSubprocessSession(ROOT, "plugin") as session:
        result = drive_loop(session, broker, "exporter.export", {"options": {}}, timeout_seconds=5)
    artifact = Path(broker.committed_artifacts[0]["path"])
    assert artifact.is_file()
    assert gzip.decompress(artifact.read_bytes()).startswith(b"WARC/1.1\r\n")
    assert result["summary"]["records"] == 1
    assert result["summary"]["mode"] == "privacy"
    assert "path" not in result["artifact"]
