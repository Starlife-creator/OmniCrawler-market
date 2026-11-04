"""Academic Paper Downloader: 三层降级批量下载学术论文 PDF.

完整优化版：并发下载、OpenAlex批量预检、批量报告、增量导入、
多格式输入、智能重试、下载后重命名、代理健康检查、登录态监控、
分布式锁、配置热重载、实时进度看板。

完全自包含：仅使用相对路径，所有文件操作限定在插件工作区内。
"""

from __future__ import annotations

import csv
import codecs
import hashlib
import html
import io
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Iterator
from download_evidence import normalize_doi, public_source_url, file_digest, build_evidence

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    yaml = None
    _HAS_YAML = False

try:
    import xlrd
    _HAS_XLRD = True
except ImportError:
    xlrd = None
    _HAS_XLRD = False

# ---------------------------------------------------------------------------
# 宿主 SDK 适配（v0.9.0）：所有网络经 EgressBroker，PDF 经 artifact.stream 交付
# ---------------------------------------------------------------------------
import base64 as _base64


def _sdk_call(operation: str, payload: dict) -> dict | None:
    """调用宿主 SDK；SDK 缺席（独立运行）或失败 → None。"""
    try:
        import omnicrawler_sdk
        result = omnicrawler_sdk.call(operation, payload)
        return result if isinstance(result, dict) else None
    except Exception:
        return None


class _SdkUnavailable(Exception):
    """宿主 SDK 不可用（独立运行/未授予能力）：调用方按降级处理，不直连网络。"""


class _HostNetworkError(Exception):
    """宿主 network.fetch 返回错误或调用失败。"""

    def __init__(self, status: int | None, message: str = "") -> None:
        self.status = status
        super().__init__(message or f"http_{status}")


def _host_fetch(url: str, headers: dict | None = None) -> tuple[bytes, int, str]:
    """经宿主 EgressBroker 抓取 URL，返回 (body, status, final_url)。

    遵守 ScopePolicy / robots / 配额；插件进程不经手凭据。
    失败或 SDK 缺席抛异常——调用方负责分类，绝不回退到直连。
    """
    result = _sdk_call("network.fetch", {"url": url, "method": "GET", "headers": headers or {}})
    if result is None:
        raise _SdkUnavailable("宿主 SDK 不可用，network.fetch 未执行（拒绝直连降级）")
    status = int(result.get("status", 0))
    body = _base64.b64decode(result.get("body_b64", ""))
    return body, status, str(result.get("url", url))


def _host_save_pdf(filename: str, data: bytes, maximum_bytes: int) -> dict | None:
    """经宿主 artifact.stream 保存 PDF；成功返回宿主工件信息，失败返回 None。

    超过宿主上限会被服务端以 E_QUOTA 拒绝并删除未提交内容，此处先行自检避免无效分块。
    """
    if len(data) > maximum_bytes:
        return None
    opened = _sdk_call("artifact.stream.open", {"name": filename, "media_type": "application/pdf"})
    if not opened or not opened.get("handle"):
        return None
    handle = opened["handle"]
    host_max = int(opened.get("maximum_bytes", maximum_bytes))
    if len(data) > host_max:
        _sdk_call("artifact.stream.abort", {"handle": handle})
        return None
    try:
        offset = 0
        chunk_size = 1024 * 1024  # 宿主单块上限 1 MiB
        while offset < len(data):
            chunk = data[offset:offset + chunk_size]
            written = _sdk_call("artifact.stream.write",
                                {"handle": handle, "content_b64": _base64.b64encode(chunk).decode("ascii")})
            if written is None:
                _sdk_call("artifact.stream.abort", {"handle": handle})
                return None
            offset += len(chunk)
        committed = _sdk_call("artifact.stream.commit", {"handle": handle})
        return committed
    except Exception:
        _sdk_call("artifact.stream.abort", {"handle": handle})
        return None


# 类型别名
JsonDict = Dict[str, Any]
CookieDict = Dict[str, str]
PaperDict = Dict[str, Any]
ConfigDict = Dict[str, Any]
ResultDict = Dict[str, Any]

# 结构化日志
_logger = logging.getLogger("academic-paper-downloader")
if not _logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('{"time":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}'))
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)

# 追踪 ID 上下文
_trace_id_ctx: threading.local = threading.local()

# 当前下载配置上下文（用于 _stream_pdf/_fetch_pdf 获取连接池参数）
_download_config_ctx: threading.local = threading.local()

def _get_trace_id() -> str:
    if not hasattr(_trace_id_ctx, "trace_id"):
        _trace_id_ctx.trace_id = str(uuid.uuid4())[:8]
    return _trace_id_ctx.trace_id

def _set_trace_id(tid: str) -> None:
    _trace_id_ctx.trace_id = tid

def _set_download_config(config: ConfigDict) -> None:
    _download_config_ctx.config = config

def _get_download_config() -> ConfigDict:
    return getattr(_download_config_ctx, "config", {})

def _log(event: str, level: int = logging.INFO, **kw) -> None:
    _logger.log(level, json.dumps({"event": event, "trace_id": _get_trace_id(), **kw}, ensure_ascii=False))

# 默认配置常量（可被 config 覆盖）
_DEFAULT_CONFIG: Dict[str, Any] = {
    "max_pdf_bytes": 100 * 1024 * 1024,
    "done_doi_cap": 20000,
    "oa_precheck_limit": 300,
    "oa_precheck_concurrency": 4,
    "default_concurrency": 3,
    "retry_base_delay": 2.0,
    "retry_max_delay": 60.0,
    "download_timeout": 60,
    "http_pool_max_connections": 20,
    "http_pool_max_keepalive": 10,
    "cookie_refresh_threshold_hours": 1,
    "proxy_check_interval_sec": 60,
    "proxy_circuit_breaker_threshold": 3,
    "inspect_cache_size": 256,
}

def _get_config_value(config: ConfigDict, key: str, default: Any = None) -> Any:
    """从 config 获取值，回退到 _DEFAULT_CONFIG。"""
    if key in config:
        return config[key]
    return _DEFAULT_CONFIG.get(key, default)

# 运行时常量（初始化为默认值，_seed 中会按 config 更新）
_MAX_PDF_BYTES = _DEFAULT_CONFIG["max_pdf_bytes"]
_DONE_DOI_CAP = _DEFAULT_CONFIG["done_doi_cap"]
_OA_PRECHECK_LIMIT = _DEFAULT_CONFIG["oa_precheck_limit"]
_OA_PRECHECK_CONCURRENCY = _DEFAULT_CONFIG["oa_precheck_concurrency"]

PLUGIN_METADATA = {
    "name": "academic-paper-downloader",
    "version": "0.9.0",
    "api_version": 1,
    "description": "从 Web of Science 导出文件批量下载论文 PDF，全优化版",
    "plugin_types": ["source", "processor", "hook"],
    "permissions": ["network:scoped", "records:read", "state:read", "state:write", "secrets:read", "files:read", "artifacts:write"],
    "domains": [
        "api.crossref.org", "api.unpaywall.org", "api.openalex.org",
        "www.sciencedirect.com", "link.springer.com", "pubs.acs.org",
        "pubs.aip.org", "pubs.rsc.org", "onlinelibrary.wiley.com",
        "journals.aps.org", "ieeexplore.ieee.org", "www.mdpi.com",
        "arxiv.org",
    ],
    "input_files": ["*.xlsx", "*.xls", "*.tsv", "*.ris", "*.bib", "*.csv", "*.json"],
    "dependencies": [
        {"name": "yaml", "version": ">=5.4,<7.0", "license": "MIT"},
        {"name": "openpyxl", "version": ">=3.0,<4.0", "license": "MIT"},
        # 旧版 .xls 导出走 xlrd（导入处有 try/except，缺库时静默降级）。
        # ★ 市场审计的门 3 是「实测导入 ⇒ 必须声明」的 fail-closed 口径，且**不看**
        #   optional_dependencies ⇒ 不声明就是 error（实测 gate3_imported_but_not_declared）。
        {"name": "xlrd", "version": ">=2.0,<3.0", "license": "BSD-3-Clause"},
        {"name": "pdfplumber", "version": ">=0.10,<1.0", "license": "MIT"},
        {"name": "pypdf", "version": ">=3.0,<4.0", "license": "BSD-3-Clause"},
    ],
    "license": "MIT",
    "execution_mode": "subprocess",
    "min_core_version": "0.11.2",
}

# ---------------------------------------------------------------------------
# 出版商路由表（默认值；可由 config/publishers.yaml 覆盖）
# ---------------------------------------------------------------------------
_DEFAULT_PUBLISHERS: dict[str, dict[str, Any]] = {
    "elsevier": {"doi_prefix": "10.1016/", "oa_pattern": "https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true", "home": "https://www.sciencedirect.com", "auth_method": "proxy", "rate_limit": 2.0},
    "springer": {"doi_prefix": "10.1007/", "oa_pattern": "https://link.springer.com/content/pdf/{doi}.pdf", "home": "https://link.springer.com", "auth_method": "proxy", "rate_limit": 3.0},
    "acs": {"doi_prefix": "10.1021/", "oa_pattern": "https://pubs.acs.org/doi/pdf/{doi}", "home": "https://pubs.acs.org", "auth_method": "cookie", "rate_limit": 3.0},
    "aip": {"doi_prefix": "10.1063/", "oa_pattern": "https://pubs.aip.org/aip/article-pdf/{doi}/pdf", "home": "https://pubs.aip.org", "auth_method": "proxy", "rate_limit": 4.0},
    "rsc": {"doi_prefix": "10.1039/", "oa_pattern": "https://pubs.rsc.org/en/content/articlepdf/{doi}", "home": "https://pubs.rsc.org", "auth_method": "proxy", "rate_limit": 2.0},
    "wiley": {"doi_prefix": "10.1002/", "oa_pattern": "https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}", "home": "https://onlinelibrary.wiley.com", "auth_method": "saml", "rate_limit": 3.0},
    "aps": {"doi_prefix": "10.1103/", "oa_pattern": "https://journals.aps.org/pr/pdf/{doi}", "home": "https://journals.aps.org", "auth_method": "proxy", "rate_limit": 4.0},
    "ieee": {"doi_prefix": "10.1109/", "oa_pattern": None, "home": "https://ieeexplore.ieee.org", "auth_method": "proxy", "rate_limit": 5.0},
    "mdpi": {"doi_prefix": "10.3390/", "oa_pattern": "https://www.mdpi.com/{doi}/pdf", "home": "https://www.mdpi.com", "auth_method": "none", "rate_limit": 1.0},
    "arxiv": {"doi_prefix": "10.48550/arXiv.", "oa_pattern": "https://arxiv.org/pdf/{doi_suffix}", "home": "https://arxiv.org", "auth_method": "none", "rate_limit": 1.0},
}

_PUBLISHERS: dict[str, dict[str, Any]] = dict(_DEFAULT_PUBLISHERS)
_PREFIX_TO_PUBLISHER: dict[str, str] = {}
def _rebuild_prefix_map() -> None:
    global _PREFIX_TO_PUBLISHER
    _PREFIX_TO_PUBLISHER = {}
    for _name, _cfg in _PUBLISHERS.items():
        if _cfg.get("doi_prefix"):
            _PREFIX_TO_PUBLISHER[_cfg["doi_prefix"].lower()] = _name
_rebuild_prefix_map()

# OA 期刊 ISSN 白名单（由 config/oa_journals.yaml 维护）
_OA_JOURNALS: set[str] = set()

# 配置文件路径（与插件同目录，随插件打包）
_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_PUBLISHERS_CONFIG = _CONFIG_DIR / "publishers.yaml"
_OA_JOURNALS_CONFIG = _CONFIG_DIR / "oa_journals.yaml"
_PUBLISHERS_RELOADER: _ConfigHotReload | None = None  # 在 _ConfigHotReload 定义后初始化

# 错误类型分类
ERROR_CLASSIFICATION = {
    "429": "rate_limit",
    "5xx": "server_error",
    "timeout": "network",
    "captcha": "captcha",
    "403": "auth_required",
    "connection": "network",
}

# ---------------------------------------------------------------------------
# Token Bucket 限流器（每域名独立）
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _domain_of(self, publisher: str) -> str:
        cfg = _PUBLISHERS.get(publisher, {})
        home = cfg.get("home", "")
        if home:
            from urllib.parse import urlparse
            return urlparse(home).netloc
        return publisher

    def wait(self, publisher: str, config: ConfigDict | None = None) -> None:
        domain = self._domain_of(publisher)
        cfg = _PUBLISHERS.get(publisher, {})
        rate = cfg.get("rate_limit", 2.0)
        if rate <= 0:
            return
        now = time.time()
        with self._lock:
            if domain not in self._buckets:
                self._buckets[domain] = {"tokens": 1.0, "last": now}
                return
            elapsed = now - self._buckets[domain]["last"]
            self._buckets[domain]["tokens"] = min(1.0, self._buckets[domain]["tokens"] + elapsed * rate)
            if self._buckets[domain]["tokens"] >= 1.0:
                self._buckets[domain]["tokens"] -= 1.0
                self._buckets[domain]["last"] = now
                return
            wait_time = (1.0 - self._buckets[domain]["tokens"]) / rate
        time.sleep(wait_time)
        with self._lock:
            self._buckets[domain]["tokens"] = 0.0
            self._buckets[domain]["last"] = time.time()

_RATE_LIMITER = _RateLimiter()

# ---------------------------------------------------------------------------
# 并发控制（Semaphore，更简洁）
# ---------------------------------------------------------------------------
class _ConcurrencyController:
    """进程内并发上限。使用 Semaphore 实现。"""

    def __init__(self, max_concurrent: int = 3) -> None:
        self._sem = threading.Semaphore(max_concurrent)
        self._max = max_concurrent

    def acquire(self) -> None:
        self._sem.acquire()

    def release(self) -> None:
        self._sem.release()

    def __enter__(self) -> "_ConcurrencyController":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    @property
    def active(self) -> int:
        return self._max - self._sem._value  # type: ignore[attr-defined]

def _make_concurrency_controller(config: ConfigDict) -> _ConcurrencyController:
    max_c = int(_get_config_value(config, "default_concurrency", 3))
    return _ConcurrencyController(max_c)

