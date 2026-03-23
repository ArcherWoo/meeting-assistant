"""
extract_release.py — 合并分卷压缩包并解压到 win-unpacked/

用法：
    py -3 scripts/extract_release.py

说明：
    将项目根目录下的 release.part1.zip、release.part2.zip、release.part3.zip
    按顺序合并为完整的 release.zip，再解压到 win-unpacked/ 目录。
    完成后直接运行 win-unpacked/Meeting Assistant.exe 即可启动应用。
"""

import os
import zipfile
import sys

# ── 配置 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)          # 项目根目录
PARTS      = ["release.part1.zip", "release.part2.zip", "release.part3.zip"]
MERGED_ZIP = os.path.join(ROOT_DIR, "release.zip")
OUTPUT_DIR = os.path.join(ROOT_DIR, "win-unpacked")
CHUNK_SIZE = 4 * 1024 * 1024                       # 4 MB 读写缓冲


def merge_parts() -> None:
    """将多个分卷按顺序合并为 release.zip。"""
    print("📦 合并分卷压缩包...")
    missing = [p for p in PARTS if not os.path.exists(os.path.join(ROOT_DIR, p))]
    if missing:
        print(f"❌ 缺少文件：{', '.join(missing)}")
        print("   请确保所有分卷文件都在项目根目录下。")
        sys.exit(1)

    total_size = sum(os.path.getsize(os.path.join(ROOT_DIR, p)) for p in PARTS)
    written = 0

    with open(MERGED_ZIP, "wb") as out_f:
        for part_name in PARTS:
            part_path = os.path.join(ROOT_DIR, part_name)
            part_size = os.path.getsize(part_path)
            print(f"   合并 {part_name} ({part_size / 1024 / 1024:.1f} MB)...")
            with open(part_path, "rb") as in_f:
                while True:
                    chunk = in_f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    written += len(chunk)
                    pct = written * 100 // total_size
                    print(f"\r   进度：{pct:3d}%", end="", flush=True)

    print(f"\r   合并完成：release.zip = {os.path.getsize(MERGED_ZIP) / 1024 / 1024:.1f} MB")


def extract_zip() -> None:
    """将 release.zip 解压到 win-unpacked/。"""
    print(f"📂 解压到 {OUTPUT_DIR} ...")
    if not os.path.exists(MERGED_ZIP):
        print("❌ release.zip 不存在，请先运行合并步骤。")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with zipfile.ZipFile(MERGED_ZIP, "r") as zf:
        members = zf.namelist()
        total  = len(members)
        for i, member in enumerate(members, 1):
            zf.extract(member, OUTPUT_DIR)
            if i % 50 == 0 or i == total:
                pct = i * 100 // total
                print(f"\r   进度：{pct:3d}%  ({i}/{total})", end="", flush=True)

    print(f"\n   解压完成，共 {total} 个文件。")


def cleanup_merged_zip() -> None:
    """删除临时合并文件以节省磁盘空间。"""
    if os.path.exists(MERGED_ZIP):
        os.remove(MERGED_ZIP)
        print("🗑  已删除临时文件 release.zip")


def main() -> None:
    print("=" * 60)
    print("  Meeting Assistant — 分卷解压工具")
    print("=" * 60)

    merge_parts()
    extract_zip()
    cleanup_merged_zip()

    exe_path = os.path.join(OUTPUT_DIR, "Meeting Assistant.exe")
    print()
    print("✅ 完成！")
    if os.path.exists(exe_path):
        print(f"   可执行文件：{exe_path}")
    print("   双击 win-unpacked/Meeting Assistant.exe 即可启动应用。")
    print("=" * 60)


if __name__ == "__main__":
    main()

