#!/usr/bin/env python3
"""
markitdown wrapper - 修复中文编码问题

markitdown 对中文文件输出 GBK 编码，此脚本自动转换 UTF-8
"""

import subprocess
import sys
import argparse


def main():
    parser = argparse.ArgumentParser(description="markitdown with UTF-8 output fix")
    parser.add_argument("file", help="Input file")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    args, unknown = parser.parse_known_args()

    # 调用 markitdown
    cmd = ["markitdown", args.file] + unknown
    result = subprocess.run(cmd, capture_output=True)

    # 尝试 GBK 解码 (markitdown Windows 输出)
    try:
        text = result.stdout.decode("gbk")
    except Exception:
        try:
            text = result.stdout.decode("utf-8")
        except Exception:
            text = result.stdout.decode("latin-1", errors="replace")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