# ---------------------------------------------------------------------------
# 代理健康检查 & 熔断器
# ---------------------------------------------------------------------------
class _ProxyHealthChecker:
    def __init__(self) -> None:
        self._health: dict[str, dict] = {}  # proxy -> {score, failures, last_check, latencies}
        self._circuit_breaker: dict[str, bool] = {}  # proxy -> open

    def check(self, proxy: str, config: ConfigDict | None = None) -> bool:
        """v0.9.0：宿主 network.fetch 不暴露代理参数，代理级健康探测已不可用。

        保留熔断数据结构以维持状态/日志形状；探测一律返回 False（视为不可用），
        调用方按降级处理，绝不回退到直连探测。
        """
        if config is None:
            config = {}
        now = time.time()
        failures = self._health.get(proxy, {}).get("failures", 0) + 1
        circuit_threshold = int(_get_config_value(config, "proxy_circuit_breaker_threshold", 3))
        self._health[proxy] = {"score": max(0, 100 - failures * 20), "failures": failures, "last_check": now}
        self._circuit_breaker[proxy] = failures >= circuit_threshold
        return False

    def get_best_proxy(self, proxy_list: list[str]) -> str | None:
        """获取健康度最高、延迟最低的代理。"""
        healthy = [p for p in proxy_list if not self._circuit_breaker.get(p, False)]
        if not healthy:
            return None
        # 优先按 score 降序，再按 P99 延迟升序
        def proxy_key(p: str) -> tuple:
            h = self._health.get(p, {})
            score = h.get("score", 50)
            latencies = h.get("latencies", [])
            if latencies:
                sorted_lat = sorted(latencies)
                p99 = sorted_lat[int(len(sorted_lat) * 0.99)]
            else:
                p99 = 9999
            return (-score, p99)
        return max(healthy, key=proxy_key)

    def record_failure(self, proxy: str) -> None:
        """记录一次失败，用于熔断。"""
        self.check(proxy, None)  # 触发更新

_PROXY_HEALTH = _ProxyHealthChecker()

# ---------------------------------------------------------------------------
# 分布式锁（基于 state）
# ---------------------------------------------------------------------------
class _DistributedLock:
    """Workspace-local OS file lock; crash/exit releases it without stale TTL races.

    Lock files remain as stable inodes. Never unlink a lock while another process
    might be waiting on it. This is same-machine coordination, not a cluster lock.
    """
    def __init__(self, config: dict, workspace: Path | None = None) -> None:
        self._directory = (workspace or _STATE_DIR or Path(tempfile.gettempdir()) / "apd-locks")
        self._handles: dict[str, Any] = {}

    def acquire(self, doi: str, timeout: int = 300) -> bool:
        folder = self._directory / ".apd_locks"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (hashlib.sha256(doi.lower().encode()).hexdigest() + ".lock")
        stream = open(path, "a+b")
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self._handles[doi.lower()] = stream
        return True

    def release(self, doi: str) -> None:
        stream = self._handles.pop(doi.lower(), None)
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    @staticmethod
    def cleanup_stale_locks(config: dict, max_age: int = 3600) -> int:
        # OS releases locks on crash; stable files must not be unlinked.
        return 0

# ---------------------------------------------------------------------------
# 登录态监控
# ---------------------------------------------------------------------------
class _CookieMonitor:
    def __init__(self, config: dict) -> None:
        self._config = config
        self._last_check: float = 0
        self._check_interval = 300  # 5 分钟
        self._valid: bool = True
        # 从配置读取刷新阈值（小时）
        self._refresh_threshold_hours = float(_get_config_value(config, "cookie_refresh_threshold_hours", 1))

    def is_valid(self) -> bool:
        """检查 Cookie 是否仍然有效（缓存结果）。"""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return self._valid
        self._last_check = now
        try:
            result = _state_get(_cookie_key(self._config))
            if not result or not result.get("value"):
                self._valid = False
                return False
            cookies = json.loads(result["value"])
            now_ts = time.time()
            for c in cookies:
                exp = c.get("expires", -1)
                if exp > 0 and exp < now_ts:
                    self._valid = False
                    return False
            self._valid = True
            return True
        except Exception:
            self._valid = False
            return False

    def needs_proactive_refresh(self) -> bool:
        """检查是否需要主动刷新（过期前 N 小时）。"""
        try:
            result = _state_get(_cookie_key(self._config))
            if not result or not result.get("value"):
                return True
            cookies = json.loads(result["value"])
            now_ts = time.time()
            threshold_sec = self._refresh_threshold_hours * 3600
            for c in cookies:
                exp = c.get("expires", -1)
                if exp > 0 and (exp - now_ts) < threshold_sec:
                    return True
            return False
        except Exception:
            return True

    def refresh_if_needed(self) -> list[dict] | None:
        """如果 Cookie 无效或即将过期，重新登录获取。"""
        # v0.6.6：未配置 login_url（如校园 IP 直连模式）时静默返回——
        # 此前每篇论文都打一条 cookie_proactive_refresh 日志（纯噪声）。
        if not (self._config.get("institution", {}) or {}).get("login_url"):
            return None
        if not self.is_valid() or self.needs_proactive_refresh():
            _log("cookie_proactive_refresh", reason="expiring_soon" if self.needs_proactive_refresh() else "invalid")
            return _login_and_capture_cookie(self._config)
        return _get_cached_cookie(self._config)

_COOKIE_MONITOR: _CookieMonitor | None = None

def _get_cookie_monitor(config: dict) -> _CookieMonitor:
    global _COOKIE_MONITOR
    if _COOKIE_MONITOR is None or _COOKIE_MONITOR._config != config:
        _COOKIE_MONITOR = _CookieMonitor(config)
    return _COOKIE_MONITOR

# ---------------------------------------------------------------------------
# 配置热重载
# ---------------------------------------------------------------------------
class _ConfigHotReload:
    def __init__(self, config_path: str) -> None:
        self._config_path = config_path
        self._last_mtime: float = 0
        self._cached: dict | None = None

    def _read(self) -> dict | None:
        """读取配置。按扩展名判断格式（YAML 文件即使带 # 注释头也能识别）。"""
        with open(self._config_path, encoding="utf-8") as f:
            content = f.read()
        suffix = Path(self._config_path).suffix.lower()
        if _HAS_YAML and suffix in (".yaml", ".yml"):
            try:
                data = yaml.safe_load(content)
            except Exception:
                return None
            return data if isinstance(data, dict) else None
        try:
            data = json.loads(content)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def get(self) -> dict | None:
        """获取配置，自动检测文件修改并重载（支持 JSON 与 YAML）。"""
        try:
            mtime = Path(self._config_path).stat().st_mtime
            if mtime != self._last_mtime or self._cached is None:
                self._last_mtime = mtime
                self._cached = self._read()
                if self._cached is not None:
                    _log("config_reloaded", path=self._config_path)
            return self._cached
        except Exception:
            return self._cached

# ---------------------------------------------------------------------------
# 配置文件装载（publishers.yaml / oa_journals.yaml → 运行时表）
# ---------------------------------------------------------------------------
def _reload_publishers_config() -> bool:
    """从 config/publishers.yaml 重载 _PUBLISHERS（未声明字段保留默认值）。"""
    global _PUBLISHERS
    if not _HAS_YAML:
        return False
    if not Path(_PUBLISHERS_CONFIG).is_file():
        return False
    try:
        reloader = _get_publishers_reloader()
        data = reloader.get()
        if not isinstance(data, dict) or not isinstance(data.get("publishers"), dict):
            return False
        merged = dict(_DEFAULT_PUBLISHERS)
        for name, cfg in data["publishers"].items():
            if not isinstance(cfg, dict):
                continue
            base = dict(merged.get(name, {}))
            for k, v in cfg.items():
                if v is not None:
                    base[k] = v
            if base.get("doi_prefix"):
                merged[name] = base
        _PUBLISHERS = merged
        _rebuild_prefix_map()
        return True
    except Exception:
        return False

def _reload_oa_journals_config() -> bool:
    """从 config/oa_journals.yaml 重载 _OA_JOURNALS（ISSN 白名单）。"""
    global _OA_JOURNALS
    if not _HAS_YAML:
        return False
    if not Path(_OA_JOURNALS_CONFIG).is_file():
        return False
    try:
        with open(_OA_JOURNALS_CONFIG, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        journals = data.get("oa_journals", []) if isinstance(data, dict) else []
        _OA_JOURNALS = {str(j.get("issn", "")).strip() for j in journals if isinstance(j, dict) and j.get("issn")}
        return bool(_OA_JOURNALS)
    except Exception:
        return False

def _get_publishers_reloader() -> _ConfigHotReload:
    global _PUBLISHERS_RELOADER
    if _PUBLISHERS_RELOADER is None:
        _PUBLISHERS_RELOADER = _ConfigHotReload(str(_PUBLISHERS_CONFIG))
    return _PUBLISHERS_RELOADER

def _reload_plugin_config() -> None:
    """入口统一调用：热重载全部外部配置（幂等，mtime 变化才生效）。"""
    _reload_publishers_config()
    _reload_oa_journals_config()

_reload_plugin_config()  # 模块加载时装载一次

# ---------------------------------------------------------------------------
# 智能重试分类
# ---------------------------------------------------------------------------
def _classify_error(status_code: int | None, error_type: str | None, publisher: str | None = None) -> str:
    """将错误分类为可处理的策略。"""
    if status_code == 429:
        return "rate_limit"
    if status_code and status_code >= 500:
        return "server_error"
    if status_code in (401, 403):
        # 无需登录的 OA 出版商（auth_method=none）401/403 多为 bot 反爬而非授权
        if _PUBLISHERS.get(publisher or "", {}).get("auth_method") == "none":
            return "bot_blocked"
        return "auth_required"
    if status_code == 200:
        # 200 但非 PDF：订阅源=登录墙（认证失效），OA 源=反爬落地页
        if _PUBLISHERS.get(publisher or "", {}).get("auth_method") == "none":
            return "bot_blocked"
        return "auth_required"
    if error_type and (error_type == "timeout" or error_type == "connection"):
        return "network"
    if error_type and "captcha" in str(error_type).lower():
        return "captcha"
    return "unknown"

def _retry_strategy(error_class: str, attempt: int, config: dict) -> float | None:
    """根据错误类型返回等待时间（秒），None 表示不应重试。"""
    base = config.get("retry_base_delay", 2.0)
    max_delay = config.get("retry_max_delay", 60.0)
    max_retries = config.get("retry_count", 3)

    if attempt > max_retries:
        return None  # 超过最大重试次数

    if error_class == "rate_limit":
        # 429 退避：等待时间更长
        delay = min(base * (2 ** attempt) * 3, max_delay)
        return delay
    elif error_class == "server_error":
        # 5xx 指数退避
        return min(base * (2 ** attempt), max_delay)
    elif error_class == "network":
        # 网络问题：中等退避
        return min(base * (1.5 ** attempt), max_delay)
    elif error_class == "auth_required":
        # 403：需要重新登录，不重试 HTTP
        return None
    elif error_class in ("bot_blocked", "captcha"):
        # v0.4.0 起这两类是"通道不匹配"信号：同一 HTTP 通道内重试在语义上不可能
        # 成功（反爬识别的是通道指纹），直接返回 None 不重试，时间让给通道升级
        # （browser_channel_upgrade / 可见浏览器兜底）。
        return None
    return None

# ---------------------------------------------------------------------------
# 路径安全工具
# ---------------------------------------------------------------------------
def _resolve_workspace_path(base: str, rel_path: str) -> Path:
    base_path = Path(base).resolve()
    target = (base_path / rel_path).resolve()
    try:
        target.relative_to(base_path)
    except ValueError:
        target = base_path / Path(rel_path).name
    return target

def _safe_mkdir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def _cleanup_stale_tmp(workspace: Path, max_age: float = 24 * 3600) -> None:
    """清理工作区内过期的下载临时文件（崩溃残留）。"""
    tmp_dir = workspace / ".tmp"
    try:
        now = time.time()
        for f in tmp_dir.glob("*.part"):
            try:
                if now - f.stat().st_mtime > max_age:
                    f.unlink()
            except Exception:
                pass
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 状态键工具
# ---------------------------------------------------------------------------
def _state_key(ns: str, config: dict) -> str:
    proxy = config.get("institution", {}).get("proxy_url", "default")
    return f"apd_{ns}_{hashlib.md5(proxy.encode()).hexdigest()[:8]}"
def _done_key(config: dict) -> str: return _state_key("done", config)
def _failed_key(config: dict) -> str: return _state_key("failed", config)
def _cookie_key(config: dict) -> str: return _state_key("cookie", config)
def _lock_key(config: dict, doi: str) -> str: return f"{_state_key('lock', config)}_{doi.lower()}"
def _record_key(config: dict, doi: str) -> str:
    return f"{_state_key('record', config)}_{hashlib.md5(str(doi).lower().encode()).hexdigest()[:16]}"

# ---------------------------------------------------------------------------
# 状态存取（v0.4.0）：SDK 优先，缺席时以 workspace 文件兜底
# ---------------------------------------------------------------------------
_STATE_DIR: Path | None = None

def _set_state_dir(workspace) -> None:
    """记录 workspace，供无 SDK 环境（独立运行）把增量状态落到文件。

    同时清理历史版本可能遗留的 Cookie 明文文件（安全回归修复的善后）。
    """
    global _STATE_DIR
    try:
        _STATE_DIR = Path(workspace) / ".apd_state"
        if _STATE_DIR.is_dir():
            for stale in _STATE_DIR.glob("apd_cookie_*.json"):
                try:
                    stale.unlink()
                    _log("stale_cookie_file_removed", path=str(stale))
                except Exception:
                    pass
    except Exception:
        _STATE_DIR = None

def _state_file(key: str) -> Path | None:
    if _STATE_DIR is None:
        return None
    return _STATE_DIR / (re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")

def _is_cookie_key(key: str) -> bool:
    """Cookie 是会话凭证：明确禁止落入 workspace 明文文件（v0.4.0 安全回归修复）。"""
    return key.startswith("apd_cookie_")

def _state_get(key: str) -> dict | None:
    """读状态：SDK 优先；SDK 缺席且已知 workspace 时读文件。都不可用 → None。

    Cookie 键不落文件（会话凭证明文落盘属安全回归），只走 SDK。
    文件格式带版本号（D7）：{"v": 1, "value": "..."}；兼容读取无版本旧格式。
    """
    if _is_cookie_key(key):
        try:
            import omnicrawler_sdk
            result = omnicrawler_sdk.call("state.get", {"key": key})
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        return None
    try:
        import omnicrawler_sdk
        result = omnicrawler_sdk.call("state.get", {"key": key})
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    try:
        f = _state_file(key)
        if f is not None and f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "v" in data:
                return {"value": data.get("value")} if data.get("v") == 1 else None
            return {"value": data.get("value") if isinstance(data, dict) and "value" in data
                    else f.read_text(encoding="utf-8")}
    except Exception:
        pass
    return None

def _state_set(key: str, value: str) -> None:
    """写状态：SDK 优先；SDK 缺席且已知 workspace 时写文件。

    Cookie 键禁止文件兜底：Cookie 是会话凭证，明文写入用户目录属安全回归。
    """
    if _is_cookie_key(key):
        try:
            import omnicrawler_sdk
            omnicrawler_sdk.call("state.set", {"key": key, "value": value})
        except Exception:
            _log("cookie_state_sdk_only", level=logging.DEBUG)
        return
    try:
        import omnicrawler_sdk
        omnicrawler_sdk.call("state.set", {"key": key, "value": value})
        return
    except Exception:
        pass
    try:
        f = _state_file(key)
        if f is not None:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=f.parent, prefix=f.name + ".", suffix=".tmp", delete=False) as stream:
                    tmp = Path(stream.name)
                    stream.write(json.dumps({"v": 1, "value": value}, ensure_ascii=False))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, f)
            finally:
                if tmp is not None and tmp.exists():
                    tmp.unlink()
    except Exception:
        pass

