"""外部配置接线测试：config/publishers.yaml、oa_journals.yaml、热重载。"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


class TestConfigWiring:
    def test_publishers_yaml_loaded(self):
        """publishers.yaml 已装载进运行时表（含 ieee 无 oa_pattern 的显式 null）。"""
        assert plugin_module._PUBLISHERS["mdpi"]["oa_pattern"] == "https://www.mdpi.com/{doi}/pdf"
        assert plugin_module._PUBLISHERS["ieee"].get("oa_pattern") is None
        assert plugin_module._PUBLISHERS["elsevier"]["doi_prefix"] == "10.1016/"

    def test_prefix_map_rebuilt_from_yaml(self):
        assert plugin_module._resolve_publisher("10.3390/abc") == "mdpi"
        assert plugin_module._resolve_publisher("10.1007/abc") == "springer"

    def test_oa_journals_yaml_loaded(self):
        assert "1996-1944" in plugin_module._OA_JOURNALS
        assert "2073-4344" in plugin_module._OA_JOURNALS
        assert "1932-6203" in plugin_module._OA_JOURNALS

    def test_stale_mtime_not_reloaded(self, tmp_path, monkeypatch):
        """mtime 未变化时不重载（热重载幂等）。"""
        cfg = tmp_path / "publishers.yaml"
        cfg.write_text("publishers:\n  mdpi:\n    rate_limit: 9.0\n", encoding="utf-8")
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_CONFIG", cfg)
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_RELOADER",
                            plugin_module._ConfigHotReload(str(cfg)))
        plugin_module._PUBLISHERS["mdpi"]["rate_limit"] = 1.0
        assert plugin_module._reload_publishers_config() is True
        assert plugin_module._PUBLISHERS["mdpi"]["rate_limit"] == 9.0
        res = plugin_module._reload_publishers_config()
        assert res is True  # 未变化，仍返回成功
        assert plugin_module._PUBLISHERS["mdpi"]["rate_limit"] == 9.0

    def test_hot_reload_detects_mtime_change(self, tmp_path, monkeypatch):
        cfg = tmp_path / "publishers.yaml"
        cfg.write_text("publishers:\n  mdpi:\n    rate_limit: 9.0\n", encoding="utf-8")
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_CONFIG", cfg)
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_RELOADER",
                            plugin_module._ConfigHotReload(str(cfg)))
        assert plugin_module._reload_publishers_config() is True
        assert plugin_module._PUBLISHERS["mdpi"]["rate_limit"] == 9.0
        cfg.write_text("publishers:\n  mdpi:\n    rate_limit: 7.0\n", encoding="utf-8")
        future = os.path.getmtime(str(cfg)) + 5
        os.utime(str(cfg), (future, future))
        assert plugin_module._reload_publishers_config() is True
        assert plugin_module._PUBLISHERS["mdpi"]["rate_limit"] == 7.0

    def test_external_yaml_overrides_only_declared_fields(self, tmp_path, monkeypatch):
        """只覆盖 yaml 声明的字段，未声明的保留默认。"""
        cfg = tmp_path / "publishers.yaml"
        cfg.write_text("publishers:\n  mdpi:\n    rate_limit: 5.5\n", encoding="utf-8")
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_CONFIG", cfg)
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_RELOADER",
                            plugin_module._ConfigHotReload(str(cfg)))
        assert plugin_module._reload_publishers_config() is True
        assert plugin_module._PUBLISHERS["mdpi"]["rate_limit"] == 5.5
        assert plugin_module._PUBLISHERS["mdpi"]["home"] == "https://www.mdpi.com"
        assert plugin_module._PUBLISHERS["mdpi"]["oa_pattern"] == "https://www.mdpi.com/{doi}/pdf"
        assert plugin_module._PREFIX_TO_PUBLISHER["10.3390/"] == "mdpi"

    def test_is_known_oa_signals(self):
        assert plugin_module._is_known_oa("mdpi", "", False)
        assert plugin_module._is_known_oa("arxiv", "", False)
        assert plugin_module._is_known_oa("springer", "1996-1944", False)
        assert not plugin_module._is_known_oa("springer", "0000-0000", False)
        assert plugin_module._is_known_oa("ieee", "", True)

    @pytest.fixture
    def seed_tsv(self, tmp_path):
        tsv = tmp_path / "wos.tsv"
        tsv.write_text(
            "Article Title\tAuthor Full Names\tPublication Year\tDOI\tISSN\n"
            "Glass Materials\tZhang, San\t2023\t10.3390/ma16010001\t1996-1944\n"
            "IEEE Paper\tLi, Si\t2022\t10.1109/abc.2022.1\t0000-0000\n",
            encoding="utf-8")
        return tsv

    def test_seed_uses_oa_issn_whitelist(self, tmp_path, seed_tsv):
        res = plugin_module._seed({"file_path": str(seed_tsv), "workspace": str(tmp_path),
                                   "config": {"level": 1, "incremental": False}})
        by_doi = {r["meta"]["paper"]["doi"]: r["meta"]["paper"] for r in res["requests"]}
        assert by_doi["10.3390/ma16010001"]["is_oa"] is True
        assert by_doi["10.1109/abc.2022.1"]["is_oa"] is False