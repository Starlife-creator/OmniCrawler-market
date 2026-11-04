"""v0.3.3 交互式代理补填 + 失败重试流程测试。

覆盖：开关关闭/跳过/EOF 静默回退/填代理后重试合并/显式结果直出报告。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module

FAILED_SEED = [
    {"doi": "10.1002/needs_proxy", "title": "Needs Proxy", "layer": "none",
     "error_class": "auth_required", "reason": "需要订阅权限", "time": 1000.0},
]
RESULTS_SEED = [{"doi": "10.3390/ok", "title": "Ok", "verified": True, "local_path": "papers/ok.pdf"}]


class TestPromptProxyAndRetry:
    def test_disabled_by_default_no_interaction(self):
        results, failed, retried = plugin_module._prompt_proxy_and_retry(
            {}, Path("."), list(RESULTS_SEED), list(FAILED_SEED))
        assert retried == 0
        assert len(results) == 1 and len(failed) == 1

    def test_blank_input_means_explicit_skip(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *a: "")
        results, failed, retried = plugin_module._prompt_proxy_and_retry(
            {"retry_prompt_proxy": True}, Path("."), list(RESULTS_SEED), list(FAILED_SEED))
        assert retried == 0
        assert len(failed) == 1

    def test_eof_silently_skips(self, monkeypatch):
        def _boom(*a):
            raise EOFError
        monkeypatch.setattr("builtins.input", _boom)
        results, failed, retried = plugin_module._prompt_proxy_and_retry(
            {"retry_prompt_proxy": True}, Path("."), list(RESULTS_SEED), list(FAILED_SEED))
        assert retried == 0
        assert len(failed) == 1

    def test_already_configured_proxy_skips_prompt(self, monkeypatch):
        def _fail(*a):
            raise AssertionError("不应触发交互：代理已配置")
        monkeypatch.setattr("builtins.input", _fail)
        config = {"retry_prompt_proxy": True,
                  "institution": {"proxy_url": "http://proxy.example.com"}}
        results, failed, retried = plugin_module._prompt_proxy_and_retry(
            config, Path("."), list(RESULTS_SEED), list(FAILED_SEED))
        assert retried == 0

    def test_filled_proxy_retries_and_merges(self, tmp_path, monkeypatch):
        answers = iter(["http://proxy.lib.test:8080", "https://login.lib.test"])
        monkeypatch.setattr("builtins.input", lambda *a: next(answers))
        seen_configs = []

        def fake_process(payload):
            seen_configs.append(payload["config"])
            doi = payload["paper"]["doi"]
            if doi == "10.1002/needs_proxy":
                return {"records": [{"doi": doi, "title": "Needs Proxy", "verified": True,
                                     "local_path": "papers/np.pdf"}], "errors": []}
            return {"records": [], "errors": [{"doi": doi, "title": "Still Down",
                    "reason": "all_layers_failed", "last_layer": "institutional_http",
                    "error_class": "network", "error_reason": "网络不可达或请求超时"}]}

        monkeypatch.setattr(plugin_module, "_process", fake_process)
        failed = FAILED_SEED + [{"doi": "10.9999/still_down", "title": "Still Down",
                                 "layer": "none", "error_class": "network",
                                 "reason": "网络不可达", "time": 1001.0}]
        results, failed2, retried = plugin_module._prompt_proxy_and_retry(
            {"retry_prompt_proxy": True}, tmp_path, list(RESULTS_SEED), failed)

        assert retried == 1
        assert {r["doi"] for r in results} == {"10.3390/ok", "10.1002/needs_proxy"}
        # 重试成功者从失败列表剔除；仍失败者用最新 error_class 覆盖
        assert [f["doi"] for f in failed2] == ["10.9999/still_down"]
        assert failed2[0]["error_class"] == "network"
        # 传给 _process 的配置带上了用户填写的代理
        assert seen_configs and all(
            c["institution"]["proxy_url"] == "http://proxy.lib.test:8080" for c in seen_configs)
        assert seen_configs[0]["institution"]["login_url"] == "https://login.lib.test"


class TestAfterRunExplicitResults:
    def test_explicit_results_generate_report_directly(self, tmp_path):
        res = plugin_module._after_run({
            "workspace": str(tmp_path),
            "config": {},  # 未开 retry_prompt_proxy → 不交互，直接出报告
            "results": RESULTS_SEED,
            "failed": FAILED_SEED,
        })
        assert res["report_generated"] is True
        assert res["success_count"] == 1
        assert res["failed_count"] == 1
        assert res["proxy_retried"] == 0
        assert list((tmp_path / "reports").glob("download_report_*.csv"))
        assert list((tmp_path / "reports").glob("dashboard_*.html"))

    def test_report_message_uses_classified_reason(self, tmp_path):
        plugin_module._after_run({
            "workspace": str(tmp_path), "config": {"defer_headed": False},  # 隔离：只验报告格式
            "results": [], "failed": FAILED_SEED,
        })
        csv_text = next((tmp_path / "reports").glob("download_report_*.csv")).read_text(encoding="utf-8-sig")
        assert "auth_required@none: 需要订阅权限" in csv_text