def _state_delete(key: str) -> None:
    try:
        import omnicrawler_sdk
        omnicrawler_sdk.call("state.delete", {"key": key})
        return
    except Exception:
        pass
    try:
        f = _state_file(key)
        if f is not None and f.exists():
            f.unlink()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# DOI 解析
# ---------------------------------------------------------------------------
def _extract_doi(row: dict[str, str]) -> str | None:
    doi = (row.get("DOI") or "").strip()
    if normalize_doi(doi): return normalize_doi(doi)
    link = (row.get("DOI Link") or "").strip()
    if normalize_doi(link): return normalize_doi(link)
    for val in row.values():
        if isinstance(val, str) and "10." in val:
            m = re.search(r"(10\.\d{4,}/[^\s]+)", val)
            if m: return normalize_doi(m.group(1).rstrip(")")) or None
    return None

def _resolve_publisher(doi: str) -> str | None:
    d = str(doi).lower()
    for prefix, name in _PREFIX_TO_PUBLISHER.items():
        if d.startswith(prefix): return name
    return None
def _extract_pii(doi: str) -> str:
    if doi.startswith("10.1016/"):
        parts = doi.split("/", 1)
        return parts[1] if len(parts) == 2 else ""
    return ""

# ---------------------------------------------------------------------------
# 多格式输入解析
# ---------------------------------------------------------------------------
def _decode_bytes(raw: bytes) -> str | None:
    """编码探测：utf-8-sig → utf-8 → gb18030（WoS 中文系统常导出 GBK）。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None

def _strict_csv_rows(text: str, reader_ctor) -> list[dict[str, str]]:
    return [{k: (v.strip() if v else "") for k, v in row.items()}
            for row in reader_ctor(io.StringIO(text))
            if any(v is not None for v in row.values())]

# WoS 导出字段码 → 规范列名（官方 TSV 头为两字母码）
_WOS_HEADER_MAP: dict[str, str] = {
    "TI": "Article Title", "AU": "Authors", "AF": "Author Full Names",
    "SO": "Source Title", "PY": "Publication Year", "DI": "DOI",
    "SN": "ISSN", "VL": "Volume", "IS": "Issue", "BP": "Start Page",
    "EP": "End Page", "AB": "Abstract", "DE": "Keywords", "C1": "Addresses",
}

def _normalize_tsv_headers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """WoS 两字母字段码头 → 规范列名（未知列名原样保留）。"""
    return [{_WOS_HEADER_MAP.get(k, k): v for k, v in row.items()} for row in rows]

def _iter_excel_rows(path: Path):
    """惰性产出工作簿表行（首行头 + 数据行），避免整簿读入内存。

    xlsx 走 openpyxl；旧版 .xls 走 xlrd（可选，缺库时静默降级）。
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                yield row
        finally:
            wb.close()
        return
    except ImportError:
        pass
    except Exception:
        pass
    if not _HAS_XLRD:
        return
    try:
        wb = xlrd.open_workbook(str(path))
        sh = wb.sheet_by_index(0)
        for r in range(min(sh.nrows, 50000)):  # 防御性上限
            yield tuple(sh.row_values(r))
    except Exception:
        return

def _excel_records(path: Path) -> list[dict[str, str]]:
    rows = list(_iter_excel_rows(path))
    if not rows:
        return []
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
    return [{headers[i]: str(c).strip() if c else "" for i, c in enumerate(row)}
            for row in rows[1:] if any(c for c in row)]

def _parse_input_file(file_path: str) -> list[dict[str, str]]:
    path = Path(file_path)
    if not path.exists(): return []
    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls"):
        try:
            return _excel_records(path)
        except Exception:
            return []

    raw = path.read_bytes()
    text = _decode_bytes(raw)
    if text is None:
        return []
    text = text.lstrip("\ufeff")

    if suffix == ".tsv":
        return _normalize_tsv_headers(_strict_csv_rows(text, lambda fh: csv.DictReader(fh, delimiter="\t")))
    if suffix == ".csv":
        return _strict_csv_rows(text, lambda fh: csv.DictReader(fh))
    if suffix == ".ris":
        return _parse_ris_text(text)
    if suffix == ".bib":
        return _parse_bibtex_text(text)
    if suffix == ".json":
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [{k: str(v) for k, v in item.items()} for item in data]
        except Exception as e:
            _log("swallowed_exception", level=logging.DEBUG, where="input_json_parse", error=str(e))

    return []

def _parse_ris(file_path: str) -> list[dict[str, str]]:
    raw = Path(file_path).read_bytes()
    text = _decode_bytes(raw)
    return _parse_ris_text(text or "")

def _parse_ris_text(text: str) -> list[dict[str, str]]:
    """解析 RIS 格式（兼容 ER 无尾空格 / 末尾不换行 / GBK）。"""
    papers = []
    current: dict[str, str] = {}
    tag_map = {
        "TI": "Article Title", "AU": "Authors", "PY": "Publication Year",
        "JO": "Source Title", "DO": "DOI", "VL": "Volume", "IS": "Issue",
        "SP": "Start Page", "EP": "End Page", "SN": "ISSN",
    }
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if current:
                papers.append(current)
                current = {}
            continue
        if re.match(r"^ER\b", line):
            if current:
                papers.append(current)
                current = {}
            continue
        m = re.match(r"^([A-Z]{2})\s+-\s*(.*)$", line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if tag in tag_map and val:
                current[tag_map[tag]] = val
    if current:  # EOF flush
        papers.append(current)
    return papers

def _parse_bibtex(file_path: str) -> list[dict[str, str]]:
    raw = Path(file_path).read_bytes()
    text = _decode_bytes(raw)
    return _parse_bibtex_text(text or "")

def _parse_bibtex_text(text: str) -> list[dict[str, str]]:
    """解析 BibTeX（正则逐条，每条件独立，嵌套花括号可放宽）。"""
    papers = []
    mapping = {"title": "Article Title", "author": "Authors", "year": "Publication Year",
               "journal": "Source Title", "doi": "DOI", "issn": "ISSN",
               "pages": "Start Page", "volume": "Volume", "number": "Issue"}
    try:
        for m in re.finditer(r"@(\w+)\s*\{\s*([^,\n}]+)\s*,(.*?)(?=\n\s*@|\Z)", text, re.DOTALL):
            etype, cite_key, body = m.group(1), m.group(2).strip(), m.group(3)
            entry = {"DOI": "", "Article Title": cite_key, "Entry Type": etype}
            for fm in re.finditer(r"(\w+)\s*=\s*\{([^{}]*)\}", body):
                key, val = fm.group(1).lower(), fm.group(2).strip()
                if key in mapping:
                    entry[mapping[key]] = val
            papers.append(entry)
    except Exception:
        pass
    return papers

# ---------------------------------------------------------------------------
# PDF 校验 & 元数据提取
# ---------------------------------------------------------------------------
_INSPECT_CACHE: dict[tuple, tuple[bool, dict[str, Any]]] = {}
_INSPECT_CACHE_MAX = 256

def _inspect_pdf(path: Path) -> tuple[bool, dict[str, Any]]:
    """一次打开完成「校验 + 元数据提取」。返回 (is_valid, meta)。"""
    parser_available = False
    try:
        import pdfplumber
        parser_available = True
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) == 0:
                return False, {}
            first_text = pdf.pages[0].extract_text() or ""
            errors = ["access denied", "403 forbidden", "captcha", "please verify", "robot check"]
            if any(e in first_text.lower() for e in errors):
                return False, {}
            text = "".join(p.extract_text() or "" for p in pdf.pages[:2])
            meta: dict[str, Any] = {}
            m = re.search(r"(10\.\d{4,}/[^\s]+)", text)
            if m:
                meta["extracted_doi"] = m.group(1)
            title_m = re.search(r"(?:Title|Article)[：\:]\s*(.+?)(?:\n|$)", text[:500])
            if title_m:
                meta["extracted_title"] = title_m.group(1).strip()
        meta["validation_level"] = "structure_parsed"
        return True, meta
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        parser_available = True
        reader = PdfReader(str(path))
        if len(reader.pages) == 0 or reader.is_encrypted:
            return False, {}
        return True, {"validation_level": "structure_parsed"}
    except Exception:
        pass
    # 两个 PDF 解析库均不可用（或文件损坏）时退化为魔数校验，
    # 避免在最小环境里把已成功下载的 PDF 误判删除
    try:
        with path.open("rb") as stream:
            header_matches = stream.read(1024).lstrip().startswith(b"%PDF-")
        if parser_available:
            return False, {"validation_level": "structure_invalid"}
        return header_matches, {"validation_level": "header_only" if header_matches else "invalid_format"}
    except Exception:
        return False, {}

def _inspect_pdf_cached(path: Path) -> tuple[bool, dict[str, Any]]:
    """带缓存的一次性解析：同一文件同一次运行内只开一次。"""
    key = (str(path), path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else (str(path), 0, 0)
    cached = _INSPECT_CACHE.get(key)
    if cached is not None:
        return cached
    result = _inspect_pdf(path)
    if len(_INSPECT_CACHE) >= _INSPECT_CACHE_MAX:
        _INSPECT_CACHE.clear()
    _INSPECT_CACHE[key] = result
    return result

def _validate_pdf(path: Path) -> bool:
    return _inspect_pdf_cached(path)[0]

def _extract_pdf_meta(path: Path) -> dict[str, Any]:
    return _inspect_pdf_cached(path)[1]

# ---------------------------------------------------------------------------
# 文件名处理（去重 + 元数据重命名）
# ---------------------------------------------------------------------------
def _unique_filename(papers_dir: Path, base: str) -> Path:
    candidate = papers_dir / base
    if not candidate.exists(): return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for i in range(1, 999):
        candidate = papers_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists(): return candidate
    return papers_dir / f"{stem}_{int(time.time())}{suffix}"

def _rename_with_metadata(paper: dict, path: Path) -> Path:
    """用 PDF 元数据修正文件名。"""
    meta = _extract_pdf_meta(path)
    if meta.get("extracted_title"):
        safe_title = re.sub(r"[^\w\s-]", "", meta["extracted_title"])[:50].strip().replace(" ", "_")
        new_name = f"{paper.get('first_author', 'Unknown')}_{paper.get('year', '')}_{safe_title}.pdf"
        new_path = _unique_filename(path.parent, new_name)
        if path != new_path:
            path.rename(new_path)
            return new_path
    return path

# ---------------------------------------------------------------------------
# OpenAlex 批量预检
# ---------------------------------------------------------------------------
def _fetch_oa_status(doi: str) -> tuple[str, bool]:
    """单个 DOI 查询 OpenAlex OA 状态（经宿主 EgressBroker），返回 (doi, is_oa)。"""
    try:
        from urllib.parse import quote
        url = ("https://api.openalex.org/works"
               f"?filter=doi:{quote(str(doi), safe='')}&select=id,doi,open_access&per-page=1")
        body, status, _final = _host_fetch(
            url, headers={"User-Agent": "academic-paper-downloader/0.9.0"})
        if status != 200:
            return doi, False
        for item in json.loads(body.decode("utf-8", errors="replace")).get("results", []):
            item_doi = (item.get("doi") or "").replace("https://doi.org/", "").lower()
            if item_doi == str(doi).lower():
                oa = item.get("open_access", {}).get("oa_status")
                return doi, oa in ("gold", "green", "bronze")
    except Exception:
        pass
    return doi, False

def _batch_check_oa(dois: list[str], concurrency: int = _OA_PRECHECK_CONCURRENCY) -> dict[str, bool]:
    """并发查询 OpenAlex 获取 OA 状态，返回 {doi: is_oa}。

    注意：OpenAlex 当前不支持 doi 过滤器的批量 OR 语法，故按 DOI 并发单查。
    使用分块提交避免一次性创建大量 future（最多 300 个）。
    """
    result: dict[str, bool] = {}
    if not dois:
        return result
    CHUNK = 50  # 每批提交的任务数
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            for i in range(0, len(dois), CHUNK):
                chunk = dois[i:i + CHUNK]
                futs = [ex.submit(_fetch_oa_status, d) for d in chunk]
                for fut in as_completed(futs):
                    try:
                        doi, is_oa = fut.result(timeout=30)
                        result[doi] = is_oa
                    except Exception:
                        pass
    except Exception:
        pass
    return result

def _batch_check_oa_sync(dois: list[str]) -> dict[str, bool]:
    """同步批量查询（无 asyncio，直接调用）。"""
    return _batch_check_oa(dois)

# ---------------------------------------------------------------------------
# 批量报告生成
# ---------------------------------------------------------------------------
def _csv_safe(value: Any) -> str:
    """防御 CSV Excel 公式注入：以 = + - @ 或制表符开头的单元格加单引号前缀。"""
    s = str(value)
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + s
    return s

def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)

