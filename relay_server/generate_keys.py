#!/usr/bin/env python3
"""
Phoenix Relay Server — RSA 密钥对生成脚本

用法:
  python3 generate_keys.py         # 生成到 relay_server/keys/
  python3 generate_keys.py /path   # 生成到指定目录

首次使用前必须运行此脚本，否则 Relay Server 无法启动（缺少 private_key.pem）。
"""
import sys
import os
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("❌ 缺少 cryptography 库，请先安装:")
    print("   pip install cryptography")
    sys.exit(1)


def generate_keys(output_dir: Path):
    """生成 RSA-2048 密钥对"""
    output_dir.mkdir(parents=True, exist_ok=True)

    private_key_path = output_dir / "private_key.pem"
    public_key_path = output_dir / "public_key.pem"

    if private_key_path.exists():
        print(f"⚠️  私钥已存在: {private_key_path}")
        print("   如需重新生成，请先删除旧密钥文件。")
        return

    print("🔑 生成 RSA-2048 密钥对...")

    # 生成私钥
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 写入私钥 (PKCS8 PEM, 无加密)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_key_path.write_bytes(private_pem)
    private_key_path.chmod(0o600)  # 仅所有者可读写
    print(f"✅ 私钥: {private_key_path}")

    # 写入公钥
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_path.write_bytes(public_pem)
    print(f"✅ 公钥: {public_key_path}")

    # 生成 DER 格式公钥（用于 Extension 的 public_key.der）
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    der_path = output_dir / "public_key.der"
    der_path.write_bytes(public_der)
    print(f"✅ DER 公钥: {der_path}")

    # 创建 .gitignore 防止意外提交
    gitignore = output_dir / ".gitignore"
    gitignore.write_text("# 密钥文件，绝不提交到版本控制\n*.pem\n*.der\n.auth_token\n")
    print(f"✅ .gitignore: {gitignore}")

    print("\n🎉 密钥生成完成！现在可以启动 Relay Server 了。")


if __name__ == "__main__":
    # 默认输出到 relay_server/keys/
    if len(sys.argv) > 1:
        keys_dir = Path(sys.argv[1])
    else:
        script_dir = Path(__file__).parent
        keys_dir = script_dir / "keys"

    generate_keys(keys_dir)
