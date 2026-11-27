"""为内置组件生成创作者签名三件套（维护者本机执行，不入 CI）。

## 为什么需要这个脚本

市场仓里插件与模板都有完整的创作者签名链，**组件此前没有**。
`finalize_submission.py` 只覆盖 `plugins/` 与 `templates/`（目标目录写死），
`new_submission.py` 的 kind 也只接受 `plugin` / `template` ——
组件没有投稿入口，所以需要一个专门的签名脚本。

## 它做什么

对指定组件目录生成四件产物（与既有组件同构）：

```
creator.identity              {username, public_key, key_fingerprint, fingerprint_algorithm}
package.manifest.json         {creator_fingerprint, files{路径: sha256:...}, package_id,
                               package_type: "component", requested_username,
                               schema_version, version}
creator.sig                   manifest 字节的创作者签名
package.manifest.creator.sig  同上（兼容轨，catalog 用这个键名）
```

## 安全边界

* **私钥只在命令行按路径传入，脚本不读、不打印、不复制它的内容**；
* 公钥从私钥派生后写进 `creator.identity`（这是公开信息）；
* 已存在签名时**默认拒绝覆盖**（防误改已发布组件的身份），要覆盖必须显式 `--force`。

## 用法（维护者本机）

下面的命令由维护者复制执行，私钥路径按本机实际位置调整。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

#: 参与清单哈希的文件（不含签名自身，否则自引用）。
#: **顺序固定**，保证同一目录内容产出同一清单。
MANIFEST_INPUTS = ("creator.identity", "recipe.json", "files.lock.json", "deps.lock.json", "listing.md")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _public_key_of(private_pem: bytes) -> bytes:
    """从私钥派生公钥（Ed25519）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("私钥不是 Ed25519 类型 —— 与既有组件的签名算法不一致")
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="为内置组件生成创作者签名三件套")
    parser.add_argument("component_dir", help="组件目录（如 components/browser/chromium-builtin）")
    parser.add_argument("--private-key", required=True, help="维护者冷私钥路径（只读，不打印内容）")
    parser.add_argument("--username", default="starlife", help="创作者用户名")
    parser.add_argument(
        "--expect-fingerprint",
        default="",
        help=("先用这把私钥派生公钥，与目录里**现有** creator.identity 的指纹比对；"
              "不一致就拒绝（防止用错钥匙把已发布身份改成另一把公钥）"),
    )
    parser.add_argument(
        "--force", action="store_true", help="覆盖已存在的签名（默认拒绝，防误改已发布身份）"
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    directory = Path(args.component_dir)
    if not (directory / "recipe.json").is_file():
        raise SystemExit(f"不是组件目录（缺 recipe.json）：{directory}")
    if (directory / "creator.identity").is_file() and not args.force:
        raise SystemExit(
            f"{directory.name} 已有签名 —— 拒绝覆盖（防误改已发布身份）。"
            "确需重签请加 --force"
        )

    private_pem = Path(args.private_key).read_bytes()
    try:
        public_raw = _public_key_of(private_pem)
    except ImportError as exc:
        raise SystemExit(f"缺少 cryptography 依赖：{exc}") from exc

    # ★ 2026-11-27 新增：**重签前先确认手里是同一把钥匙**。
    #
    #   事故：我拿 `component_signing_private.pem` 对 11 个组件加了 `--force`，
    #   它们的 `creator.identity` 被写成了另一把公钥（指纹 085c7770… 而不是
    #   `4c301480…`）。签名工具当时只说"OK 已签名"，自检验的是"新签名能被新公钥
    #   验证"—— 那当然成立。
    #
    #   `--force` 的语义是「覆盖已有签名」，**不是**「换一把钥匙」。
    #   这条守卫把二者区分开：给了 `--expect-fingerprint` 就必须对上。
    if args.expect_fingerprint:
        from catalog_lib.identity import derive_fingerprint as _derive

        actual = _derive(public_raw)
        if actual != args.expect_fingerprint.strip():
            raise SystemExit(
                f"私钥派生的指纹是 {actual}，与 --expect-fingerprint "
                f"{args.expect_fingerprint.strip()} 不一致 —— 这把不是同一把钥匙。"
                "拒绝重签（否则会把已发布的创作者身份改成另一把公钥）。"
            )

    # ── creator.identity ──────────────────────────────────────────────
    from catalog_lib.identity import derive_fingerprint

    fingerprint = derive_fingerprint(public_raw)
    identity = {
        "username": args.username,
        "public_key": base64.b64encode(public_raw).decode("ascii"),
        "key_fingerprint": fingerprint,
        "fingerprint_algorithm": "sha256-raw32-16",
    }
    # ★ 必须显式 `newline="\n"`：Windows 上 `write_text` 默认把 `\n` 写成 `\r\n`，
    #   而 `creator.identity` 的字节**进了 `package.manifest.json` 的 sha256 清单**。
    #
    #   实测后果（2026-11-27）：签名脚本在 Windows 上跑 ⇒ 盘上是 CRLF（202 字节），
    #   manifest 记的是 CRLF 那份的哈希；而 git 按 `.gitattributes` 的
    #   `* text=auto eol=lf` 把它存成 LF（196 字节）⇒ **CI 检出后哈希对不上**：
    #
    #       convert-markdown: 清单与文件不一致 —— creator.identity 记录
    #       sha256:4e24c9c23cf3…，实际 sha256:37b6ea536be1…
    #
    #   本地绿、CI 红，正是这类「Windows 上恰好正确」的缺陷。
    (directory / "creator.identity").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # ── package.manifest.json ─────────────────────────────────────────
    recipe = json.loads((directory / "recipe.json").read_text(encoding="utf-8"))
    files = {
        name: _sha256_file(directory / name)
        for name in MANIFEST_INPUTS
        if (directory / name).is_file()
    }
    manifest = {
        "creator_fingerprint": fingerprint,
        "files": files,
        "package_id": str(recipe.get("id") or directory.name),
        "package_type": "component",
        "requested_username": args.username,
        "schema_version": 1,
        "version": str(recipe["version"]),
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    (directory / "package.manifest.json").write_bytes(manifest_bytes)

    # ── 双签名轨 ──────────────────────────────────────────────────────
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(private_pem, password=None)
    assert isinstance(key, Ed25519PrivateKey)
    signature = key.sign(manifest_bytes)
    (directory / "creator.sig").write_bytes(signature)
    (directory / "package.manifest.creator.sig").write_bytes(signature)

    # 自检：用 identity 里的公钥验一遍
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature, manifest_bytes
        )
    except InvalidSignature as exc:  # pragma: no cover - 只在实现出错时触发
        raise SystemExit("自检失败：刚生成的签名验不过") from exc

    print(f"OK 已签名：{directory}")
    print(f"  package_id      = {manifest['package_id']}")
    print(f"  version         = {manifest['version']}")
    print(f"  creator         = {identity['username']} ({fingerprint})")
    print(f"  清单覆盖文件    = {len(files)} 个")
    print("  签名自检        = 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