def _generate_report(workspace: Path, results: list[dict], failed: list[dict]) -> None:
    """生成 CSV 和 HTML 汇总报告。"""
    report_dir = workspace / "reports"
    _safe_mkdir(report_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # CSV 报告
    csv_path = report_dir / f"download_report_{timestamp}.csv"
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["DOI", "Title", "Authors", "Year", "Journal", "Publisher",
                           "Source", "LocalPath", "FileSize", "Status", "Message"])
            for r in results:
                verified = bool(r.get("verified", True))
                writer.writerow([_csv_safe(r.get("doi","")), _csv_safe(r.get("title","")),
                               _csv_safe(r.get("authors","")), _csv_safe(r.get("year","")),
                               _csv_safe(r.get("journal","")), _csv_safe(r.get("publisher","")),
                               _csv_safe(r.get("download_source","")), _csv_safe(r.get("local_path","")),
                               _csv_safe(r.get("file_size","")),
                               "SUCCESS" if verified else "UNVERIFIED",
                               "" if verified else "未能核验 DOI（文件已保留，不计入成功）"])
            for f_item in failed:
                # v0.3.2：Message = "error_class@layer: 人类可读原因"（旧记录缺字段时逐级回退）。
                # 注意：reason 必须先单独过 _csv_safe——拼接后整串不再以 "=" 开头，
                # 外层转义不会加防公式前缀，注入防护会失效（test_report_output_is_injection_safe 守卫此点）。
                msg = (f"{f_item.get('error_class', 'unknown')}@{f_item.get('layer', 'none')}: "
                       f"{_csv_safe(f_item.get('reason') or _failure_reason(f_item.get('error_class', 'unknown')))}")
                writer.writerow([_csv_safe(f_item.get("doi","")), _csv_safe(f_item.get("title","")),
                               "", "", "", "", "", "", "", "FAILED", _csv_safe(msg)])
        _log("report_generated", path=str(csv_path))
    except Exception as e:
        _logger.exception("CSV report generation failed: %s", e)

    # HTML 看板
    html_path = report_dir / f"dashboard_{timestamp}.html"
    try:
        total = len(results) + len(failed)
        # ★ 未核验（DOI 提不出）的文件仍在 papers/，但**不计入 Success**（issue #22 §1）：
        #   反爬挑战页/登录页/落地页都提不出 DOI，把它们算成成功正是报告失真的来源。
        unverified_count = sum(1 for r in results if not r.get("verified", True))
        success_count = len(results) - unverified_count
        rows_html = ''.join(
            f'<tr data-k="ok"><td>{_esc(r.get("doi",""))}</td><td>{_esc(r.get("title",""))}</td>'
            f'<td>{_esc(r.get("local_path",""))}</td></tr>' for r in results)
        # U10：失败按 error_class 分组小计 + 行级 data-k 供筛选
        fail_counts: dict[str, int] = {}
        for f in failed:
            ec = str(f.get("error_class", "unknown"))
            fail_counts[ec] = fail_counts.get(ec, 0) + 1
        summary_html = ' '.join(
            f'<span class="tag">{_esc(ec)} × {n}</span>' for ec, n in
            sorted(fail_counts.items(), key=lambda kv: -kv[1]))
        failed_html = ''.join(
            f'<tr data-k="fail"><td>{_esc(f.get("doi",""))}</td><td>{_esc(f.get("title",""))}</td>'
            f'<td>{_esc(f.get("error_class","unknown"))} @ {_esc(f.get("layer","none"))}</td>'
            f'<td>{_esc(f.get("reason") or _failure_reason(f.get("error_class","unknown")))}</td></tr>'
            for f in failed)
        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Download Dashboard</title>
