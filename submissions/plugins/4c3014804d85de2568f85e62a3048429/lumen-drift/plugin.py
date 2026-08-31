"""Lumen Drift: a declarative local-media background for OmniCrawler."""

from __future__ import annotations

PLUGIN_METADATA = {
    "name": "lumen-drift",
    "version": "0.2.0",
    "api_version": 1,
    "description": "使用 OmniCrawler 声明式背景宿主呈现本地图片与视频",
    "plugin_types": ["ui"],
    "category": "appearance",
    "tags": ["wallpaper", "ambient", "video", "local-only", "declarative-ui"],
    "permissions": ["ui:background"],
    "domains": [],
    "input_files": [],
    "dependencies": [],
    "license": "MIT",
    "execution_mode": "in_process",
    "min_core_version": "0.11.2",
}


def register(registry) -> None:
    """Declare intent only; OmniCrawler owns scanning, controls, and rendering."""

    registry.register_background(
        "lumen-drift.ambient",
        "Lumen Drift · 流光漂移",
        default_opacity=0.24,
        default_dim=0.30,
    )
