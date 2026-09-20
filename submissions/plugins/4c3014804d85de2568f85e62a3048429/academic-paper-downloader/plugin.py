"""Academic Paper Downloader: 三层降级批量下载学术论文 PDF.

完整优化版：并发下载、OpenAlex批量预检、批量报告、增量导入、
多格式输入、智能重试、下载后重命名、代理健康检查、登录态监控、
分布式锁、配置热重载、实时进度看板。

完全自包含：仅使用相对路径，所有文件操作限定在插件工作区内。
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import logging
import os
import random
import re
import shutil
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
from typing import Generator
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import Union
from typing import Iterator

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    yaml = None
    _HAS_YAML = False

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

try:
    import xlrd
    _HAS_XLRD = True
except ImportError:
    xlrd = None
    _HAS_XLRD = False

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
    "version": "0.3.0",
    "api_version": 1,
    "description": "从 Web of Science 导出文件批量下载论文 PDF，全优化版",
    "plugin_types": ["source", "processor", "hook"],
    "permissions": ["network:scoped", "records:read", "state:read", "state:write", "secrets:read", "files:read"],
    "domains": [
        "api.crossref.org", "api.unpaywall.org", "api.openalex.org",
        "www.sciencedirect.com", "link.springer.com", "pubs.acs.org",
        "pubs.aip.org", "pubs.rsc.org", "onlinelibrary.wiley.com",
        "journals.aps.org", "ieeexplore.ieee.org", "www.mdpi.com",
        "arxiv.org",
    ],
    "input_files": ["*.xlsx", "*.xls", "*.tsv", "*.ris", "*.bib", "*.csv", "*.json"],
    "dependencies": [
        {"name": "httpx", "version": ">=0.27,<1.0", "license": "BSD-3-Clause"},
        {"name": "yaml", "version": ">=5.4,<7.0", "license": "MIT"},
        {"name": "openpyxl", "version": ">=3.0,<4.0", "license": "MIT"},
        {"name": "pdfplumber", "version": ">=0.10,<1.0", "license": "MIT"},
        {"name": "pypdf", "version": ">=3.0,<4.0", "license": "BSD-3-Clause"},
        {"name": "playwright", "version": ">=1.30,<2.0", "license": "Apache-2.0"},
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
        """探测代理是否可用。"""
        if config is None:
            config = {}
        now = time.time()
        check_interval = int(_get_config_value(config, "proxy_check_interval_sec", 60))
        last = self._health.get(proxy, {}).get("last_check", 0)
        if now - last < check_interval:
            return not self._circuit_breaker.get(proxy, False)

        try:
            import httpx
            start = time.time()
            if proxy:
                client = httpx.Client(proxy=proxy, timeout=10)
                try:
                    resp = client.get("https://api.openalex.org/")
                finally:
                    client.close()
            else:
                resp = httpx.get("https://api.openalex.org/", timeout=10)
            latency_ms = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                latencies = self._health.get(proxy, {}).get("latencies", [])
                latencies.append(latency_ms)
                if len(latencies) > 100:
                    latencies = latencies[-100:]
                self._health[proxy] = {"score": 100, "failures": 0, "last_check": now, "latencies": latencies}
                self._circuit_breaker[proxy] = False
                return True
        except Exception:
            pass

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
    def __init__(self, config: dict) -> None:
        self._config = config
        self._key = f"apd_lock_{hashlib.md5(str(config).encode()).hexdigest()[:8]}"

    def acquire(self, doi: str, timeout: int = 300) -> bool:
        """尝试获取锁，超时返回 False。"""
        try:
            import omnicrawler_sdk
            lock_key = f"{self._key}_{doi.lower()}"
            result = omnicrawler_sdk.call("state.get", {"key": lock_key})
            if result and result.get("value"):
                locked_at = float(result["value"])
                if time.time() - locked_at < timeout:
                    time.sleep(random.uniform(0, 0.3))  # 抖动，避免多实例蜂拥
                    return False  # 已被锁定
            omnicrawler_sdk.call("state.set", {"key": lock_key, "value": str(time.time())})
            return True
        except Exception:
            return True  # 锁不可用时降级为允许下载

    def release(self, doi: str) -> None:
        """释放锁。"""
        try:
            import omnicrawler_sdk
            lock_key = f"{self._key}_{doi.lower()}"
            omnicrawler_sdk.call("state.delete", {"key": lock_key})
        except Exception:
            pass

    @staticmethod
    def cleanup_stale_locks(config: dict, max_age: int = 3600) -> int:
        """清理过期的锁（TTL 自动过期）。返回清理数量。"""
        try:
            import omnicrawler_sdk
            prefix = f"apd_lock_{hashlib.md5(str(config).encode()).hexdigest()[:8]}_"
            # 注意：state 存储不支持前缀查询，这里仅作演示
            # 实际需要 state 存储支持 scan/keys 操作
            return 0
        except Exception:
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
            import omnicrawler_sdk
            result = omnicrawler_sdk.call("state.get", {"key": _cookie_key(self._config)})
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
            import omnicrawler_sdk
            result = omnicrawler_sdk.call("state.get", {"key": _cookie_key(self._config)})
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
    elif error_class == "bot_blocked":
        # OA 源反爬 403：短暂重试一次即可，不触发重登
        return base if attempt == 0 else None
    elif error_class == "captcha":
        # 验证码：等待后重试
        return min(base * 2, 30.0)
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
# DOI 解析
# ---------------------------------------------------------------------------
def _extract_doi(row: dict[str, str]) -> str | None:
    doi = (row.get("DOI") or "").strip()
    if doi and "/" in doi: return doi
    link = (row.get("DOI Link") or "").strip()
    if "doi.org/" in link: return link.split("doi.org/", 1)[-1].strip()
    for val in row.values():
        if isinstance(val, str) and "10." in val:
            m = re.search(r"(10\.\d{4,}/[^\s]+)", val)
            if m: return m.group(1).rstrip(")")
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
        except Exception: pass

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
    try:
        import pdfplumber
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
        return True, meta
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if len(reader.pages) == 0 or reader.is_encrypted:
            return False, {}
        return True, {}
    except Exception:
        pass
    # 两个 PDF 解析库均不可用（或文件损坏）时退化为魔数校验，
    # 避免在最小环境里把已成功下载的 PDF 误判删除
    try:
        if path.read_bytes()[:1024].lstrip().startswith(b"%PDF"):
            return True, {}
        return False, {}
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
    """单个 DOI 查询 OpenAlex OA 状态，返回 (doi, is_oa)。"""
    if not _HAS_HTTPX:
        return doi, False
    try:
        resp = httpx.get(
            "https://api.openalex.org/works",
            params={"filter": f"doi:{doi}", "select": "id,doi,open_access", "per-page": "1"},
            timeout=30,
            headers={"User-Agent": "academic-paper-downloader/0.3.0 (mailto:plugin-owner@example.com)"},
        )
        if resp.status_code != 200:
            return doi, False
        for item in resp.json().get("results", []):
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
                writer.writerow([_csv_safe(r.get("doi","")), _csv_safe(r.get("title","")),
                               _csv_safe(r.get("authors","")), _csv_safe(r.get("year","")),
                               _csv_safe(r.get("journal","")), _csv_safe(r.get("publisher","")),
                               _csv_safe(r.get("download_source","")), _csv_safe(r.get("local_path","")),
                               _csv_safe(r.get("file_size","")), "SUCCESS", ""])
            for f_item in failed:
                writer.writerow([_csv_safe(f_item.get("doi","")), _csv_safe(f_item.get("title","")),
                               "", "", "", "", "", "", "", "FAILED", _csv_safe(f_item.get("reason",""))])
        _log("report_generated", path=str(csv_path))
    except Exception as e:
        _logger.exception("CSV report generation failed: %s", e)

    # HTML 看板
    html_path = report_dir / f"dashboard_{timestamp}.html"
    try:
        total = len(results) + len(failed)
        success_count = len(results)
        rows_html = ''.join(
            f'<tr><td>{_esc(r.get("doi",""))}</td><td>{_esc(r.get("title",""))}</td>'
            f'<td>{_esc(r.get("local_path",""))}</td></tr>' for r in results)
        failed_html = ''.join(
            f'<tr><td>{_esc(f.get("doi",""))}</td><td>{_esc(f.get("reason",""))}</td></tr>' for f in failed)
        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Download Dashboard</title>
<style>body{{font-family:sans-serif;margin:20px;background:#f5f5f5}}
.card{{background:#fff;border-radius:8px;padding:20px;margin:10px;box-shadow:0 2px 4px rgba(0,0,0,.1)}}
.success{{color:#2e7d32}} .fail{{color:#c62828}} .stat{{font-size:2em;font-weight:bold}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:8px;text-align:left;border-bottom:1px solid #ddd}}</style>
</head><body><h1>📚 Download Dashboard</h1>
<div class="card"><span class="stat success">{success_count}</span> Success / <span class="stat fail">{len(failed)}</span> Failed / {total} Total</div>
<div class="card"><h2>✅ 已下载</h2><table>{rows_html}</table></div>
<div class="card"><h2>❌ 失败</h2><table>{failed_html}</table></div></body></html>"""
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

    # 非 Excel 直接返回全量
    yield _parse_input_file(file_path)