<style>body{{font-family:sans-serif;margin:20px;background:#f5f5f5}}
.card{{background:#fff;border-radius:8px;padding:20px;margin:10px;box-shadow:0 2px 4px rgba(0,0,0,.1)}}
.success{{color:#2e7d32}} .fail{{color:#c62828}} .stat{{font-size:2em;font-weight:bold}}
.tag{{display:inline-block;background:#eee;border-radius:4px;padding:2px 8px;margin:2px;font-size:13px}}
button{{margin-right:6px;padding:4px 10px;cursor:pointer}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:8px;text-align:left;border-bottom:1px solid #ddd}}
th{{background:#fafafa}}</style>
<script>
function _show(k){{document.querySelectorAll('tr[data-k]').forEach(function(r){{
r.style.display=(k==='all'||r.getAttribute('data-k')===k)?'':'none';}});}}
</script>
</head><body><h1>📚 Download Dashboard</h1>
<div class="card"><span class="stat success">{success_count}</span> Success / <span class="stat fail">{len(failed)}</span> Failed / <span class="stat">{unverified_count}</span> Unverified / {total} Total</div>
<p>Unverified = 文件已落盘但**未能核验为请求的那篇**（PDF 内提不出 DOI）；不计入 Success。</p>
<div class="card"><b>失败原因分布：</b> {summary_html or '（无失败）'}</div>
<div class="card">
<button onclick="_show('all')">全部</button>
<button onclick="_show('ok')">仅成功</button>
<button onclick="_show('fail')">仅失败</button>
<h2>✅ 已下载</h2><table><tr><th>DOI</th><th>标题</th><th>本地文件</th></tr>{rows_html}</table>
<h2>❌ 失败</h2><table><tr><th>DOI</th><th>标题</th><th>分类 @ 层</th><th>原因</th></tr>{failed_html}</table></div></body></html>"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        _log("dashboard_generated", path=str(html_path))
    except Exception as e:
        _logger.exception("HTML dashboard generation failed: %s", e)

# ---------------------------------------------------------------------------
# 增量导入（分块读取大 Excel）
# ---------------------------------------------------------------------------
def _parse_input_file_chunked(file_path: str, chunk_size: int = 500) -> Iterator[List[Dict[str, str]]]:
    """分块读取，避免大文件 OOM（Excel 惰性逐行，不整簿入内存）。"""
    path = Path(file_path)
    if not path.exists():
        return
    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls"):
        try:
            it = _iter_excel_rows(path)
            header = next(it, None)
            if header is None:
                return
            headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(header)]
            buf: List[Dict[str, str]] = []
            for row in it:
                if not any(c for c in row):
                    continue
                buf.append({headers[j]: str(c).strip() if c else "" for j, c in enumerate(row)})
                if len(buf) >= chunk_size:
                    yield buf
                    buf = []
            if buf:
                yield buf
        except Exception:
            pass
        return

    if suffix in (".csv", ".tsv"):
        sample = path.open("rb")
        try:
            prefix = sample.read(8192)
        finally:
            sample.close()
        encoding = None
        for candidate in ("utf-8-sig", "gb18030", "gbk", "utf-16"):
            try:
                codecs.getincrementaldecoder(candidate)(errors="strict").decode(prefix, final=False)
                encoding = candidate
                break
            except UnicodeError:
                continue
        if encoding is None:
            return
        with path.open("r", encoding=encoding, newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t" if suffix == ".tsv" else ",")
            buf = []
            for row in reader:
                if None in row:
                    raise ValueError("输入行列数超过表头")
                buf.append({str(k): str(v or "") for k, v in row.items()})
                if len(buf) >= chunk_size:
                    yield _normalize_tsv_headers(buf) if suffix == ".tsv" else buf
                    buf = []
            if buf:
                yield _normalize_tsv_headers(buf) if suffix == ".tsv" else buf
        return
    yield _parse_input_file(file_path)

# ---------------------------------------------------------------------------
# Phase 1: seed（含 OpenAlex 批量预检 + 增量导入）
# ---------------------------------------------------------------------------
def _apply_runtime_tuning(config: dict) -> None:
    """把 config 中的调优项收敛写入模块级运行时常量（D3：单一写入点）。

    仅当 config 显式提供时才覆盖全局默认值（便于测试通过 monkeypatch 修改全局变量）。
    """
    global _MAX_PDF_BYTES, _DONE_DOI_CAP, _OA_PRECHECK_LIMIT, _OA_PRECHECK_CONCURRENCY
    if "max_pdf_bytes" in config:
        _MAX_PDF_BYTES = int(config["max_pdf_bytes"])
    if "done_doi_cap" in config:
        _DONE_DOI_CAP = int(config["done_doi_cap"])
    if "oa_precheck_limit" in config:
        _OA_PRECHECK_LIMIT = int(config["oa_precheck_limit"])
    if "oa_precheck_concurrency" in config:
        _OA_PRECHECK_CONCURRENCY = int(config["oa_precheck_concurrency"])

def _seed(payload: dict) -> dict:
    config = payload.get("config", {})
    cfg_errors = _validate_config(config)
    if cfg_errors:
        return {"requests": [], "errors": [{"config": e} for e in cfg_errors], "warnings": cfg_errors}
    _reload_plugin_config()  # 外部配置热重载（mtime 变化才生效）

    # 应用配置到运行时常量（D3：收敛到单一函数）
    _apply_runtime_tuning(payload.get("config", {}))
    config = payload.get("config", {})
    # U6：新批次重置面板进度计数器
    _RUN_STATS["success"] = 0
    _RUN_STATS["failed"] = 0

    file_path = payload.get("file_path", "")
    workspace = payload.get("workspace", ".")
    _set_state_dir(workspace)
    _CANCEL_EVENT.clear()
    _state_set(_CANCEL_KEY, "false")
    try:
        _view_sync_from_run(config, workspace)
    except Exception:
        pass
    incremental = config.get("incremental", True)
    dry_run = config.get("dry_run", False)

    # 配置校验
    cfg_errors = _validate_config(config)
    if cfg_errors:
        return {"requests": [], "errors": [{"config": e} for e in cfg_errors], "warnings": cfg_errors}

    safe_input = _resolve_workspace_path(workspace, file_path)

    # 增量模式：读取已下载列表（SDK 优先，独立运行时读 workspace 文件）
    done_dois: set[str] = set()
    if incremental:
        try:
            result = _state_get(_done_key(config))
            if result and result.get("value"):
                for item in json.loads(result["value"]):
                    if isinstance(item, dict) and item.get("doi"):
                        done_dois.add(str(item["doi"]).lower())
                    elif isinstance(item, str):
                        done_dois.add(item.lower())
        except Exception:
            pass

    # 解析输入文件（分块，避免大文件 OOM）
    papers: list[dict[str, Any]] = []
    seen_rows = 0
    eligible_count = 0
    candidate_seen: set[str] = set()
    no_doi_rows = 0  # U3：无 DOI 的行显式计数，进 meta + warning（保证对账闭环）
    for chunk in _parse_input_file_chunked(str(safe_input)):
        for row in chunk:
            seen_rows += 1
            doi = _extract_doi(row)
            if not doi:
                no_doi_rows += 1
                continue
            doi_lower = doi.lower()
            if doi_lower in done_dois:
                continue
            if doi_lower in candidate_seen:
                continue
            candidate_seen.add(doi_lower)
            eligible_count += 1
            if dry_run or len(papers) < config.get("max_per_session", 50):
                papers.append({"doi": doi_lower, "row": row})
    if not papers and seen_rows == 0:
        return {"requests": [], "errors": [{"file": file_path, "reason": "empty_or_unreadable"}], "warnings": []}

    # 构建请求
    requests: list[dict] = []
    seen = set()
    issn_by_doi: dict[str, str] = {}
    # 预检名单：仅收录尚未被免费 OA 信号覆盖的 DOI（省请求）
    to_precheck: list[str] = []
    for item in papers:
        doi = item["doi"]
        if doi in seen: continue
        seen.add(doi)

        publisher = _resolve_publisher(doi)
        row = item["row"]
        title = row.get("Article Title") or row.get("Title") or ""
        authors = row.get("Author Full Names") or row.get("Authors") or ""
        year = row.get("Publication Year") or row.get("Year") or ""
        first_author = authors.split(";")[0].strip().split(",")[0].strip() if authors else "Unknown"

        # 多重 OA 信号：OpenAlex 预检 / ISSN 白名单 / 全 OA 出版商
        issn = row.get("ISSN") or row.get("issn") or ""
        issn_by_doi[doi] = str(issn)
        if not _is_known_oa(publisher or "", str(issn), False):
            to_precheck.append(doi)

        requests.append({
            "url": f"academic://paper/{doi}",
            "method": "GET",
            "meta": {"paper": {"doi": doi, "title": title, "first_author": first_author,
                              "year": year, "publisher": publisher or "unknown",
                              "authors": authors, "is_oa": False}, "source": "academic-paper-downloader"},
        })

    # 批量查 OpenAlex（仅查真正不确定的，且限量防 seed 过慢）
    oa_status = {}
    if to_precheck and config.get("level", 1) >= 2:
        to_precheck = to_precheck[:_OA_PRECHECK_LIMIT]
        oa_status = _batch_check_oa_sync(to_precheck)
        _log("oa_precheck", total=len(to_precheck), oa_count=sum(1 for v in oa_status.values() if v))

    # 把预检结果按 DOI 回填到请求的 is_oa
    warnings: list[str] = []
    if not dry_run and eligible_count > len(requests):
        warnings.append(f"超过 max_per_session={config.get('max_per_session', 50)}，仅前 {len(requests)} 篇入队，其余可在下次增量续跑")
    for r in requests:
        doi = r["meta"]["paper"]["doi"]
        publisher = r["meta"]["paper"]["publisher"]
        r["meta"]["paper"]["is_oa"] = _is_known_oa(publisher, issn_by_doi.get(doi, ""), oa_status.get(doi, False))

    # U2：Level≥2 未填 unpaywall_email 时显式提示（否则 Unpaywall 整层被跳过且用户无感知）
    if config.get("level", 1) >= 2 and not config.get("unpaywall_email"):
        warnings.append("未配置 unpaywall_email，Layer 2 的 Unpaywall OA 副本探测被跳过；"
                        "填写邮箱可显著提升 OA 论文检出率")
    # U3：无 DOI 行显式计数入 meta，保证对账闭环
    if no_doi_rows:
        warnings.append(f"{no_doi_rows} 行缺少 DOI，已跳过（无法定位文献）")

    # Dry-run 模式：仅生成计划，不下载
    if dry_run:
        plan = [{
            "doi": r["meta"]["paper"]["doi"],
            "title": r["meta"]["paper"]["title"],
            "publisher": r["meta"]["paper"]["publisher"],
            "is_oa": r["meta"]["paper"]["is_oa"],
        } for r in requests]
        _log("dry_run_plan", total=len(plan))
        return {
            "requests": [],
            "meta": {"total_rows": seen_rows, "total_papers": len(requests), "no_doi_rows": no_doi_rows,
                     "oa_precheck": sum(1 for v in oa_status.values() if v), "dry_run": True, "plan": plan},
            "errors": [], "warnings": warnings,
        }

    # 限流
    max_per_session = config.get("max_per_session", 50)
    if len(requests) > max_per_session:
        requests = requests[:max_per_session]
        warnings.append(f"超过 max_per_session={max_per_session}，仅前 {max_per_session} 篇入队")
        _log("session_limit", total=len(requests), limit=max_per_session)

    return {
        "requests": requests,
        "meta": {"total_rows": seen_rows, "total_papers": len(requests), "no_doi_rows": no_doi_rows,
                 "oa_precheck": sum(1 for v in oa_status.values() if v)},
        "errors": [], "warnings": warnings,
    }

# ---------------------------------------------------------------------------
# Layer 1: OA 直连（根据 OA 标记优先尝试）
# ---------------------------------------------------------------------------
def _build_oa_url(doi: str, cfg: dict) -> str | None:
    """根据出版商 oa_pattern 构造 PDF URL（支持 {pii}/{doi}/{doi_suffix}）。"""
    pattern = cfg.get("oa_pattern")
    if not pattern:
        return None
    if "{pii}" in pattern:
        pii = _extract_pii(doi)
        if not pii:
            return None
        return pattern.replace("{pii}", pii)
    if "{doi_suffix}" in pattern:
        suffix = doi.split("/", 1)[-1]
        return pattern.replace("{doi_suffix}", suffix)
    return pattern.replace("{doi}", doi)

def _is_known_oa(publisher: str, issn: str, openalex_flag: bool = False) -> bool:
    """多重 OA 信号：OpenAlex 预检 / OA 期刊 ISSN 白名单 / 全 OA 出版商。"""
    if openalex_flag:
        return True
    if issn and issn in _OA_JOURNALS:
        return True
    if publisher in ("mdpi", "plos", "bmc", "arxiv"):
        return True
    return False

def _try_oa_direct(doi: str, publisher: str, is_oa: bool = False) -> str | None:
    if not is_oa:
        # 非 OA 标记的论文跳过此层（节省时间）
        return None
    cfg = _PUBLISHERS.get(publisher)
    if not cfg:
        return None
    # 只构造 URL，不在此探测（下载/校验交给 _fetch_pdf，避免 PDF 被下载两遍）
    return _build_oa_url(doi, cfg)

# ---------------------------------------------------------------------------
# Layer 2: API 探测
# ---------------------------------------------------------------------------
_API_PROBE_TIMEOUT = 20

def _try_api_probe(doi: str, config: dict) -> str | None:
    """并发探测 Crossref / Unpaywall / OpenAlex，取最先返回的 OA 链接。"""

    def _crossref() -> str | None:
        try:
            from urllib.parse import quote
            body, status, _final = _host_fetch(f"https://api.crossref.org/works/{quote(str(doi), safe='')}")
            if status == 200:
                for link in json.loads(body.decode("utf-8", errors="replace")).get("message", {}).get("link", []):
                    if link.get("content-type") == "application/pdf":
                        return link.get("URL")
        except Exception:
            pass
        return None

    def _unpaywall() -> str | None:
        email = config.get("unpaywall_email", "")
        if not email:
            return None
        try:
            from urllib.parse import quote
            body, status, _final = _host_fetch(
                f"https://api.unpaywall.org/v2/{quote(str(doi), safe='')}?email={quote(str(email), safe='')}")
            if status == 200:
                data = json.loads(body.decode("utf-8", errors="replace"))
                # v0.4.0 镜像优先：仓储副本（arXiv/PMC/机构库等）零反爬，
                # 显著优于出版商 endpoint（常见 bot_blocked）。出版商链接仅作后备。
                locs = [loc for loc in (data.get("oa_locations") or []) if isinstance(loc, dict)]
                for loc in locs:
                    if loc.get("host_type") == "repository" and loc.get("url_for_pdf"):
                        return loc.get("url_for_pdf")
                loc = data.get("best_oa_location") or {}
                return loc.get("url_for_pdf")
        except Exception:
            pass
        return None

    def _openalex() -> str | None:
        try:
            from urllib.parse import quote
            body, status, _final = _host_fetch(f"https://api.openalex.org/works/doi:{quote(str(doi), safe='')}")
            if status == 200:
                data = json.loads(body.decode("utf-8", errors="replace"))
                # v0.6.3 镜像优先（与 Unpaywall 同策略）：best_oa_location.host_type ==
                # repository 的副本零反爬，优先于出版商 endpoint
                locs = [loc for loc in (data.get("locations") or []) if isinstance(loc, dict)]
                for loc in locs:
                    if loc.get("source", {}).get("host_type") == "repository" and loc.get("pdf_url"):
                        return loc.get("pdf_url")
                return data.get("open_access", {}).get("oa_url")
        except Exception:
            pass
        return None

    ex = None
    try:
        ex = ThreadPoolExecutor(max_workers=3)
        futs = [ex.submit(fn) for fn in (_crossref, _unpaywall, _openalex)]
        try:
            deadline = time.time() + _API_PROBE_TIMEOUT + 5
            for fut in as_completed(futs):
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    url = fut.result(timeout=max(0.5, min(1.0, remaining)))
                except Exception:
                    continue
                if url:
                    return url
        finally:
            # 命中即退出，不等待其余兄弟请求（子进程内允许其在后台自然结束）
            if ex is not None:
                ex.shutdown(wait=False, cancel_futures=True)
    except TimeoutError:
        pass
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------
# Cookie / 登录态（v0.9.0 明确降级）
# ---------------------------------------------------------------------------
# 宿主 SDK 不提供通用交互浏览器，也没有宿主登录会话能力；明文 Cookie 既是
# 宿主宿主边界门禁禁止的敏感 state，插件侧也无合法采集途径。
# 因此机构 Cookie 登录通道（ACS 等 auth_method=cookie/saml）在本版明确
# 降级为不可用：调用方会得到 unsupported_capability，不静默失败、不直连。


def _get_cached_cookie(config: dict) -> list[dict] | None:
    """不再读取插件 state 中的 Cookie（敏感凭证不入插件 state，宿主运行期亦拒绝）。"""
    return None


def _save_cookie(config: dict, cookies: list[dict]) -> None:
    """不再保存 Cookie（无合法采集途径；宿主会拒绝敏感 state 键）。"""
    _log("cookie_storage_disabled", level=logging.DEBUG)


def _invalidate_cookie(config: dict) -> None:
    """登录态已不可用，失效操作退化为 no-op。"""
    return None


def _login_and_capture_cookie(config: dict) -> list[dict] | None:
    """登录捕获通道已移除：宿主无交互浏览器/登录会话 SDK，明确返回 None。

    调用方应将其视为不支持的能力并降级（不可用时跳过机构层），绝不回退到
    直连浏览器或自建登录窗口。
    """
    _log("institutional_login_unsupported", level=logging.INFO,
         reason="host SDK has no browser/session capability")
    return None


# ---------------------------------------------------------------------------
# 代理池管理（v0.9.0 已降级）
# ---------------------------------------------------------------------------
# 宿主 network.fetch 不暴露代理参数，代理池/健康探测在本插件内不再生效；
# 函数保留仅为兼容旧配置形状，恒返回 None，调用方不得据此启用直连。
def _get_next_proxy(config: dict) -> str | None:
    return None

# ---------------------------------------------------------------------------
# 流式下载 + 智能重试
# ---------------------------------------------------------------------------
def _build_headers(publisher: str) -> dict:
    cfg = _PUBLISHERS.get(publisher, {})
    return {
        # v0.6.6：UA 跟随时代（2024 年初的 Chrome/124 在 2026 年是 WAF 的
        # 直接红旗——UA 新旧是反爬打分项）；真浏览器通道用原生 UA，本常量
        # 只服务 httpx 直连通道，保持与主流真浏览器一致。
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "Accept": "application/pdf,*/*;q=0.8",
        "Referer": cfg.get("home", ""),
        "Accept-Language": "en;q=0.9,zh-CN;q=0.8",
    }

class _PdfTooLarge(Exception):
    """PDF 超过大小上限（防恶意超大文件拖垮磁盘/本进程）。"""


def _fetch_pdf(pdf_url: str, headers: dict, cookies: dict | None = None, timeout: int = 60) -> tuple[bytes | None, int | None]:
    """经宿主 EgressBroker 抓取 PDF（内存返回），带大小上限。返回 (content, status_code)。

    v0.9.0：不再直连 httpx；cookies 参数仅保留调用形状（宿主无 Cookie 注入能力，
    机构登录层已明确降级），传入值不会被使用。
    """
    try:
        body, status, _final = _host_fetch(pdf_url, headers=headers)
        if status != 200:
            return None, status
        if not body:
            return None, status
        if len(body) > _MAX_PDF_BYTES:
            raise _PdfTooLarge(f"pdf exceeds limit: {len(body)} > {_MAX_PDF_BYTES}")
        if not body.lstrip()[:5] == b"%PDF-":
            return None, status
        return body, status
    except _PdfTooLarge:
        raise
    except _SdkUnavailable:
        return None, None
    except Exception:
        return None, None


def _download_with_retry(pdf_url: str, paper: dict, config: dict, cookies: dict | None = None,
                         error_class: str = "unknown", headers: dict | None = None,
                         dest: str | None = None) -> tuple[bytes | None, str]:
    """经宿主 EgressBroker 重试下载，返回 (content, 最终 error_class)。

    v0.9.0：取消插件侧流式临时文件与直连代理；dest 参数仅为兼容调用形状而保留，
    宿主 network.fetch 无流式接口，正文一次性经内存返回后交给 artifact.stream。
    """
    max_retries = config.get("retry_count", 3)
    timeout = config.get("download_timeout", 60)
    hdrs = _build_headers(paper.get("publisher", "unknown"))
    if headers:
        hdrs.update(headers)

    for attempt in range(max_retries + 1):
        try:
            content, status = _fetch_pdf(pdf_url, hdrs, cookies, timeout)
            if content:
                return content, "ok"
            publisher = paper.get("publisher", "unknown")
            free_oa = _PUBLISHERS.get(publisher, {}).get("auth_method") == "none"
            if status == 200:
                # 200 但非 PDF → 登录墙（订阅源）或反爬落地页（OA 源）
                error_class = "bot_blocked" if free_oa else "auth_required"
            else:
                error_class = _classify_error(status, None, publisher)
            _log("download_http_fail", doi=paper.get("doi"), url=pdf_url, status=status, attempt=attempt)
        except _PdfTooLarge as e:
            error_class = "too_large"
            _log("download_too_large", doi=paper.get("doi"), url=pdf_url, error=str(e), attempt=attempt)
        except Exception as e:
            error_class = _classify_error(None, str(e))
            _log("download_net_error", doi=paper.get("doi"), url=pdf_url, error=str(e), attempt=attempt)
        if attempt < max_retries:
            delay = _retry_strategy(error_class, attempt, config)
            if delay is None:
                break
            time.sleep(delay)
    return None, error_class

# ---------------------------------------------------------------------------
# PDF 下载保存（工作区内）
# ---------------------------------------------------------------------------
def _save_pdf(paper: dict, content: bytes | str, workspace: Path, source: str) -> dict | None:
    # v0.9.0：迁移到宿主 artifact.stream（不再写 workspace 本地文件）。
    # 校验与元数据提取需要在本地临时文件进行，完成后经 artifact.stream.commit 交付宿主，
    # 临时文件删除。文件名沿用既有命名/元数据重命名规则，提交给宿主的 artifact name 不含路径分隔符。
    if not isinstance(content, bytes):
        _log("pdf_save_rejected_non_bytes", doi=paper.get("doi"))
        return None
    if len(content) > _MAX_PDF_BYTES:
        return None
    papers_dir = workspace / "papers"
    _safe_mkdir(papers_dir)

    first_author = paper.get("first_author", "Unknown")
    year = paper.get("year", "")
    title = paper.get("title", "untitled")
    safe_title = re.sub(r"[^\w\s-]", "", title)[:50].strip().replace(" ", "_")
    base_name = f"{first_author}_{year}_{safe_title}.pdf"
    out_path = _unique_filename(papers_dir, base_name)

    file_size = len(content)
    out_path.write_bytes(content)

    # 单次打开：校验 + 元数据提取
    if not _validate_pdf(out_path):
        _log("pdf_validation_failed", doi=paper.get("doi"), path=str(out_path))
        try: out_path.unlink()
        except Exception as e:
            _log("swallowed_exception", level=logging.DEBUG, where="pdf_unlink_invalid", error=str(e))
        return None

    # 下载后重命名（用元数据修正，命中时复用已缓存的解析结果）
    out_path = _rename_with_metadata(paper, out_path)

    meta = _extract_pdf_meta(out_path)
    validation_level = meta.get("validation_level", "unknown")

    # DOI 交叉核对（**强校验**，issue #22 §1）：
    #   - 请求了 DOI 却**提不出** DOI ⇒ 无法证明这就是目标论文（反爬挑战页/登录页/文章落地页
    #     都提不到 DOI）。旧实现写成 `if ext_doi and req_doi and ...` ⇒ 提不到就**直接放行**，
    #     于是 Cloudflare 验证页被当成成功论文计入报告；
    #   - 提取到但与请求不一致 ⇒ 出版商发错文件，拒绝并清理。
    ext_doi = (meta.get("extracted_doi") or "").strip().lower().rstrip(".")
    req_doi = normalize_doi(paper.get("doi") or "").rstrip(".")
    verified = True
    if ext_doi and req_doi and ext_doi != req_doi:
        _log("pdf_doi_mismatch", doi=req_doi, extracted=ext_doi, path=str(out_path))
        verified = False
    if req_doi and not ext_doi:
        verified = False
        _log("pdf_doi_unverified", doi=req_doi, path=str(out_path))

    if validation_level == "header_only":
        verified = False
        if not _get_download_config().get("allow_weak_pdf_validation", True):
            out_path.unlink(missing_ok=True)
            return None

    # v0.9.0：交付宿主 artifact（受控产物），本地临时文件清理。
    artifact_info = None
    try:
        data = out_path.read_bytes()
        artifact_info = _host_save_pdf(out_path.name, data, maximum_bytes=_MAX_PDF_BYTES)
    finally:
        out_path.unlink(missing_ok=True)
    if not artifact_info:
        _log("pdf_artifact_unavailable", doi=paper.get("doi"))
        return None

    record = {
        "doi": paper.get("doi", ""), "canonical_doi": req_doi, "title": title, "authors": paper.get("authors", ""),
        "year": year, "journal": paper.get("journal", ""), "publisher": paper.get("publisher", ""),
        "pdf_url": "", "filename": out_path.name,
        # v0.9.0：宿主 artifact 引用（宿主统一管理产物；本地 workspace 不再留 PDF）。
        "artifact_id": artifact_info.get("artifact_id", ""),
        "local_path": "",
        "download_source": source, "file_size": file_size, "pdf_meta": meta,
        # 是否已核验为"请求的那篇"（DOI 交叉核对通过）。未核验仍保留文件，但不计入成功。
        "verified": verified,
        "verification": "header_only" if validation_level == "header_only" else "doi_mismatch" if ext_doi and req_doi and ext_doi != req_doi else "doi_not_found_in_pdf" if req_doi and not ext_doi else "doi_matched" if req_doi else "doi_not_requested",
        "sha256": artifact_info.get("sha256") or hashlib.sha256(content).hexdigest(),
    }
    record["download_evidence"] = build_evidence(record)
    return record

# 全局并发控制器（懒初始化）
_concurrency_controller: _ConcurrencyController | None = None

def _get_concurrency_controller(config: ConfigDict) -> _ConcurrencyController:
    global _concurrency_controller
    if _concurrency_controller is None:
        _concurrency_controller = _make_concurrency_controller(config)
    return _concurrency_controller

# ---------------------------------------------------------------------------
# Phase 2: processor（完整三层降级 + 并发控制 + 分布式锁）
# ---------------------------------------------------------------------------
def _process(payload: dict) -> dict:
    """完整三层降级 + 并发控制 + 分布式锁。"""
    config_errors = _validate_config(payload.get("config", {}))
    if config_errors:
        return {"records": [], "errors": [{"config": e} for e in config_errors]}
    _set_state_dir(payload.get("workspace", "."))
    if _cancel_requested():
        return {"records": [], "errors": [{"doi": (payload.get("paper") or {}).get("doi", ""), "error_class": "cancelled", "reason": "用户取消；已完成的增量状态保留", "retryable": False}]}
    _reload_plugin_config()  # 外部配置热重载（mtime 变化才生效）
    paper = payload.get("paper", {})
    config = payload.get("config", {})
    workspace = Path(payload.get("workspace", ".")).resolve()
    progress = payload.get("progress", {"done": 0, "total": 1})

    doi = paper.get("doi", "")

    lock = _DistributedLock(config, workspace)
    if not lock.acquire(doi):
        return {"records": [], "errors": [{"doi": doi, "reason": "already_downloading"}], "progress": progress}

    controller = _get_concurrency_controller(config)
    try:
        controller.acquire()
        try:
            try:
                result = _process_download(paper, config, workspace, progress)
            except Exception as e:
                # 单篇论文内部异常不拖垮整个批次，转为失败记录
                _log("paper_crash", doi=doi, error=str(e))
                result = {
                    "records": [],
                    "errors": [{"doi": doi, "title": paper.get("title", ""),
                                "reason": f"internal_error: {e}"}],
                    "progress": {"done": progress["done"] + 1, "total": progress["total"], "current_doi": doi},
                }
        finally:
            controller.release()
    finally:
        lock.release(doi)

    return result

def _process_download(paper: dict, config: dict, workspace: Path, progress: dict) -> dict:
    """实际下载流程（在并发配额内执行）。"""
    _set_state_dir(workspace)
    doi = paper.get("doi", "")
    publisher = paper.get("publisher", "unknown")
    is_oa = paper.get("is_oa", False)

    _cleanup_stale_tmp(workspace)
    start_time = time.time()
    layer_used = "none"
    pdf_url = None
    content = None
    error_class = "unknown"

    # 限流（按域名）
    _RATE_LIMITER.wait(publisher, config)

    # robots.txt 合规检查（Layer 1 前）
    pub_cfg = _PUBLISHERS.get(publisher, {})
    home = pub_cfg.get("home", "")
    robots_allowed = True
    if home:
        from urllib.parse import urlparse
        domain = urlparse(home).netloc
        robots_allowed = _check_robots_txt(domain)
        if not robots_allowed:
            _log("robots_txt_disallow", doi=doi, publisher=publisher, domain=domain)

    # 登录态监控（Layer 3 使用）；校园直连无需 Cookie
    cookies: dict = {}
    cookies_raw: list[dict] = []
    campus_direct = _campus_direct(config)

    def _try_layer(name: str, func, *args) -> tuple[bool, str]:
        """返回 (是否成功, 该层最终 error_class)。"""
        nonlocal pdf_url, content, layer_used
        _log("layer_start", level=logging.DEBUG, doi=doi, layer=name)
        t0 = time.time()
        local_error = "unknown"
        try:
            result = func(*args)
            if result:
                pdf_url = result
                if isinstance(result, str) and result.startswith("http"):
                    content, local_error = _download_with_retry(
                        result, paper, config, cookies, local_error)
                if content:
                    layer_used = name
                    _log("layer_success", doi=doi, layer=name, duration_ms=int((time.time() - t0) * 1000))
                    return True, "ok"
        except _PdfTooLarge:
            local_error = "pdf_too_large"
        except Exception as e:
            local_error = _classify_error(None, str(e))
            _log("layer_error", doi=doi, layer=name, error=str(e))
        _log("layer_failed", level=logging.DEBUG, doi=doi, layer=name, duration_ms=int((time.time() - t0) * 1000))
        return False, local_error

    # --- 通道计划（v0.4.0/v0.5.0→D6 数据驱动编排）---
    # 顺序 = 成本升序（权限×通道），每个通道带运行时门控；
    # 新增通道只需在 plan 里加一项，不改编排逻辑。
    # U5：域级通道画像——出版商域刚发生 bot_blocked 时，跳过该域的 http 通道直接升级。
    domain = _publisher_domain(publisher)
    profile_skip_http = _domain_http_blocked(domain)
    ctx: dict = {"ok": False, "error_class": "unknown", "saw_mismatch": False,
                 "browser_tried": False, "http_failed": False, "http_error": None}
    # 域画像本身就是通道不匹配证据：跳过 http 通道时必须同步建立升级信号，
    # 否则后续所有通道都失败后升级通道不会触发。
    if profile_skip_http:
        ctx["saw_mismatch"] = True

    def _mark(ok: bool, ec: str, browser: bool = False) -> None:
        ctx["ok"] = bool(ok)
        if ok:
            ctx["error_class"] = "ok"
        else:
            if ec in ("bot_blocked", "captcha"):
                ctx["saw_mismatch"] = True
            # v0.9.0：错误分类注释已移除机构层引用（institutional_http 层已删除）。
            if ec != "unknown" or ctx["error_class"] == "unknown":
                ctx["error_class"] = ec
        if browser and not ok:
            ctx["browser_tried"] = True

    plan: list[tuple[str, object, tuple, Callable[[], bool]]] = [
        ("oa_direct", _try_oa_direct, (doi, publisher, is_oa),
         lambda: robots_allowed and not profile_skip_http),
        ("api", _try_api_probe, (doi, config), lambda: True),
        # v0.9.0：宿主 SDK 无交互浏览器/登录会话能力，机构 Cookie 登录通道明确降级为
        # 不可用（不会静默失败：Cookie 函数只记日志并返回 None）。代理参数宿主不暴露，
        # _get_next_proxy/_PROXY_HEALTH 已降级。
    ]

    ok = False
    error_class = "unknown"
    for name, fn, args, gate in plan:
        if ctx["ok"] or not gate():
            continue
        ok, ec = _try_layer(name, fn, *args)
        _mark(ok, ec)

    error_class = ctx["error_class"] if not ctx["ok"] else "ok"
    ok = ctx["ok"]

    # U5：把通道不匹配证据写入域画像，同域后续论文跳过 http 通道直连升级
    if domain and (ctx["saw_mismatch"] or (not ok and error_class in ("bot_blocked", "captcha"))):
        _profile_channel_mismatch(domain)
    elif domain and ok and layer_used in ("oa_direct", "api"):
        _profile_channel_clear(domain)

    # D11：未知出版商全层失败时显式归类（区别于"网络抖动"类可重试失败）
    if not ok and error_class in ("unknown",) and not _PUBLISHERS.get(publisher):
        error_class = "unknown_publisher"
    # v0.9.0：OA 内容 + auth_required → bot_blocked 的调整保留（OA 不该要权限）；
    # 机构 Cookie 登录层已明确降级（宿主无交互浏览器/登录会话能力），无需再改判。

    duration_ms = int((time.time() - start_time) * 1000)
    _log("paper_finished", doi=doi, layer=layer_used, ok=bool(content), duration_ms=duration_ms,
         error_class=error_class)

    # 计算 ETA 和速度
    done = progress["done"] + 1
    total = progress["total"]
    elapsed_sec = time.time() - start_time
    speed = done / elapsed_sec if elapsed_sec > 0 else 0
    eta = (total - done) / speed if speed > 0 else 0

    # U6：面板进度推送（每篇一次，兼任 drive_loop 会话保活——宿主每读到一行输出
    # 重置会话超时，超过 ~30s 无输出会话会被回收）
    if content:
        _RUN_STATS["success"] += 1
    else:
        _RUN_STATS["failed"] += 1
    _report_view_progress(done, total, doi, eta, _RUN_STATS["success"], _RUN_STATS["failed"])

    if content:
        record = _save_pdf(paper, content, workspace, layer_used)
        if record:
            record["pdf_url"] = public_source_url(pdf_url or "")
            record["download_evidence"] = build_evidence(record, pdf_url or "", duration_ms)
            _mark_done(config, doi, record)
            return {
                "records": [record], "errors": [],
                "progress": {"done": done, "total": total, "current_doi": doi,
                             "eta_seconds": round(eta), "speed_papers_per_min": round(speed * 60, 2)},
            }
        # 实机回归发现：通道成功（error_class=ok）但 _save_pdf 校验失败（假成功防护）
        # 时，失败记录会带着 "ok" 分类落盘——显式改判为 pdf_invalid。
        if error_class == "ok":
            error_class = "pdf_invalid"
            layer_used = layer_used or "unknown"

    _mark_failed(config, doi, layer_used, error_class, title=paper.get("title", ""),
                 first_author=paper.get("first_author", ""), year=str(paper.get("year", "")))
    return {
        "records": [],
        "errors": [{"doi": doi, "title": paper.get("title", ""), "reason": "all_layers_failed",
                    "error_reason": _failure_reason(error_class),
                    "last_layer": layer_used, "error_class": error_class}],
        "progress": {"done": done, "total": total, "current_doi": doi,
                     "eta_seconds": round(eta), "speed_papers_per_min": round(speed * 60, 2)},
    }

from functools import wraps


def _serialize_state_lists(function):
    @wraps(function)
    def wrapped(config, *args, **kwargs):
        lock = _DistributedLock(config, _STATE_DIR)
        deadline = time.monotonic() + 5
        while not lock.acquire("__state_index__"):
            if time.monotonic() >= deadline:
                raise RuntimeError("增量索引正在写入，请重试")
            time.sleep(0.01)
        try:
            return function(config, *args, **kwargs)
        finally:
            lock.release("__state_index__")
    return wrapped


@_serialize_state_lists
def _mark_done(config: dict, doi: str, record: dict | None = None) -> None:
    """记录成功论文：完整记录存 per-DOI 键（O(1)），done 列表只存 DOI 并限量。"""
    try:
        doi_lower = str(doi).lower()
        rec = record if record else {"doi": doi_lower}
        # per-DOI 完整记录，一次写入不重写全表
        _state_set(_record_key(config, doi_lower), json.dumps(rec))
        # done 列表：仅 DOI 字符串，限量防无限增长
        key = _done_key(config)
        result = _state_get(key)
        done = json.loads(result["value"]) if result and result.get("value") else []
        if not isinstance(done, list):
            done = []
        done = [d for d in done if not (
            (isinstance(d, dict) and str(d.get("doi", "")).lower() == doi_lower)
            or (isinstance(d, str) and d.lower() == doi_lower))]
        done.append(doi_lower)
        _state_set(key, json.dumps(done[-_DONE_DOI_CAP:]))
    except Exception:
        pass

def _load_done_records(config: dict) -> tuple[list, list]:
    """读取完成列表并尽力复原本地记录。返回 (records, done_list)。"""
    records: list = []
    done_list: list = []
    try:
        result = _state_get(_done_key(config))
        if result and result.get("value"):
            done_list = json.loads(result["value"])
        if not isinstance(done_list, list):
            done_list = []
        for item in done_list:
            if isinstance(item, dict):
                records.append(item)
                continue
            if isinstance(item, str):
                rec_result = _state_get(_record_key(config, item))
                if rec_result and rec_result.get("value"):
                    try:
                        rec = json.loads(rec_result["value"])
                        records.append(rec if isinstance(rec, dict) else {"doi": item})
                    except Exception:
                        records.append({"doi": item})
                else:
                    records.append({"doi": item})
    except Exception:
        return [], []
    return records, done_list

_RETRYABLE_CLASSES = {"network", "rate_limit", "server_error"}

@_serialize_state_lists
def _mark_failed(config: dict, doi: str, layer: str, error_class: str = "unknown",
                 title: str = "", first_author: str = "", year: str = "") -> None:
    """记录失败文献：结构化字段（doi/layer/error_class）+ 人类可读 reason + 可重试标记。

    v0.4.0+：冗余 first_author/year（U7）——输入文件被移动后重试成功的 PDF 仍能正确命名。
    """
    try:
        key = _failed_key(config)
        result = _state_get(key)
        failed = json.loads(result["value"]) if result and result.get("value") else []
        failed.append({
            "doi": doi,
            "title": title or "",
            "first_author": first_author or "",
            "year": year or "",
            "layer": layer,
            "error_class": error_class,
            "reason": _failure_reason(error_class),
            "retryable": error_class in _RETRYABLE_CLASSES,
            "time": time.time(),
        })
        _state_set(key, json.dumps(failed[-100:]))
    except Exception as e:
        _log("swallowed_exception", level=logging.DEBUG, where="failed_state_write", error=str(e))

_FAILURE_REASON_MAP: dict[str, str] = {
    "pdf_too_large": "PDF 超过配置大小上限，未计入成功",
    "auth_required": "需要订阅权限或登录态（当前网络无权限，或 Cookie 已失效）",
    "bot_blocked": "出版商反爬拦截（响应非 PDF 内容）",
    "pdf_invalid": "PDF 落盘校验失败（假成功防护拦截，文件未计入成功）",
    "rate_limit": "触发出版商限流（HTTP 429）",
    "server_error": "出版商服务器错误（HTTP 5xx）",
    "network": "网络不可达或请求超时",
    "captcha": "下载过程遇到人机验证",
    "robots_disallow": "robots.txt 禁止抓取该出版商 PDF 路径",
    "unknown_publisher": "出版商未收录（无法构造下载链接）",
    "internal_error": "插件内部异常",
    "unknown": "未知错误",
}

def _failure_reason(error_class: str) -> str:
    """error_class → 人类可读失败原因。"""
    return _FAILURE_REASON_MAP.get(error_class, _FAILURE_REASON_MAP["unknown"])

_BROWSER_MIGRATION_REMOVED = True

# v0.9.0：以下浏览器 / 直连 HTTP / 子进程实现已被宿主能力适配整体移除。
# 保留占位以避免外部测试误导入；真实下载仅经宿主 network.fetch/artifact.stream。
def _browser_removed_placeholder() -> None:
    return None

# ---------------------------------------------------------------------------
# Hook: after_run — 生成报告
# ---------------------------------------------------------------------------
def _reindex_rows(file_path: str) -> dict[str, dict]:
    """把输入文件重建为 {doi_lower: 行字典}，供失败重试时还原论文元数据。"""
    out: dict[str, dict] = {}
    try:
        for chunk in _parse_input_file_chunked(str(file_path)):
            for row in chunk:
                doi = _extract_doi(row)
                if doi:
                    out[doi.lower()] = row
    except Exception:
        pass
    return out


def _paper_from_failed(f: dict, rows_by_doi: dict) -> dict:
    """失败记录 → 可重试的 paper 结构（元数据优先从输入文件回查，其次失败记录冗余字段）。"""
    doi = str(f.get("doi", "")).strip().lower()
    row = rows_by_doi.get(doi, {})
    authors = str(row.get("Author Full Names") or row.get("Authors") or f.get("authors") or "")
    first_author = (authors.split(";")[0].split(",")[0].strip()
                    if authors else str(f.get("first_author") or "Unknown"))
    year = str(row.get("Publication Year") or row.get("Year") or f.get("year") or "")
    return {
        "doi": doi,
        "title": row.get("Article Title") or row.get("Title") or f.get("title", ""),
        "first_author": first_author,
        "year": year,
        "publisher": _resolve_publisher(doi),
        "authors": authors,
        "is_oa": False,
    }


def _rerun_failed(config: dict, workspace: Path, results: list, failed: list,
                  file_path: str, runner: Callable[[dict], dict], label: str) -> tuple[list, list]:
    """D4 统一失败重试执行器：重建元数据 → 逐篇 runner → 标准化失败记录。

    runner(paper) 返回 processor 形状 {"records": [...], "errors": [...]}。
    所有重试入口（机构代理补填 / 有头第二阶段 / 未来新通道）共用本循环，
    避免"改一处忘一处"的漂移（今日 done 清单覆盖事故的同类根源）。
    返回 (new_results, new_failed)——调用方用 _merge_retry 合并。
    """
    rows_by_doi = _reindex_rows(file_path) if file_path else {}
    done_dois = {str(r.get("doi", "")).lower() for r in results if isinstance(r, dict)}
    papers = [_paper_from_failed(f, rows_by_doi) for f in failed
              if isinstance(f, dict) and str(f.get("doi", "")).strip().lower() not in done_dois]
    if not papers:
        return [], []
    print(f"[academic-paper-downloader] {label}：重试 {len(papers)} 篇失败文献 ...", flush=True)
    new_results: list = []
    new_failed: list = []
    for i, paper in enumerate(papers, 1):
        if _cancel_requested():
            break
        res = runner(paper)
        ok = bool(res.get("records"))
        new_results.extend(res.get("records", []))
        for e in res.get("errors", []):
            ec = e.get("error_class", "unknown")
            new_failed.append({
                "doi": e.get("doi", paper["doi"]), "title": e.get("title", paper.get("title", "")),
                "first_author": paper.get("first_author", ""), "year": str(paper.get("year", "")),
                "layer": e.get("last_layer", "none"), "error_class": ec,
                "reason": e.get("error_reason") or _failure_reason(ec),
                "retryable": ec in _RETRYABLE_CLASSES,
                "time": time.time(),
            })
        print(f"  [{i}/{len(papers)}] {paper['doi']} {'成功' if ok else '失败'}", flush=True)
    print(f"  {label}结束：成功 {len(new_results)} / 仍失败 {len(new_failed)}", flush=True)
    return new_results, new_failed


def _merge_retry(results: list, failed: list, new_results: list, new_failed: list) -> tuple[list, list]:
    """重试结果合并：成功者并入 results 并从失败列表剔除；仍失败者以最新记录覆盖。"""
    ok_dois = {str(r.get("doi", "")).lower() for r in new_results if isinstance(r, dict)}
    newfail_by_doi = {str(f.get("doi", "")).lower(): f for f in new_failed}
    failed2 = [newfail_by_doi.get(str(f.get("doi", "")).lower(), f)
               for f in failed if str(f.get("doi", "")).lower() not in ok_dois]
    return results + new_results, failed2


def _prompt_proxy_and_retry(config: dict, workspace: Path, results: list,
                            failed: list, file_path: str = "") -> tuple[list, list, int]:
    """最终报告之前：默认网络失败时给用户补填 VPN/机构代理并自动重试（v0.3.3）。

    触发条件（全部满足才交互）：retry_prompt_proxy 开启 ∧ 有失败文献 ∧ 尚未配置代理
    （含面板选择的代理）。非交互环境（stdin 关闭/EOF/用户 Ctrl-C）→ 静默跳过，
    流程绝不因此中断。回车空输入 = 明确跳过。返回 (results, failed, retried_count)。
    """
    if _cancel_requested() or not config.get("retry_prompt_proxy", False):
        return results, failed, 0
    if not failed:
        return results, failed, 0
    inst = config.get("institution") or {}
    if inst.get("proxy_url") or inst.get("proxy_list"):
        return results, failed, 0  # 已配置代理（含面板选择）：本轮已用代理跑过，不再问
    try:
        print(f"\n[academic-paper-downloader] {len(failed)} 篇文献下载失败。"
              "若您在校外，可先连接学校 VPN，再填写机构代理后自动重试。", flush=True)
        proxy_url = input("  机构代理 proxy_url（如 http://proxy.lib.xxx.edu.cn:8080，直接回车=跳过）: ").strip()
        if not proxy_url:
            print("  已选择跳过，即将生成最终报告。", flush=True)
            return results, failed, 0
        login_url = input("  登录页 login_url（可选，回车跳过）: ").strip()
    except (EOFError, OSError, KeyboardInterrupt):
        # 非交互环境（GUI 宿主/重定向 stdin）或用户取消：不打断流程
        return results, failed, 0

    cfg2 = {**config, "institution": {**inst, "proxy_url": proxy_url,
                                      **({"login_url": login_url} if login_url else {})}}
    new_results, new_failed = _rerun_failed(
        cfg2, workspace, results, failed, file_path,
        runner=lambda paper: _process({"paper": paper, "config": cfg2,
                                       "workspace": str(workspace),
                                       "progress": {"done": 0, "total": 1}}),
        label="机构代理重试")
    results2, failed2 = _merge_retry(results, failed, new_results, new_failed)
    return results2, failed2, len(new_results)


def _deferred_headed_pass(config: dict, workspace: Path, results: list,
                          failed: list, file_path: str = "") -> tuple[list, list, int]:
    """v0.9.0：有头浏览器阶段已明确降级为不可用——宿主 SDK 不提供交互浏览器或
    登录会话能力，也不再通过 subprocess 拉起本机浏览器。这里只记录降级日志，
    不重试、不弹窗。"""
    targets = [f for f in failed if isinstance(f, dict)
               and f.get("error_class") in ("bot_blocked", "captcha", "auth_required")]
    if targets:
        _log("headed_browser_unsupported", count=len(targets))
    return results, failed, 0


def _retry_transient_pass(config: dict, workspace: Path, results: list,
                          failed: list, file_path: str = "") -> tuple[list, list, int]:
    """v0.6.6：消费 ``retryable`` 字段的设计目的——瞬时失败批末自动补一轮。

    此前 ``_RETRYABLE_CLASSES``（network/rate_limit/server_error）只写进报告
    （``retryable: true``）却没有任何逻辑读它——"可重试"是语义假象：有头轮
    只服务"需要人"的失败（bot_blocked/captcha/auth_required），而网络类失败
    （DNS 抖动、临时 5xx、限流窗口）既不弹窗也不进有头轮，**从头到尾只有一次
    机会**。本轮补上：无头、无弹窗、只跑一轮；rate_limit 类失败每篇前留
    5s 缓冲给限流窗口。
    """
    if _cancel_requested():
        return results, failed, 0
    targets = [f for f in failed if isinstance(f, dict) and f.get("retryable")]
    if not targets:
        return results, failed, 0
    orig_ec = {str(f.get("doi", "")).lower(): f.get("error_class") for f in targets}

    def runner(paper: dict) -> dict:
        if orig_ec.get(str(paper.get("doi", "")).lower()) == "rate_limit":
            time.sleep(5.0)  # 限流窗口缓冲，立即重试只会再撞
        try:
            return _process({"paper": paper, "config": config, "workspace": str(workspace),
                             "progress": {"done": 0, "total": 1}})
        except Exception:
            return {"records": [], "errors": [{"doi": paper.get("doi", ""),
                     "title": paper.get("title", ""),
                     "last_layer": "transient_retry", "error_class": "network"}]}

    # v0.9.0：浏览器层已降级（宿主无交互浏览器/登录会话），瞬时失败重试不再有
    # 有头预算并发冲突，无需浏览器全局锁。
    new_results, new_failed = _rerun_failed(config, workspace, results, targets,
                                            file_path, runner, "瞬时失败重试")
    results2, failed2 = _merge_retry(results, failed, new_results, new_failed)
    return results2, failed2, len(new_results)


def _after_run(payload: dict) -> dict:
    """下载完成后生成汇总报告（含成功论文明细）。

    v0.3.3：报告生成前插入"机构代理补填 + 失败重试"环节 —— 默认网络失败时不直接
    出报告收尾，给用户一次填写 VPN/机构代理（或明确跳过）的机会，重试完再出最终报告。
    结果来源：宿主/运行器显式传入 payload["results"]/["failed"] 优先，否则回退 sdk state。
    """
    workspace = Path(payload.get("workspace", ".")).resolve()
    config = payload.get("config", {})
    _set_state_dir(workspace)
    _CANCEL_EVENT.clear()
    _state_set(_CANCEL_KEY, "false")
    try:
        _view_sync_from_run(config, workspace)
    except Exception:
        pass

    if "results" in payload or "failed" in payload:
        results = list(payload.get("results") or [])
        failed = list(payload.get("failed") or [])
    else:
        results, done_list = _load_done_records(config)
        failed = []
        try:
            failed_result = _state_get(_failed_key(config))
            if failed_result and failed_result.get("value"):
                failed = json.loads(failed_result["value"])
        except Exception:
            failed = []
        if not isinstance(failed, list):
            failed = []

    # U4（部分）：面板选择的机构代理参与失败重试——GUI 用户在面板选好代理后，
    # 此处直接用该代理重跑一轮失败文献（低成本 http 通道优先，剩余反爬项再走有头）；
    # 任务配置已显式带代理时不重复（说明批处理已用代理跑过）。
    try:
        vcfg = _view_cfg()
        panel_proxy = str(vcfg.get("proxy_url", "") or "")
    except Exception:
        panel_proxy = ""
    if panel_proxy and failed and not (config.get("institution") or {}).get("proxy_url"):
        cfg2 = {**config, "institution": {**config.get("institution", {}), "proxy_url": panel_proxy}}
        new_results, new_failed = _rerun_failed(
            cfg2, workspace, results, failed, str(payload.get("file_path", "") or ""),
            runner=lambda paper: _process({"paper": paper, "config": cfg2,
                                           "workspace": str(workspace),
                                           "progress": {"done": 0, "total": 1}}),
            label="面板代理重试")
        results, failed = _merge_retry(results, failed, new_results, new_failed)

    # 两阶段第二阶段：defer_headed 时集中走一轮串行有头（bot_blocked/captcha 失败）
    results, failed, headed_saved = _deferred_headed_pass(
        config, workspace, results, failed, file_path=str(payload.get("file_path", "") or ""))

    # v0.6.6：retryable 字段的消费端——网络类瞬时失败批末自动补一轮（无头、无弹窗）
    results, failed, transient_saved = _retry_transient_pass(
        config, workspace, results, failed, file_path=str(payload.get("file_path", "") or ""))

    results, failed, retried = _prompt_proxy_and_retry(
        config, workspace, results, [f for f in failed if isinstance(f, dict)],
        file_path=str(payload.get("file_path", "") or ""))

    _generate_report(workspace, results, failed)
    # 与报告同口径：Success 只算**已核验**的记录，未核验单列（issue #22 §1）
    unverified_count = sum(1 for r in results if isinstance(r, dict) and not r.get("verified", True))
    return {
        "report_generated": True,
        "success_count": len(results) - unverified_count,
        "unverified_count": unverified_count,
        "failed_count": len(failed),
        "proxy_retried": retried,
        "headed_saved": headed_saved,
        "transient_saved": transient_saved,
    }

# ---------------------------------------------------------------------------
# robots.txt 合规检查
# ---------------------------------------------------------------------------
_ROBOTS_CACHE: dict[str, bool] = {}
_ROBOTS_CACHE_LOCK = threading.Lock()

# U5：域级通道画像——出版商域发生 bot_blocked/captcha 后，冷却期内同域论文
# 跳过 http 通道直接从浏览器通道起步，避免重复支付注定失败的探测成本。
_CHANNEL_PROFILE: dict[str, dict] = {}
_CHANNEL_PROFILE_LOCK = threading.Lock()
_CHANNEL_PROFILE_COOLDOWN_SEC = 1800.0

def _publisher_domain(publisher: str) -> str:
    home = str((_PUBLISHERS.get(publisher) or {}).get("home") or "")
    if not home:
        return ""
    try:
        from urllib.parse import urlparse
        return urlparse(home).netloc
    except Exception:
        return ""

def _domain_http_blocked(domain: str) -> bool:
    if not domain:
        return False
    with _CHANNEL_PROFILE_LOCK:
        info = _CHANNEL_PROFILE.get(domain)
    return bool(info and info.get("until", 0) > time.time())

def _profile_channel_mismatch(domain: str) -> None:
    if not domain:
        return
    with _CHANNEL_PROFILE_LOCK:
        info = _CHANNEL_PROFILE.setdefault(domain, {})
        info["count"] = info.get("count", 0) + 1
        info["until"] = time.time() + _CHANNEL_PROFILE_COOLDOWN_SEC

def _profile_channel_clear(domain: str) -> None:
    with _CHANNEL_PROFILE_LOCK:
        _CHANNEL_PROFILE.pop(domain, None)

def _check_robots_txt(domain: str) -> bool:
    """检查 robots.txt 是否允许爬取 /pdf 路径（按域缓存，进程内只请求一次）。"""
    if not domain:
        return True
    with _ROBOTS_CACHE_LOCK:
        if domain in _ROBOTS_CACHE:
            return _ROBOTS_CACHE[domain]
    allowed = True
    try:
        body, status, _final = _host_fetch(f"https://{domain}/robots.txt")
        if status == 200:
            content = body.decode("utf-8", errors="replace").lower()
            # 简单检查：是否有 Disallow: /pdf 或 Disallow: /*pdf
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    if path in ("/pdf", "/pdf/", "/*pdf", "/*pdf*"):
                        allowed = False
                        break
    except Exception:
        allowed = True
    with _ROBOTS_CACHE_LOCK:
        _ROBOTS_CACHE[domain] = allowed
    return allowed


# ---------------------------------------------------------------------------
# Hook: before_run — 代理健康检查 + 登录态预热 + robots.txt 检查
# ---------------------------------------------------------------------------
def _before_run(payload: dict) -> dict:
    """运行前检查 robots.txt；代理级探测与登录态监控已明确降级（v0.9.0）。"""
    _CANCEL_EVENT.clear()
    _state_set(_CANCEL_KEY, "false")
    config = payload.get("config", {})
    # v0.9.0：宿主 network.fetch 不暴露代理参数——代理级探测不可用（已降级），
    # 不再做代理健康检查；机构登录态监控同样不可用（宿主无登录会话能力）。
    cookie_valid = None
    if config.get("institution", {}).get("proxy_list"):
        _log("proxy_probe_unsupported",
             note="host network.fetch has no proxy support; download goes through host EgressBroker")

    # robots.txt 检查（仅对已知出版商域名）
    robots_ok = {}
    for pub_name, pub_cfg in _PUBLISHERS.items():
        home = pub_cfg.get("home", "")
        if home:
            from urllib.parse import urlparse
            domain = urlparse(home).netloc
            robots_ok[pub_name] = _check_robots_txt(domain)

    return {"proxy_healthy": True, "cookie_valid": cookie_valid, "robots_txt": robots_ok}

# ---------------------------------------------------------------------------
# 配置校验
# ---------------------------------------------------------------------------
def _campus_direct(config: dict) -> bool:
    """校园网 IP 直连模式：无需登录 Cookie，IP 即授权。"""
    return bool(config.get("campus_ip", False)) or bool((config.get("institution") or {}).get("campus_ip", False))

def _validate_config(config: dict) -> list[str]:
    if not isinstance(config, dict):
        return ["config 必须是对象"]
    errors = []
    if "allow_weak_pdf_validation" in config and not isinstance(config["allow_weak_pdf_validation"], bool):
        errors.append("allow_weak_pdf_validation 必须是布尔值")
    level = config.get("level", 1)
    if isinstance(level, bool) or not isinstance(level, int) or level not in (1, 2, 3):
        errors.append("level 必须是 1/2/3")
    integers = {"max_pdf_bytes": (1024, 1024 * 1024 * 1024), "done_doi_cap": (1, 100000),
        "oa_precheck_limit": (0, 100000), "oa_precheck_concurrency": (1, 32),
        "max_concurrent": (1, 32), "max_per_session": (1, 200),
        "http_pool_max_connections": (1, 200), "http_pool_max_keepalive": (0, 200),
        "headed_solve_timeout": (1, 3600)}
    for key, (low, high) in integers.items():
        if key not in config:
            continue
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            errors.append("max_per_session 建议 <= 200 且 >= 1" if key == "max_per_session" else f"{key} 必须是 {low}..{high} 的整数")
    for key in ("delay_min", "delay_max", "retry_base_delay", "retry_max_delay", "challenge_wait_timeout"):
        if key not in config:
            continue
        value = config[key]
        low = 1 if key == "delay_min" else 0
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= 3600:
            errors.append("delay_min 建议 >= 1 且 <= 3600" if key == "delay_min" else f"{key} 必须是 {low}..3600 的数值")
    institution = config.get("institution", {})
    if not isinstance(institution, dict):
        errors.append("institution 必须是对象")
    else:
        for key in ("proxy_url", "login_url"):
            if key in institution and not isinstance(institution[key], str):
                errors.append(f"institution.{key} 必须是字符串")
        if "proxy_list" in institution and (not isinstance(institution["proxy_list"], list) or any(not isinstance(p, str) for p in institution["proxy_list"])):
            errors.append("institution.proxy_list 必须是字符串列表")
    return errors

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# View 面板（v0.9.0）：任务控制中心
#
# v0.9.0 起：宿主 SDK 不提供交互浏览器或宿主登录会话能力，宿主边界审计也禁止
# 插件把 Cookie/会话/凭据写入插件 state。因此机构登录捕获与代理级探测**明确
# 降级为不支持**：面板仅保留进度/取消与说明文案；机构代理字段保留为展示项，
# 但宿主 network.fetch 不应用该配置（请求一律经宿主 EgressBroker）。
# 不再弹出有头 Chromium 窗口，也不再捕获或存储任何 Cookie。
# ---------------------------------------------------------------------------
_VIEW_KEY = "apd_view_cfg"
_VIEW_ID = "academic-paper-downloader.main"
# U6：批处理计数器（面板进度用），_seed 时重置
_RUN_STATS: dict = {"success": 0, "failed": 0}
_CANCEL_EVENT = threading.Event()
_CANCEL_KEY = "apd_cancel_requested"


def _cancel_requested() -> bool:
    # Shared host state bridges view and processing subprocess sessions.
    result = _state_get(_CANCEL_KEY)
    if isinstance(result, dict) and result.get("value") == "true":
        return True
    return _CANCEL_EVENT.is_set()

def _report_view_progress(done: int, total: int, current_doi: str, eta_seconds: float,
                          success: int, failed: int) -> None:
    """U6：向宿主面板推送批处理进度（view.progress，协议 v1）。

    仅宿主 SDK 可用时生效（独立运行 no-op）。字段面与 broker 白名单一致
    （done/total/eta_seconds/success/failed 强转，current_doi 字符串）。
    每篇调用一次，兼任 drive_loop 会话保活（宿主每读到一行输出重置会话超时）。
    """
    try:
        import omnicrawler_sdk
        omnicrawler_sdk.call("view.progress", {
            "done": int(done), "total": int(total),
            "current_doi": str(current_doi or ""),
            "eta_seconds": round(float(eta_seconds or 0), 1),
            "success": int(success), "failed": int(failed),
        })
    except Exception:
        pass

def _view_cfg() -> dict:
    result = _state_get(_VIEW_KEY)
    try:
        if result and result.get("value"):
            data = json.loads(result["value"])
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"login_url": "", "proxy_url": "", "workspace": "", "message": "就绪"}

def _view_cfg_save(data: dict) -> None:
    _state_set(_VIEW_KEY, json.dumps(data, ensure_ascii=False))

def _view_sync_from_run(config: dict, workspace) -> None:
    """运行时把任务配置同步给面板（登录页/代理/workspace），供面板按钮复用。

    ★ Cookie 的 state 键按 proxy_url 哈希分键——面板登录与任务下载需使用同一
    代理设置才能命中同一键；本同步保证"跑过任务再点面板"时两者一致。
    """
    data = _view_cfg()
    inst = config.get("institution", {}) or {}
    changed = False
    for key in ("login_url", "proxy_url"):
        if inst.get(key) and inst.get(key) != data.get(key):
            data[key] = inst[key]
            changed = True
    # U4：任务配置里的 proxy_list 同步给面板（select 组件供 GUI 用户选择）
    if inst.get("proxy_list"):
        data["proxy_list"] = list(inst["proxy_list"])
    ws = str(workspace or "")
    if ws and ws != data.get("workspace"):
        data["workspace"] = ws
        changed = True
    if changed:
        _view_cfg_save(data)

def _view_cookie_status() -> str:
    # v0.9.0：机构登录捕获已明确降级——宿主 SDK 无交互浏览器/登录会话能力，
    # 且宿主边界审计禁止插件把 Cookie 写入插件 state。面板如实展示不支持，
    # 不再读取任何历史 Cookie 缓存。
    return "机构登录不支持（v0.9.0 起：宿主无交互浏览器能力，Cookie 不存储）"

def _view_components() -> list:
    data = _view_cfg()
    # v0.9.0：登录窗口/清除登录态按钮移除；机构代理字段保留为只读展示（宿主
    # network.fetch 不应用代理配置，请求一律经宿主 EgressBroker）。
    return [
        {"type": "label", "id": "status", "label": "登录态", "text": _view_cookie_status()},
        {"type": "label", "id": "capability-note", "label": "能力说明",
         "text": "0.9.0 起经宿主 EgressBroker 下载；机构登录/代理绕行已明确降级为不支持。"},
        {"type": "text", "id": "proxy-input", "label": "机构代理（仅展示，宿主不应用）",
         "value": data.get("proxy_url", ""),
         "placeholder": "（宿主不应用代理配置，下载经 EgressBroker）",
         "maxlength": 512, "action": "configure-proxy"},
        {"type": "button", "id": "refresh", "label": "刷新状态", "action": "refresh"},
        {"type": "label", "id": "message", "label": "消息", "text": str(data.get("message", "就绪"))},
        {"type": "button", "id": "cancel-downloads", "label": "取消后续下载", "action": "cancel-downloads"},
    ]

def _view() -> dict:
    return {"view_id": _VIEW_ID, "title": "论文下载 · 登录中心",
            "preferred_zone": "right", "movable": True, "resizable": True, "floatable": True,
            "default_width": 420, "default_height": 440, "minimum_width": 280,
            "minimum_height": 280, "components": _view_components()}

def _view_open_login() -> dict:
    """v0.9.0：登录窗口已明确降级为不支持——宿主 SDK 无交互浏览器/登录会话
    能力，宿主边界审计禁止插件把 Cookie 写入插件 state。返回明确降级信息，
    不弹窗、不启动任何浏览器。"""
    _log("institutional_login_unsupported", surface="view")
    return {"view": _view(),
            "message": "机构登录不支持（0.9.0 起）：宿主无交互浏览器能力，Cookie 不存储。"}

def _view_action(payload: dict) -> dict:
    action = str((payload or {}).get("action", ""))
    value = str(((payload or {}).get("payload") or {}).get("value", "")).strip()[:512]
    if action == "cancel-downloads":
        _CANCEL_EVENT.set()
        _state_set(_CANCEL_KEY, "true")
        return {"view": _view(), "message": "已请求取消：当前网络操作完成后停止，已完成记录可续跑"}
    if action == "open-login":
        return _view_open_login()
    if action == "configure-proxy":
        # v0.9.0：仅保留展示。宿主 network.fetch 不应用代理配置，下载一律经
        # 宿主 EgressBroker；保存值仅用于面板展示与既有配置兼容。
        data = _view_cfg()
        data["proxy_url"] = value
        _view_cfg_save(data)
        msg = (f"机构代理已记录（宿主不应用，下载经 EgressBroker）：{value}" if value
               else "机构代理已清空（下载经宿主 EgressBroker）")
        return {"view": _view(), "message": msg}
    if action == "configure-login-url":
        # U4：面板填写的登录页供"打开登录窗口"使用
        data = _view_cfg()
        data["login_url"] = value
        _view_cfg_save(data)
        msg = f"登录页已更新：{value}" if value else "登录页已清空"
        return {"view": _view(), "message": msg}
    if action == "choose-proxy":  # 兼容旧 select 动作（已由 text 取代）
        data = _view_cfg()
        data["proxy_url"] = value
        _view_cfg_save(data)
        return {"view": _view(), "message": f"已选择机构代理：{value or '无'}"}
    if action == "clear-login":
        data = _view_cfg()
        _invalidate_cookie({"institution": {"proxy_url": data.get("proxy_url", "")}})
        data["message"] = "登录态已清除"
        _view_cfg_save(data)
        return {"view": _view(), "message": data["message"]}
    if action == "refresh":
        return {"view": _view()}
    return {"view": _view(), "message": f"未知操作: {action}"}

def handle(operation: str, payload: dict) -> dict:
    if operation == "source.seed": return _seed(payload)
    if operation == "processor.process": return _process(payload)
    if operation == "hook.after_run":
        return _after_run(payload)
    if operation == "hook.before_run": return _before_run(payload)
    if operation == "view.describe": return {"view": _view()}
    if operation == "view.action": return _view_action(payload)
    return {"error": "unsupported_operation", "operation": str(operation)}
