#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P2-8：市场仓自包含创作者身份模型，不依赖主仓 ``sys.path`` 注入。

语义与主仓 ``omnicrawler.plugins.identity.CreatorIdentity`` 同源：
- 指纹是公钥的纯函数，任何时候现场推导，包内自称指纹只用于比对、绝不采信；
- 公钥长度非法 / base64 损坏 / 自称指纹不符即拒（fail-closed）。

主仓侧 ``UserIdentity``（本地私钥加密存储、密钥环）属运行时身份管理，市场仓
不复制；本模块只覆盖发布/校验所需的公开身份还原与指纹推导。
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

FINGERPRINT_ALGORITHM = "sha256-raw32-16"
ED25519_PUBLIC_KEY_SIZE = 32


class IdentityError(ValueError):
    """身份数据非法（公钥长度 / base64 / 字段缺失）。"""


class FingerprintMismatchError(IdentityError):
    """自称指纹与公钥现场推导指纹不一致（疑似身份冒充）。"""


def derive_fingerprint(public_key_bytes: bytes) -> str:
    """SHA-256(ed25519 原始 32 字节) 前 32 hex 字符，与主仓同一算法。"""
    if not isinstance(public_key_bytes, bytes) or len(public_key_bytes) != ED25519_PUBLIC_KEY_SIZE:
        raise IdentityError(
            f"ed25519 公钥必须是 {ED25519_PUBLIC_KEY_SIZE} 个原始字节，"
            f"实际 {len(public_key_bytes) if isinstance(public_key_bytes, bytes) else type(public_key_bytes)} 字节"
        )
    return hashlib.sha256(public_key_bytes).hexdigest()[:32]


@dataclass(slots=True)
class CreatorIdentity:
    """公开身份信息，嵌入插件 manifest 的 ``creator.identity``（可随包分发）。

    **不存储指纹字段。** 指纹由公钥现场推导；``to_dict`` 写出的冗余指纹仅供
    人工查看/诊断，读取端一律重新推导。
    """

    username: str
    public_key: bytes

    def __post_init__(self) -> None:
        derive_fingerprint(self.public_key)

    @property
    def key_fingerprint(self) -> str:
        return derive_fingerprint(self.public_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "public_key": base64.b64encode(self.public_key).decode("ascii"),
            "key_fingerprint": self.key_fingerprint,
            "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CreatorIdentity":
        """从 ``creator.identity`` 还原身份；自称指纹只用于比对，绝不用于信任判定。"""
        try:
            public_key = base64.b64decode(str(data["public_key"]), validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise IdentityError("creator.identity 的 public_key 缺失或不是合法 base64") from exc
        identity = cls(username=str(data["username"]), public_key=public_key)
        declared = str(data.get("key_fingerprint", "")).strip().lower()
        if declared and declared != identity.key_fingerprint:
            raise FingerprintMismatchError(
                f"creator.identity 指纹与公钥不符：声明 {declared}，"
                f"公钥实际推导 {identity.key_fingerprint}（疑似身份冒充，已拒绝）"
            )
        return identity


__all__ = [
    "IdentityError",
    "FingerprintMismatchError",
    "FINGERPRINT_ALGORITHM",
    "ED25519_PUBLIC_KEY_SIZE",
    "derive_fingerprint",
    "CreatorIdentity",
]