# ---------------------------------------------------------------------------
# Phase 1: seed（含 OpenAlex 批量预检 + 增量导入）
# ---------------------------------------------------------------------------
def _seed(payload: dict) -> dict:
    _reload_plugin_config()  # 外部配置热重载（mtime 变化才生效）
    
    # 应用配置到运行时常量
    global _MAX_PDF_BYTES, _DONE_DOI_CAP, _OA_PRECHECK_LIMIT, _OA_PRECHECK_CONCURRENCY
    config = payload.get("config", {})
    # 仅当 config 显式提供时才覆盖全局默认值（便于测试通过 monkeypatch 修改全局变量）
    if "max_pdf_bytes" in config:
        _MAX_PDF_BYTES = int(config["max_pdf_bytes"])
    if "done_doi_cap" in config:
        _DONE_DOI_CAP = int(config["done_doi_cap"])
    if "oa_precheck_limit" in config:
        _OA_PRECHECK_LIMIT = int(config["oa_precheck_limit"])
    if "oa_precheck_concurrency" in config:
        _OA_PRECHECK_CONCURRENCY = int(config["oa_precheck_concurrency"])
    
    file_path = payload.get("file_path", "")
    workspace = payload.get("workspace", ".")
    incremental = config.get("incremental", True)
    dry_run = config.get("dry_run", False)

    # 配置校验
    cfg_errors = _validate_config(config)
    if cfg_errors:
        return {"requests": [], "errors": [{"config": e} for e in cfg_errors], "warnings": cfg_errors}

    safe_input = _resolve_workspace_path(workspace, file_path)

    # 增量模式：读取已下载列表
    done_dois: set[str] = set()
    if incremental:
        try:
            import omnicrawler_sdk
            result = omnicrawler_sdk.call("state.get", {"key": _done_key(config)})
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
    for chunk in _parse_input_file_chunked(str(safe_input)):
        for row in chunk:
            seen_rows += 1
            doi = _extract_doi(row)
            if not doi:
                continue
            doi_lower = doi.lower()
            if doi_lower in done_dois:
                continue
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
    for r in requests:
        doi = r["meta"]["paper"]["doi"]
        publisher = r["meta"]["paper"]["publisher"]
        r["meta"]["paper"]["is_oa"] = _is_known_oa(publisher, issn_by_doi.get(doi, ""), oa_status.get(doi, False))

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
            "meta": {"total_rows": seen_rows, "total_papers": len(requests), "oa_precheck": sum(1 for v in oa_status.values() if v), "dry_run": True, "plan": plan},
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
        "meta": {"total_rows": seen_rows, "total_papers": len(requests), "oa_precheck": sum(1 for v in oa_status.values() if v)},
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
    if publisher in ("mdpi", "arxiv"):
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
        if not _HAS_HTTPX:
            return None
        try:
            resp = httpx.get(f"https://api.crossref.org/works/{doi}", timeout=_API_PROBE_TIMEOUT)
            if resp.status_code == 200:
                for link in resp.json().get("message", {}).get("link", []):
                    if link.get("content-type") == "application/pdf":
                        return link.get("URL")
        except Exception:
            pass
        return None

    def _unpaywall() -> str | None:
        email = config.get("unpaywall_email", "")
        if not email or not _HAS_HTTPX:
            return None
        try:
            resp = httpx.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": email}, timeout=_API_PROBE_TIMEOUT)
            if resp.status_code == 200:
                loc = resp.json().get("best_oa_location") or {}
                return loc.get("url_for_pdf")
        except Exception:
            pass
        return None

    def _openalex() -> str | None:
        if not _HAS_HTTPX:
            return None
        try:
            resp = httpx.get(f"https://api.openalex.org/works/doi:{doi}", timeout=_API_PROBE_TIMEOUT)
            if resp.status_code == 200:
                return resp.json().get("open_access", {}).get("oa_url")
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
# Cookie 管理
# ---------------------------------------------------------------------------
def _get_cached_cookie(config: dict) -> list[dict] | None:
    try:
        import omnicrawler_sdk
        result = omnicrawler_sdk.call("state.get", {"key": _cookie_key(config)})
        if result and result.get("value"):
            cookies = json.loads(result["value"])
            now = time.time()
            for c in cookies:
                exp = c.get("expires", -1)
                if exp > 0 and exp < now: return None
            return cookies
    except Exception: pass
    return None

