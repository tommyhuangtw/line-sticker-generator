# LINE 貼圖產生器（寵物 / 小孩 / 角色版）

用 AI 把照片變成 12 張一組的 LINE 貼圖。提供網頁介面與命令列兩種用法。

`examples/` 裡有 3 組樹懶範例成品可以參考。

## 安裝與設定

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定 API 金鑰
cp .env.example .env
# 然後編輯 .env，填入你自己申請的金鑰（見下方說明）

# 3. 啟動網頁介面
python app.py
# 開瀏覽器到 http://localhost:8080
```

### 需要哪些 API 金鑰

| 金鑰 | 必填 | 用途 | 申請 |
|------|------|------|------|
| `KIE_AI_API_KEY` | ✅ | 主要圖片生成 | https://kie.ai |
| `CLOUDINARY_CLOUD_NAME` / `_API_KEY` / `_API_SECRET` | ✅ | 圖片上傳/CDN（免費） | https://cloudinary.com |
| `FAL_KEY` | ⬜ | 圖片生成備援 | https://fal.ai |
| `OPENROUTER_API_KEY` | ⬜ | AI 自動生成貼圖文字 | https://openrouter.ai |

> ⚠️ 每個人請用**自己**申請的金鑰，不要共用。`.env` 不會被上傳到 GitHub（已加進 `.gitignore`）。

## 命令列快速開始

### Step 1：生成貼圖大圖
1. 打開 ChatGPT（GPT-4o 圖片生成）
2. 上傳你寵物或小孩的照片（1-3 張）
3. 複製對應的 prompt：
   - 寵物版：`prompts/pet_sticker_prompt.md`
   - 小孩版：`prompts/kid_sticker_prompt.md`
4. 貼上送出，ChatGPT 會產生一張 4x3 的 grid 大圖

### Step 2：自動裁切
```bash
# 安裝依賴
pip install Pillow

# 基本用法（4列 x 3行 = 12張）
python crop_stickers.py 你的大圖.png

# 移除灰色背景（上架 LINE Creators Market 需要透明背景）
python crop_stickers.py 你的大圖.png --remove-bg

# 保留背景（LINE 拍貼自用）
python crop_stickers.py 你的大圖.png --keep-bg

# 自訂 grid 大小
python crop_stickers.py 你的大圖.png --rows 4 --cols 4

# 指定輸出資料夾
python crop_stickers.py 你的大圖.png -o ./my_stickers
```

### Step 3：上架或使用

#### 方法 A：LINE 拍貼（最簡單，自用或販售）
1. 下載 [LINE Sticker Maker](https://creator.line.me/en/stickermaker/) App
2. 建立新貼圖組 → 選擇張數（8/16/24/32/40）
3. 從 `output/stickers/` 匯入裁切好的圖片
4. 設定標題、說明、價格
5. 送出審核（約 1-3 天）
6. 審核通過後即可購買使用

#### 方法 B：LINE Creators Market（正式上架）
1. 到 [LINE Creators Market](https://creator.line.me/) 註冊帳號
2. 建立新貼圖
3. 上傳 `output/stickers/` 裡的 PNG（需透明背景，用 `--remove-bg`）
4. 上傳 `output/main.png` 和 `output/tab.png`
5. 送出審核

#### 方法 C：直接當圖片傳（最快，免審核）
1. 把 `output/stickers/` 裡的圖片存到手機
2. 在 LINE 聊天中直接傳送圖片

## 檔案結構
```
line_stickers/
├── README.md
├── crop_stickers.py          # 自動裁切腳本
├── prompts/
│   ├── pet_sticker_prompt.md  # 寵物版 prompt
│   └── kid_sticker_prompt.md  # 小孩版 prompt
└── output/                    # 裁切輸出（自動產生）
    ├── main.png               # LINE main image (240x240)
    ├── tab.png                # LINE tab image (96x74)
    └── stickers/
        ├── 01.png
        ├── 02.png
        └── ...
```

## LINE 貼圖規格

| 項目 | 尺寸 | 格式 |
|------|------|------|
| 貼圖 | 最大 370x320 px | PNG |
| Main Image | 240x240 px | PNG |
| Tab Image | 96x74 px | PNG |
| 數量 | 8/16/24/32/40 張 | - |
| 背景 | 透明（上架用） | - |
