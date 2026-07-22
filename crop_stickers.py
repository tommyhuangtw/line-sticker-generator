"""
LINE 貼圖自動裁切工具
=====================
把 ChatGPT 生成的 grid 大圖自動切成符合 LINE 規格的個別貼圖。

使用方式：
    python crop_stickers.py <圖片路徑> [--rows 3] [--cols 4] [--output ./output]

LINE 貼圖規格：
    - 貼圖：最大 370x320 px, PNG, 透明背景
    - Main image：240x240 px
    - Tab image：96x74 px
"""

import argparse
import sys
from pathlib import Path

from generate_stickers import process_grid_image


def main():
    parser = argparse.ArgumentParser(
        description="LINE 貼圖自動裁切工具 - 把 grid 大圖切成個別貼圖"
    )
    parser.add_argument("image", help="輸入的 grid 大圖路徑")
    parser.add_argument("--rows", type=int, default=3, help="grid 行數（預設 3）")
    parser.add_argument("--cols", type=int, default=4, help="grid 列數（預設 4）")
    parser.add_argument("--output", "-o", default="./output", help="輸出資料夾（預設 ./output）")
    parser.add_argument("--remove-bg", action="store_true",
                        help="移除背景（預設行為，上架需透明背景）")
    parser.add_argument("--keep-bg", action="store_true",
                        help="保留背景（LINE 拍貼自用，不去背）")

    args = parser.parse_args()
    remove_bg = not args.keep_bg

    input_path = Path(args.image)
    if not input_path.exists():
        print(f"找不到檔案：{input_path}")
        sys.exit(1)

    output_dir = Path(args.output)

    print(f"載入圖片：{input_path}")
    process_grid_image(input_path, output_dir, args.rows, args.cols, remove_bg)

    sticker_dir = output_dir / "stickers"
    print(f"\n完成！貼圖已存到：{output_dir.resolve()}")
    print(f"\n下一步：")
    print(f"  1. 打開 LINE 拍貼 App")
    print(f"  2. 建立新貼圖組")
    print(f"  3. 匯入 {sticker_dir.resolve()} 裡的圖片")
    print(f"  4. 發布即可使用！")


if __name__ == "__main__":
    main()