def _save_cookie(config: dict, cookies: list[dict]) -> None:
    try:
        import omnicrawler_sdk
        omnicrawler_sdk.call("state.set", {"key": _cookie_key(config), "value": json.dumps(cookies)})
    except Exception: pass

def _invalidate_cookie(config: dict) -> None:
    try:
        import omnicrawler_sdk
        omnicrawler_sdk.call("state.delete", {"key": _cookie_key(config)})
    except Exception: pass

def _login_and_capture_cookie(config: dict) -> list[dict] | None:
    inst = config.get("institution", {})
    login_url = inst.get("login_url", "")
    if not login_url: return None
    proxy_url = _get_next_proxy(config)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, proxy={"server": proxy_url} if proxy_url else None)
            context = browser.new_context()
            page = context.new_page()
            page.goto(login_url)
            page.wait_for_url("**/*", timeout=120000)
            _solve_captcha_if_present(page)
            cookies = context.cookies()
            browser.close()
            if cookies:
                _save_cookie(config, cookies)
                return cookies
    except Exception: pass
    return None

def _solve_captcha_if_present(page: Any) -> bool:
    """探测验证码（仅上报；OCR 由宿主能力代理解析，subprocess 不 import 宿主核心）。"""
    try:
        captcha_selectors = [
            "img[id*='captcha']", "img[class*='captcha']",
            "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']",
            "#captcha-img", ".captcha-image"
        ]
        for sel in captcha_selectors:
            el = page.query_selector(sel)
            if el:
                _log("captcha_detected", selector=sel)
                return False
        return False
    except Exception:
        return False

# ---------------------------------------------------------------------------
# 代理池管理
# ---------------------------------------------------------------------------
def _get_next_proxy(config: dict) -> str | None:
    proxy_list = config.get("institution", {}).get("proxy_list", [])
    if not proxy_list:
        return config.get("institution", {}).get("proxy_url")
    try:
        import omnicrawler_sdk
        key = f"apd_proxy_idx_{hashlib.md5(str(config).encode()).hexdigest()[:8]}"
        result = omnicrawler_sdk.call("state.get", {"key": key})
        idx = int(result.get("value", "0")) if result else 0
        proxy = _PROXY_HEALTH.get_best_proxy(proxy_list) or proxy_list[idx % len(proxy_list)]
        omnicrawler_sdk.call("state.set", {"key": key, "value": str((idx + 1) % len(proxy_list))})
        return proxy
    except Exception:
        return proxy_list[0] if proxy_list else None

# ---------------------------------------------------------------------------
# 流式下载 + 智能重试
# ---------------------------------------------------------------------------
def _build_headers(publisher: str) -> dict:
    cfg = _PUBLISHERS.get(publisher, {})
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/pdf,*/*;q=0.8",
        "Referer": cfg.get("home", ""),
        "Accept-Language": "en;q=0.9,zh-CN;q=0.8",
    }

class _PdfTooLarge(Exception):
    """PDF 超过大小上限（防恶意超大文件拖垮磁盘/本进程）。"""

# 共享 HTTP 客户端（连接池复用，线程安全）
_HTTP_CLIENT: httpx.Client | None = None
_HTTP_CLIENT_LOCK = threading.Lock()


def _get_http_client() -> httpx.Client:
    global _HTTP_CLIENT
    config = _get_download_config()
    with _HTTP_CLIENT_LOCK:
        if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
            max_conn = int(_get_config_value(config, "http_pool_max_connections", 20))
            max_keepalive = int(_get_config_value(config, "http_pool_max_keepalive", 10))
            _HTTP_CLIENT = httpx.Client(
                timeout=60.0,
                limits=httpx.Limits(max_connections=max_conn, max_keepalive_connections=max_keepalive),
                follow_redirects=True,
            )
        return _HTTP_CLIENT


def _fetch_pdf(pdf_url: str, headers: dict, cookies: dict, timeout: int = 60) -> tuple[bytes | None, int | None]:
    """内存下载（供最小链路复用），带大小上限。返回 (content, status_code)。"""
    if not _HAS_HTTPX:
        return None, None
    client = _get_http_client()
    try:
        with client.stream("GET", pdf_url, headers=headers, cookies=cookies, timeout=timeout) as resp:
            if resp.status_code != 200:
                return None, resp.status_code
            ct = resp.headers.get("content-type", "")
            if "pdf" not in ct:
                return None, resp.status_code
            chunks = []
            total = 0
            for chunk in resp.iter_bytes(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_PDF_BYTES:
                    raise _PdfTooLarge(f"pdf exceeds limit: {total} > {_MAX_PDF_BYTES}")
                chunks.append(chunk)
            return b"".join(chunks), resp.status_code
    except _PdfTooLarge:
        raise
    except Exception:
        return None, None


def _stream_pdf(pdf_url: str, headers: dict, cookies: dict, timeout: int, dest: Path) -> tuple[Path | None, int | None]:
    """流式写到临时文件（正文不驻留内存），超限即中断清理。返回 (path, status_code)。"""
    if not _HAS_HTTPX:
        return None, None
    client = _get_http_client()
    try:
        with client.stream("GET", pdf_url, headers=headers, cookies=cookies, timeout=timeout) as resp:
            if resp.status_code != 200:
                return None, resp.status_code
            ct = resp.headers.get("content-type", "")
            if "pdf" not in ct:
                return None, resp.status_code
            total = 0
            try:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > _MAX_PDF_BYTES:
                            raise _PdfTooLarge(f"pdf exceeds limit: {total} > {_MAX_PDF_BYTES}")
                        f.write(chunk)
            except _PdfTooLarge:
                try:
                    dest.unlink()
                except Exception:
                    pass
                return None, None
            if total == 0:
                try:
                    dest.unlink()
                except Exception:
                    pass
                return None, resp.status_code
            return dest, resp.status_code
    except _PdfTooLarge:
        try:
            dest.unlink()
        except Exception:
            pass
        return None, None
    except Exception:
        return None, None

def _download_with_retry(pdf_url: str, paper: dict, config: dict, cookies: dict,
                         error_class: str = "unknown", headers: dict | None = None,
                         dest: str | None = None) -> tuple[bytes | None | str, str]:
    """重试下载，返回 (content 或 临时文件路径, 最终 error_class)。"""
    max_retries = config.get("retry_count", 3)
    timeout = config.get("download_timeout", 60)
    hdrs = _build_headers(paper.get("publisher", "unknown"))
    if headers:
        hdrs.update(headers)

    # 设置下载配置上下文（供 _stream_pdf/_fetch_pdf 使用）
    _set_download_config(config)

    for attempt in range(max_retries + 1):
        try:
            if dest:
                out, status = _stream_pdf(pdf_url, hdrs, cookies, timeout, Path(dest))
                if out is not None:
                    return str(out), "ok"
            else:
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
    papers_dir = workspace / "papers"
    _safe_mkdir(papers_dir)

    first_author = paper.get("first_author", "Unknown")
    year = paper.get("year", "")
    title = paper.get("title", "untitled")
    safe_title = re.sub(r"[^\w\s-]", "", title)[:50].strip().replace(" ", "_")
    base_name = f"{first_author}_{year}_{safe_title}.pdf"
    out_path = _unique_filename(papers_dir, base_name)

    # 支持 bytes（内存下载）或临时文件路径（流式下载：移至工作区后删除临时源）
    file_size = 0
    if isinstance(content, (str, os.PathLike)):
        tmp = Path(content)
        if not tmp.is_file():
            return None
        try:
            shutil.move(str(tmp), str(out_path))
        except Exception:
            return None
        file_size = out_path.stat().st_size
    else:
        out_path.write_bytes(content)
        file_size = len(content)

    # 单次打开：校验 + 元数据提取
    if not _validate_pdf(out_path):
        _log("pdf_validation_failed", doi=paper.get("doi"), path=str(out_path))
        try: out_path.unlink()
        except Exception: pass
        return None

    # 下载后重命名（用元数据修正，命中时复用已缓存的解析结果）
    out_path = _rename_with_metadata(paper, out_path)

    meta = _extract_pdf_meta(out_path)

    # DOI 交叉核对：PDF 首页提取到的 DOI 与请求不一致 → 出版商发错文件，拒绝并清理
    ext_doi = (meta.get("extracted_doi") or "").strip().lower().rstrip(".")
    req_doi = (paper.get("doi") or "").strip().lower().rstrip(".")
    if ext_doi and req_doi and ext_doi != req_doi:
        _log("pdf_doi_mismatch", doi=req_doi, extracted=ext_doi, path=str(out_path))
        try: out_path.unlink()
        except Exception: pass
        return None

    return {
        "doi": paper.get("doi", ""), "title": title, "authors": paper.get("authors", ""),
        "year": year, "journal": paper.get("journal", ""), "publisher": paper.get("publisher", ""),
        "pdf_url": "", "filename": out_path.name, "local_path": str(out_path.relative_to(workspace)),
        "download_source": source, "file_size": file_size, "pdf_meta": meta,
    }

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
    _reload_plugin_config()  # 外部配置热重载（mtime 变化才生效）
    paper = payload.get("paper", {})
    config = payload.get("config", {})
    workspace = Path(payload.get("workspace", ".")).resolve()
    progress = payload.get("progress", {"done": 0, "total": 1})

    doi = paper.get("doi", "")

    lock = _DistributedLock(config)
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
    if config.get("level", 1) >= 3:
        monitor = _get_cookie_monitor(config)
        fetched = monitor.refresh_if_needed()
        if fetched:
            cookies_raw = fetched
            cookies = {c["name"]: c["value"] for c in fetched}
        if campus_direct:
            _log("campus_direct_mode", doi=doi, has_cookies=bool(fetched))

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
                    # 流式下载到工作区临时文件，正文不驻留内存
                    tmp_dir = workspace / ".tmp"
                    _safe_mkdir(tmp_dir)
                    tmp_dest = tmp_dir / f"{hashlib.md5(result.encode()).hexdigest()[:16]}.part"
                    content, local_error = _download_with_retry(
                        result, paper, config, cookies, local_error, dest=str(tmp_dest))
                elif isinstance(result, str) and os.path.exists(result):
                    # 本地临时文件（浏览器导出）
                    content = Path(result).read_bytes()
                    try:
                        Path(result).unlink()  # 清理临时 PDF，避免泄漏
                    except Exception:
                        pass
                if content:
                    layer_used = name
                    _log("layer_success", doi=doi, layer=name, duration_ms=int((time.time() - t0) * 1000))
                    return True, "ok"
        except _HttpStatusError as e:
            local_error = _classify_error(e.status, None, publisher)
            _log("layer_error", doi=doi, layer=name, error=f"http_{e.status}")
        except Exception as e:
            local_error = _classify_error(None, str(e))
            _log("layer_error", doi=doi, layer=name, error=str(e))
        _log("layer_failed", level=logging.DEBUG, doi=doi, layer=name, duration_ms=int((time.time() - t0) * 1000))
        return False, local_error

    # --- Layer 1 ---
    if robots_allowed:
        ok, error_class = _try_layer("oa_direct", _try_oa_direct, doi, publisher, is_oa)
    else:
        ok, error_class = False, "robots_disallow"
    # --- Layer 2 ---
    if not ok:
        ok, error_class = _try_layer("api", _try_api_probe, doi, config)
    # --- Layer 3 ---
    if not ok and config.get("level", 1) >= 3 and (cookies_raw or campus_direct):
        ok, http_error = _try_layer("institutional_http", _http_download_with_cookie, doi, publisher, cookies, config)
        error_class = http_error
        if not ok:
            ok, browser_error = _try_layer("institutional_browser", _browser_download, doi, publisher, cookies_raw, config)
            if browser_error != "unknown":
                error_class = browser_error
            # 认证失效 → 重新登录后重试一次（仅此前已有 Cookie 时才触发）
            if not ok and http_error == "auth_required" and cookies:
                _invalidate_cookie(config)
                _log("relogin_attempt", doi=doi, reason=http_error)
                new_cookies = _login_and_capture_cookie(config)
                if new_cookies:
                    cookies_raw = new_cookies
                    cookies = {c["name"]: c["value"] for c in new_cookies}
                    ok, error_class = _try_layer("institutional_http_retry", _http_download_with_cookie, doi, publisher, cookies, config)
                    if not ok:
                        ok, error_class = _try_layer("institutional_browser_retry", _browser_download, doi, publisher, cookies_raw, config)

    duration_ms = int((time.time() - start_time) * 1000)
    _log("paper_finished", doi=doi, layer=layer_used, ok=bool(content), duration_ms=duration_ms,
         error_class=error_class)

    # 计算 ETA 和速度
    done = progress["done"] + 1
    total = progress["total"]
    elapsed_sec = time.time() - start_time
    speed = done / elapsed_sec if elapsed_sec > 0 else 0
    eta = (total - done) / speed if speed > 0 else 0

    if content:
        record = _save_pdf(paper, content, workspace, layer_used)
        if record:
            record["pdf_url"] = pdf_url or ""
            _mark_done(config, doi, record)
            return {
                "records": [record], "errors": [],
                "progress": {"done": done, "total": total, "current_doi": doi,
                             "eta_seconds": round(eta), "speed_papers_per_min": round(speed * 60, 2)},
            }

    _mark_failed(config, doi, layer_used, error_class)
    return {
        "records": [],
        "errors": [{"doi": doi, "title": paper.get("title", ""), "reason": "all_layers_failed",
                    "last_layer": layer_used, "error_class": error_class}],
        "progress": {"done": done, "total": total, "current_doi": doi,
                     "eta_seconds": round(eta), "speed_papers_per_min": round(speed * 60, 2)},
    }

def _mark_done(config: dict, doi: str, record: dict | None = None) -> None:
    """记录成功论文：完整记录存 per-DOI 键（O(1)），done 列表只存 DOI 并限量。"""
    try:
        import omnicrawler_sdk
        doi_lower = str(doi).lower()
        rec = record if record else {"doi": doi_lower}
        # per-DOI 完整记录，一次写入不重写全表
        omnicrawler_sdk.call("state.set", {"key": _record_key(config, doi_lower), "value": json.dumps(rec)})
        # done 列表：仅 DOI 字符串，限量防无限增长
        key = _done_key(config)
        result = omnicrawler_sdk.call("state.get", {"key": key})
        done = json.loads(result["value"]) if result and result.get("value") else []
        if not isinstance(done, list):
            done = []
        done = [d for d in done if not (
            (isinstance(d, dict) and str(d.get("doi", "")).lower() == doi_lower)
            or (isinstance(d, str) and d.lower() == doi_lower))]
        done.append(doi_lower)
        omnicrawler_sdk.call("state.set", {"key": key, "value": json.dumps(done[-_DONE_DOI_CAP:])})
    except Exception:
        pass

def _load_done_records(config: dict) -> tuple[list, list]:
    """读取完成列表并尽力复原本地记录。返回 (records, done_list)。"""
    records: list = []
    done_list: list = []
    try:
        import omnicrawler_sdk
        result = omnicrawler_sdk.call("state.get", {"key": _done_key(config)})
        if result and result.get("value"):
            done_list = json.loads(result["value"])
        if not isinstance(done_list, list):
            done_list = []
        for item in done_list:
            if isinstance(item, dict):
                records.append(item)
                continue
            if isinstance(item, str):
                rec_result = omnicrawler_sdk.call("state.get", {"key": _record_key(config, item)})
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

def _mark_failed(config: dict, doi: str, layer: str, error_class: str = "unknown") -> None:
    try:
        import omnicrawler_sdk
        key = _failed_key(config)
        result = omnicrawler_sdk.call("state.get", {"key": key})
        failed = json.loads(result["value"]) if result and result.get("value") else []
        failed.append({"doi": doi, "layer": layer, "error_class": error_class, "time": time.time()})
        omnicrawler_sdk.call("state.set", {"key": key, "value": json.dumps(failed[-100:])})
    except Exception: pass

def _http_download_with_cookie(doi: str, publisher: str, cookies: dict, config: dict) -> str | None:
    cfg = _PUBLISHERS.get(publisher)
    if not cfg:
        return None
    pdf_url = _build_oa_url(doi, cfg)
    if not pdf_url:
        return None
    if not _HAS_HTTPX:
        return None
    _set_download_config(config)
    try:
        client = _get_http_client()
        headers = _build_headers(publisher)
        # 只流式读响应头校验，不下载正文（正文统一由 _download_with_retry 下载一次）
        with client.stream("GET", pdf_url, headers=headers, cookies=cookies, timeout=60) as resp:
            ct = resp.headers.get("content-type", "")
            if resp.status_code == 200 and "pdf" in ct:
                return pdf_url
            # 重定向链中出现登录页 → Cookie 已失效
            for hop in getattr(resp, "history", []) or []:
                loc = hop.headers.get("location", "").lower()
                if any(k in loc for k in ("login", "sso", "signin", "account", "auth")):
                    _invalidate_cookie(config)
                    break
            if resp.status_code in (401, 403) or (resp.status_code == 200 and "pdf" not in ct):
                _invalidate_cookie(config)
                raise _HttpStatusError(resp.status_code)
    except _HttpStatusError:
        raise
    except Exception:
        pass
    return None

class _HttpStatusError(Exception):
    """携带 HTTP 状态码的层失败，用于把该层错误分类透传给重登判定。"""
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"http_{status}")

def _normalize_cookies_for_browser(cookies: list[dict], home: str) -> list[dict]:
    """补齐 Playwright add_cookies 必需字段（name/value + url 或 domain/path）。"""
    normalized: list[dict] = []
    for c in cookies:
        if not isinstance(c, dict):
            continue
        item = dict(c)
        if not item.get("name") or item.get("value") is None:
            continue
        if not (item.get("url") or item.get("domain")):
            item["url"] = home
        item.setdefault("path", "/")
        normalized.append(item)
    return normalized

def _save_browser_download(dl) -> str | None:
    """把 Playwright 下载对象落到临时 PDF，返回本地路径。"""
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        dl.save_as(tmp.name)
        path = Path(tmp.name)
        if path.stat().st_size > 0:
            return tmp.name
        try:
            path.unlink()
        except Exception:
            pass
    except Exception:
        pass
    return None

def _browser_capture_pdf(context, page) -> str | None:
    """在浏览器会话内下载 PDF：点击 → 捕获下载事件（同页或新标签页）。"""
    selectors = [
        "a[href*='pdf']",
        "a[href*='download']",
        "a.pdf-download",
        "a[class*='pdf']",
        "button[class*='pdf']",
        "a[class*='download']",
    ]
    for sel in selectors:
        link = page.query_selector(sel)
        if not link:
            continue
        # 同页触发下载
        try:
            with page.expect_download(timeout=15000) as dl_info:
                link.click()
            return _save_browser_download(dl_info.value)
        except Exception:
            pass
        # 新标签页打开并触发下载
        try:
            with context.expect_page(timeout=15000) as page_info:
                link.click()
            popup = page_info.value
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=20000)
                with popup.expect_download(timeout=15000) as dl_info:
                    popup.wait_for_timeout(500)
                return _save_browser_download(dl_info.value)
            except Exception:
                popup.close()
        except Exception:
            pass
    # 兜底：内联渲染页面 → print to PDF
    try:
        pdf_bytes = page.pdf()
        if pdf_bytes and len(pdf_bytes) > 1000:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.close()
            Path(tmp.name).write_bytes(pdf_bytes)
            return tmp.name
    except Exception:
        pass
    return None

def _browser_download(doi: str, publisher: str, cookies: list[dict], config: dict) -> str | None:
    """浏览器层：在真实浏览器会话内完成授权下载（校园 IP 直连 / 机构 Cookie）。"""
    cfg = _PUBLISHERS.get(publisher)
    if not cfg or not cfg.get("home"):
        return None
    home = cfg["home"]
    proxy_url = _get_next_proxy(config)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, proxy={"server": proxy_url} if proxy_url else None)
            context = browser.new_context(user_agent=_build_headers(publisher)["User-Agent"], accept_downloads=True)
            if cookies:
                context.add_cookies(_normalize_cookies_for_browser(cookies, home))
            page = context.new_page()
            page.goto(f"{home}/doi/{doi}", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            _solve_captcha_if_present(page)
            result = _browser_capture_pdf(context, page)
            browser.close()
            return result
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Hook: after_run — 生成报告
# ---------------------------------------------------------------------------
def _after_run(payload: dict) -> dict:
    """下载完成后生成汇总报告（含成功论文明细）。"""
    workspace = Path(payload.get("workspace", ".")).resolve()
    config = payload.get("config", {})

    # 读取 state 中的完成/失败列表
    results, done_list = _load_done_records(config)
    failed: list = []
    try:
        import omnicrawler_sdk
        failed_result = omnicrawler_sdk.call("state.get", {"key": _failed_key(config)})
        if failed_result and failed_result.get("value"):
            failed = json.loads(failed_result["value"])
    except Exception:
        failed = []
    if not isinstance(failed, list):
        failed = []

    _generate_report(workspace, results, [f for f in failed if isinstance(f, dict)])
    return {"report_generated": True, "success_count": len(results), "failed_count": len(failed)}

# ---------------------------------------------------------------------------
# robots.txt 合规检查
# ---------------------------------------------------------------------------
def _check_robots_txt(domain: str) -> bool:
    """检查 robots.txt 是否允许爬取 /pdf 路径。"""
    try:
        import httpx
        resp = httpx.get(f"https://{domain}/robots.txt", timeout=5)
        if resp.status_code == 200:
            content = resp.text.lower()
            # 简单检查：是否有 Disallow: /pdf 或 Disallow: /*pdf
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    if path in ("/pdf", "/pdf/", "/*pdf", "/*pdf*"):
                        return False
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# Hook: before_run — 代理健康检查 + 登录态预热 + robots.txt 检查
# ---------------------------------------------------------------------------
def _before_run(payload: dict) -> dict:
    """运行前检查代理健康、登录态、robots.txt。"""
    config = payload.get("config", {})
    proxy_list = config.get("institution", {}).get("proxy_list", [])
    if proxy_list:
        healthy = sum(1 for p in proxy_list if _PROXY_HEALTH.check(p, config))
        _log("proxy_health_check", total=len(proxy_list), healthy=healthy)
    monitor = _get_cookie_monitor(config)
    cookie_valid = monitor.is_valid() if config.get("level", 1) >= 3 else None
    
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
    errors = []
    level = config.get("level", 1)
    if level not in (1, 2, 3): errors.append("level 必须是 1/2/3")
    if level >= 3:
        inst = config.get("institution", {})
        if not _campus_direct(config):
            if not inst.get("proxy_url") and not inst.get("proxy_list"):
                errors.append("level 3 需要 institution.proxy_url 或 proxy_list 或开启 campus_ip")
            if not inst.get("login_url"):
                errors.append("level 3 需要 institution.login_url 或开启 campus_ip")
    if config.get("delay_min", 3) < 1: errors.append("delay_min 建议 >= 1")
    if config.get("max_per_session", 50) > 200: errors.append("max_per_session 建议 <= 200")
    return errors

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def handle(operation: str, payload: dict) -> dict:
    if operation == "source.seed": return _seed(payload)
    if operation == "processor.process": return _process(payload)
    if operation == "hook.after_run": return _after_run(payload)
    if operation == "hook.before_run": return _before_run(payload)
    return {"error": "unsupported_operation", "operation": str(operation)}