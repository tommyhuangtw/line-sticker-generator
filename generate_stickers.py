"""
LINE 貼圖一鍵生成工具
====================
使用 KIE AI 的 GPT Image-2 API 生成貼圖，自動裁切成 LINE 規格。

使用方式：
    # 寵物版（用寵物照片生成）
    python generate_stickers.py --pet --photos photo1.jpg photo2.jpg

    # 小孩版（用小孩照片生成）
    python generate_stickers.py --kid --photos photo1.jpg photo2.jpg

    # 純文字生成（不需要照片）
    python generate_stickers.py --pet --text-only

    # 自訂文字
    python generate_stickers.py --pet --photos photo1.jpg --phrases "汪汪,肚子餓,想睡覺"
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("需要安裝 Pillow：pip install Pillow")
    sys.exit(1)

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()


class StickerError(Exception):
    """Raised when sticker generation or processing fails."""
    pass

# --- Config ---
KIE_API_BASE = "https://api.kie.ai"
KIE_API_KEY = os.environ.get("KIE_AI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "google/gemini-3.1-flash-lite-preview"
FAL_API_KEY = os.environ.get("FAL_KEY", "")
FAL_API_BASE = "https://queue.fal.run/openai/gpt-image-2"

STICKER_MAX_W = 370
STICKER_MAX_H = 320
MAIN_IMAGE_SIZE = (240, 240)
TAB_IMAGE_SIZE = (96, 74)

# --- Sticker phrases ---
# Each mode has multiple styles; keys are style IDs shown in the UI.

PET_PHRASE_STYLES = {
    "撒嬌": [
        "奴才陪我～", "肚子餓了喵", "早安～起床",
        "你快回來", "吃飽沒？", "記得餵我",
        "想睡了zzz", "摸摸我嘛", "人呢？？",
        "我最可愛吧", "不要出門！", "晚安喵～",
    ],
    "日常實用": [
        "早安～", "肚子餓了", "辛苦了！",
        "你快回來！", "吃飽沒？", "好想你～",
        "想睡了zzz", "拜託啦～", "收到！",
        "謝謝你～", "不要走！", "晚安～",
    ],
    "傲嬌": [
        "哼！不理你", "還不餵我？", "勉強早安",
        "算你識相", "吃飽了 別煩", "沒有很想你",
        "本喵要睡了", "不准摸！", "你終於回來",
        "我才沒撒嬌", "走開啦！", "哼 晚安",
    ],
}

PET_DOG_PHRASE_STYLES = {
    "撒嬌": [
        "陪我玩～", "我餓餓了汪", "早安～散步",
        "你快回來！", "吃飽沒？", "記得餵我",
        "想睡了zzz", "摸摸我嘛", "人呢？？汪",
        "我最乖吧", "不要出門！", "晚安汪～",
    ],
    "日常實用": [
        "早安～", "肚子餓了", "辛苦了！",
        "你快回來！", "吃飽沒？", "好想你～",
        "想睡了zzz", "拜託啦～", "收到！",
        "謝謝你～", "不要走！", "晚安～",
    ],
    "傲嬌": [
        "哼！不理你", "還不餵我？", "勉強早安",
        "算你識相", "吃飽了 別煩", "沒有很想你",
        "本汪要睡了", "不准摸！", "你終於回來",
        "我才沒撒嬌", "走開啦！", "哼 晚安",
    ],
}

KID_PHRASE_STYLES = {
    "撒嬌": [
        "馬麻抱抱～", "我要吃飯飯", "早安～",
        "你快看！", "吃飽飽了", "不要上班嘛",
        "想睡覺了zzz", "寶寶辛苦了", "人呢？？",
        "我可愛吧～", "回我訊息！", "晚安安～",
    ],
    "日常實用": [
        "早安～", "肚子餓了", "辛苦了！",
        "快回來！", "吃飽沒？", "好想你～",
        "想睡了zzz", "拜託啦～", "收到！",
        "謝謝你～", "不要走！", "晚安～",
    ],
    "小大人": [
        "我醒了！", "今天吃什麼", "早安你好",
        "等你回家", "我自己來！", "你放心啦",
        "該睡覺了", "你還好嗎？", "我知道了",
        "沒問題！", "加油！", "晚安 好夢",
    ],
}

# Convenience aliases for backward compatibility
PET_PHRASES = PET_PHRASE_STYLES["撒嬌"]
PET_DOG_PHRASES = PET_DOG_PHRASE_STYLES["撒嬌"]
KID_PHRASES = KID_PHRASE_STYLES["撒嬌"]

CHARACTER_PHRASE_STYLES = {
    "日常實用": [
        "早安～", "肚子餓了", "辛苦了！",
        "你快回來！", "吃飽沒？", "好想你～",
        "想睡了zzz", "拜託啦～", "收到！",
        "謝謝你～", "不要走！", "晚安～",
    ],
}
CHARACTER_PHRASES = CHARACTER_PHRASE_STYLES["日常實用"]

ALL_PHRASE_STYLES = {
    "pet": PET_PHRASE_STYLES,
    "dog": PET_DOG_PHRASE_STYLES,
    "kid": KID_PHRASE_STYLES,
    "character": CHARACTER_PHRASE_STYLES,
}

# --- Target audience options ---
AUDIENCES = {
    "通用日常": {
        "label": "通用日常",
        "desc": "適合所有人的日常用語",
        "phrases": [
            "早安～", "肚子餓了", "辛苦了！",
            "你快回來！", "吃飽沒？", "好想你～",
            "想睡了zzz", "拜託啦～", "收到！",
            "謝謝你～", "OK！", "晚安～",
        ],
    },
    "社畜上班族": {
        "label": "社畜上班族",
        "desc": "上班、加班、開會、摸魚",
        "phrases": [
            "早安 又是Monday", "又要開會...", "辛苦了！",
            "下班！！！", "午餐吃什麼", "好累 想下班",
            "摸魚中...", "收到 馬上做", "deadline到了",
            "可以準時走嗎", "幫我買咖啡", "今天也加油",
        ],
    },
    "媽媽/爸爸": {
        "label": "媽媽/爸爸",
        "desc": "帶小孩、家長群組、家庭日常",
        "phrases": [
            "早安～起床了", "功課寫了沒", "吃飯了！",
            "快去洗澡", "幾點回來？", "媽媽好累",
            "睡覺時間到", "不要再看手機", "收到謝謝",
            "今天晚餐吃啥", "乖～", "晚安 早點睡",
        ],
    },
    "學生": {
        "label": "學生",
        "desc": "上課、考試、報告、宿舍生活",
        "phrases": [
            "早安 要遲到了", "這題怎麼寫", "報告救我",
            "下課了！", "今天考什麼", "好想翹課",
            "熬夜中...", "借我抄一下", "OK 收到",
            "要不要吃飯", "考完了！！", "晚安 明天見",
        ],
    },
    "情侶": {
        "label": "情侶",
        "desc": "撒嬌、約會、想你",
        "phrases": [
            "早安 想你了", "你在幹嘛～", "辛苦了寶貝",
            "什麼時候來找我", "吃飯了嗎", "好想你喔",
            "想睡了 陪我", "拜託嘛～", "已讀不回？",
            "你最好了", "不要生氣嘛", "晚安 愛你",
        ],
    },
    "閨蜜/好友": {
        "label": "閨蜜/好友",
        "desc": "約吃、八卦、吐槽、揪團",
        "phrases": [
            "早～今天約嗎", "有八卦！", "笑死",
            "吃什麼好", "快來！", "太扯了吧",
            "好無聊喔", "拜託幫我", "收到！",
            "揪團揪團", "哈哈哈哈", "掰掰～",
        ],
    },
    "工程師": {
        "label": "工程師",
        "desc": "寫 code、debug、deploy、on-call",
        "phrases": [
            "早 先喝咖啡", "在 debug...", "LGTM！",
            "又有 bug", "deploy 了嗎", "code review 拜託",
            "404 找不到人", "先 merge 再說", "收到 開 ticket",
            "這不是 feature", "on-call 中...", "git push 下班",
        ],
    },
}

AUDIENCE_LIST = list(AUDIENCES.keys())

# --- Drawing style options ---
DRAWING_STYLES = {
    "保持原圖風格": "保持上傳圖片的原始畫風和風格，不要改變角色的繪製風格",
    "寫實感": "主體要寫實感",
    "插畫風": "主體使用插畫風格，線條清晰、色彩鮮明",
    "Q版可愛": "主體使用 Q 版風格，頭大身體小、圓潤可愛",
}


def build_prompt(mode: str, phrases: list[str], custom_description: str = "",
                 personality: str = "", drawing_style: str = "",
                 audience: str = "") -> str:
    """Build the image generation prompt based on mode."""

    if mode == "pet":
        subject_desc = "寵物（貓咪或狗狗）"
        tone_desc = "撒嬌、傲嬌，像寵物在跟主人任性說話"
        extra_deco = "肉球、魚骨頭、小愛心、小星星"
        expression_desc = "伸懶腰、歪頭、趴著、舔嘴、翻肚、蹭蹭、打哈欠、露出肚子"
    elif mode == "character":
        subject_desc = "虛擬角色"
        tone_desc = personality if personality else "活潑可愛、有個性"
        extra_deco = "小愛心、小星星、驚嘆號、問號、音符"
        expression_desc = "開心、生氣、驚訝、難過、思考、揮手、比心、睡覺、歪頭、大笑、嘟嘴、偷笑"
    else:  # kid
        subject_desc = "小朋友"
        tone_desc = "童言童語、撒嬌，像小朋友在說話"
        extra_deco = "小星星、小愛心、小花、泡泡"
        expression_desc = "嘟嘴、歪頭、大笑、揉眼睛、比YA、托腮、伸手要抱抱、偷笑"

    personality_line = ""
    if personality and mode != "character":
        personality_line = f"\n個性特徵：{personality}，請讓貼圖的表情和肢體語言反映這個性格。"

    audience_line = ""
    if audience and audience != "通用日常":
        aud_info = AUDIENCES.get(audience, {})
        aud_desc = aud_info.get("desc", audience)
        audience_line = f"\n目標使用者：{audience}（{aud_desc}），貼圖的情境和氛圍要符合這個族群的日常。"

    # Determine drawing style instruction
    style_instruction = DRAWING_STYLES.get(drawing_style, "主體要寫實感")

    phrases_text = "\n".join(f"- {p}" for p in phrases)

    prompt = f"""請生成一張 4x3 的網格大圖（共 12 張 LINE 貼圖排列在一起），亮綠色背景（green screen）。

主體是{subject_desc}。
{f"特徵描述：{custom_description}" if custom_description else ""}{personality_line}{audience_line}

【文字內容】（12 張，每張一句）
{phrases_text}

【繪製規則】
・{style_instruction}，每張要有不同的姿勢和表情（{expression_desc}）
・使用像白色筆畫上去的粗手繪線條作為描邊
・線條要有隨手一筆畫出的感覺，略微粗細不均、自然隨性
・可搭配箭頭、虛線，讓畫面有視線引導感
・每張貼圖中的主體要有白色描邊效果（像貼紙剪下來的感覺）

【文字規則】
・使用手寫感粗體的中文文字，白色
・語氣偏{tone_desc}
・簡短的句子，不需要註解
・不要加數字編號（不要寫 1. 2. 3. 等數字）

【裝飾元素】
・可適度加入{extra_deco}、zzz 等手繪裝飾
・裝飾也使用白色手繪風格
・不要加太多，讓貼圖看起來輕鬆舒服

【格式要求】
・輸出為一張大圖，4 列 x 3 行排列
・每張貼圖之間必須有明顯的亮綠色間隔，間距至少佔格子寬度的 5%
・貼圖內容不可以超出自己的格子範圍，不可以和相鄰貼圖重疊
・亮綠色背景（#00B140），像綠幕一樣方便後續去背
"""
    return prompt


def generate_phrases_with_ai(character_name: str = "", personality: str = "") -> list[str]:
    """Use OpenRouter (Gemini) to generate 12 LINE sticker phrases for a character."""
    if not OPENROUTER_API_KEY:
        raise StickerError("OPENROUTER_API_KEY 未設定")

    name_part = f"角色名稱是「{character_name}」，" if character_name else ""
    system_msg = (
        "你是一個 LINE 貼圖文案專家。請根據角色的個性和說話風格，"
        "生成 12 句適合用在 LINE 貼圖上的短句。\n\n"
        "重要規則：\n"
        "1. 這些文字是給「人」在聊天中使用的，必須是日常生活中常用的場景，"
        "例如：早安、晚安、謝謝、辛苦了、好餓、想睡、OK、加油 等\n"
        "2. 在這些日常用語的基礎上，融入角色的個性和說話風格（語助詞、口頭禪、態度等），"
        "讓文字帶有角色特色但仍然實用\n"
        "3. 每句不超過 8 個字\n"
        "4. 12 句要涵蓋不同的日常情境（打招呼、道謝、道歉、鼓勵、吃飯、睡覺、同意、拒絕等）\n\n"
        "請直接回傳 JSON 陣列格式，例如：[\"早安～\", \"辛苦了\", ...]"
        "只回傳 JSON 陣列，不要有其他文字。"
    )
    user_msg = (
        f"{name_part}"
        f"個性與說話風格：{personality if personality else '活潑可愛'}\n"
        f"請生成 12 句日常實用、帶有角色風格的 LINE 貼圖文字。"
    )

    payload = json.dumps({
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.8,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        content = result["choices"][0]["message"]["content"].strip()
        # Extract JSON array from response (handle markdown code blocks)
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        phrases = json.loads(content)
        if isinstance(phrases, list) and len(phrases) >= 12:
            return phrases[:12]
        elif isinstance(phrases, list):
            # Pad with defaults if less than 12
            defaults = CHARACTER_PHRASES
            return (phrases + defaults)[:12]
        raise StickerError("AI 回傳格式不正確")
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        raise StickerError(f"OpenRouter API 呼叫失敗: {e}")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        raise StickerError(f"AI 回傳解析失敗: {e}")


def api_request(method: str, path: str, data: dict = None, params: dict = None) -> dict:
    """Make a request to the KIE AI API."""
    url = f"{KIE_API_BASE}{path}"

    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise StickerError(f"API 錯誤 {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise StickerError(f"連線錯誤: {e.reason}")


def create_task_text_to_image(prompt: str) -> str:
    """Create a text-to-image task, return task ID."""
    payload = {
        "model": "gpt-image-2-text-to-image",
        "input": {
            "prompt": prompt,
            "aspect_ratio": "4:3",
            "resolution": "2K",
        }
    }
    resp = api_request("POST", "/api/v1/jobs/createTask", data=payload)

    if resp.get("code") != 200:
        raise StickerError(f"建立任務失敗: {resp.get('msg', 'unknown error')}")

    task_id = resp["data"]["taskId"]
    return task_id


def create_task_image_to_image(prompt: str, image_urls: list[str]) -> str:
    """Create an image-to-image task, return task ID."""
    payload = {
        "model": "gpt-image-2-image-to-image",
        "input": {
            "prompt": prompt,
            "input_urls": image_urls,
            "aspect_ratio": "4:3",
            "resolution": "2K",
        }
    }
    resp = api_request("POST", "/api/v1/jobs/createTask", data=payload)

    if resp.get("code") != 200:
        raise StickerError(f"建立任務失敗: {resp.get('msg', 'unknown error')}")

    task_id = resp["data"]["taskId"]
    return task_id


def check_task_status(task_id: str) -> dict:
    """Check task status once. Returns the data dict with 'state' field."""
    resp = api_request("GET", "/api/v1/jobs/recordInfo", params={"taskId": task_id})
    if resp.get("code") != 200:
        raise StickerError(f"查詢失敗: {resp.get('msg')}")
    return resp["data"]


# --- fal.ai API ---

def _fal_request(method: str, url: str, data: dict = None) -> dict:
    """Make a request to fal.ai API."""
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Key {FAL_API_KEY}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise StickerError(f"fal.ai API 錯誤 {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise StickerError(f"fal.ai 連線錯誤: {e.reason}")


def fal_create_task_image_to_image(prompt: str, image_urls: list[str]) -> str:
    """Create an image-to-image task on fal.ai, return request ID."""
    payload = {
        "prompt": prompt,
        "image_urls": image_urls,
        "image_size": "landscape_4_3",
        "quality": "high",
        "num_images": 1,
        "output_format": "png",
    }
    resp = _fal_request("POST", f"{FAL_API_BASE}/edit", payload)
    request_id = resp.get("request_id")
    if not request_id:
        raise StickerError(f"fal.ai 建立任務失敗: {resp}")
    return request_id


def fal_create_task_text_to_image(prompt: str) -> str:
    """Create a text-to-image task on fal.ai, return request ID."""
    payload = {
        "prompt": prompt,
        "image_size": "landscape_4_3",
        "quality": "high",
        "num_images": 1,
        "output_format": "png",
    }
    resp = _fal_request("POST", FAL_API_BASE, payload)
    request_id = resp.get("request_id")
    if not request_id:
        raise StickerError(f"fal.ai 建立任務失敗: {resp}")
    return request_id


def fal_check_task_status(request_id: str) -> dict:
    """Check fal.ai task status. Returns dict compatible with KIE format."""
    status_resp = _fal_request("GET", f"{FAL_API_BASE}/requests/{request_id}/status", None)
    fal_status = status_resp.get("status", "UNKNOWN")

    if fal_status == "COMPLETED":
        # Fetch the actual result
        result = _fal_request("GET", f"{FAL_API_BASE}/requests/{request_id}", None)
        images = result.get("images", [])
        if images:
            result_urls = [img["url"] for img in images]
            return {
                "state": "success",
                "resultJson": json.dumps({"resultUrls": result_urls}),
            }
        return {"state": "fail", "failMsg": "fal.ai 沒有回傳圖片"}

    elif fal_status == "FAILED":
        return {"state": "fail", "failMsg": status_resp.get("error", "fal.ai 生圖失敗")}

    else:
        # IN_QUEUE, IN_PROGRESS, etc.
        return {"state": "generating", "progress": 0}


def poll_task(task_id: str, max_wait: int = 300) -> dict:
    """Poll task status until completion or timeout."""
    print("等待生圖完成", end="", flush=True)
    start = time.time()

    while time.time() - start < max_wait:
        data = check_task_status(task_id)
        state = data.get("state", "")

        if state == "success":
            print(" 完成！")
            return data
        elif state == "fail":
            fail_msg = data.get("failMsg", "unknown")
            raise StickerError(f"生圖失敗: {fail_msg}")
        else:
            print(".", end="", flush=True)
            time.sleep(5)

    raise StickerError(f"超時（等了 {max_wait} 秒）")


def download_image(url: str, save_path: Path) -> Path:
    """Download image from URL."""
    print(f"下載圖片: {save_path.name}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        save_path.write_bytes(resp.read())
    return save_path


def upload_photo_to_temp(photo_path: str) -> str:
    """
    For image-to-image, KIE needs a URL. If user provides local files,
    we need to upload them somewhere accessible.
    For now, we'll guide users to provide URLs or use an upload service.
    """
    # Check if it's already a URL
    if photo_path.startswith("http://") or photo_path.startswith("https://"):
        return photo_path

    raise StickerError("KIE AI API 需要圖片 URL，不支援本地檔案直接上傳。請上傳到圖床後提供 URL。")


# --- Crop functions (from crop_stickers.py) ---

def _detect_bg_color(img: Image.Image) -> tuple[int, int, int]:
    """Sample corners to detect the background color."""
    pixels = [
        img.getpixel((2, 2)),
        img.getpixel((img.width - 3, 2)),
        img.getpixel((2, img.height - 3)),
        img.getpixel((img.width - 3, img.height - 3)),
    ]
    return tuple(sum(p[i] for p in pixels) // 4 for i in range(3))


def _is_bg_pixel(pixel, bg_color: tuple, tolerance: int = 35) -> bool:
    """Check if a pixel matches the background color."""
    return all(abs(pixel[i] - bg_color[i]) < tolerance for i in range(3))


def _compute_bg_ratios(img: Image.Image, axis: str,
                       bg_color: tuple, tolerance: int = 35) -> list[float]:
    """Compute bg-pixel ratio for each row (axis='y') or column (axis='x')."""
    w, h = img.size
    length = w if axis == "x" else h
    cross = h if axis == "x" else w
    step = max(1, cross // 120)

    ratios = []
    for pos in range(length):
        bg_count = 0
        samples = 0
        for c in range(0, cross, step):
            px = img.getpixel((pos, c)) if axis == "x" else img.getpixel((c, pos))
            if _is_bg_pixel(px, bg_color, tolerance):
                bg_count += 1
            samples += 1
        ratios.append(bg_count / samples if samples else 0)
    return ratios


def _find_gap_centers(ratios: list[float], num_cells: int,
                      total_length: int) -> list[int]:
    """Find the center positions of gaps between cells.

    Searches near each expected boundary for the column/row with the
    highest background ratio — that's the gap center.
    """
    cell_size = total_length / num_cells
    search_window = int(cell_size * 0.2)  # look +/- 20% of cell size

    gap_centers = []
    for i in range(1, num_cells):
        expected = int(i * cell_size)
        search_start = max(0, expected - search_window)
        search_end = min(len(ratios), expected + search_window)

        best_pos = expected
        best_ratio = -1.0
        for pos in range(search_start, search_end):
            if ratios[pos] > best_ratio:
                best_ratio = ratios[pos]
                best_pos = pos
        gap_centers.append(best_pos)

    return gap_centers


def detect_grid(img: Image.Image, rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    """
    Hierarchical grid detection: first splits into rows, then detects
    column gaps independently per row. This prevents cutting into stickers
    when columns are not perfectly aligned across rows.
    """
    bg_color = _detect_bg_color(img)

    # Step 1: find row gaps globally
    y_ratios = _compute_bg_ratios(img, "y", bg_color)
    row_gaps = _find_gap_centers(y_ratios, rows, img.height)
    row_edges = [0] + row_gaps + [img.height]

    # Step 2: for each row strip, detect column gaps independently
    boxes = []
    for r in range(rows):
        y1 = row_edges[r]
        y2 = row_edges[r + 1]
        row_strip = img.crop((0, y1, img.width, y2))

        x_ratios = _compute_bg_ratios(row_strip, "x", bg_color)
        col_gaps = _find_gap_centers(x_ratios, cols, row_strip.width)
        col_edges = [0] + col_gaps + [img.width]

        for c in range(cols):
            boxes.append((col_edges[c], y1, col_edges[c + 1], y2))

    return boxes


def _clean_edges(img: Image.Image, bg_color: tuple, tolerance: int = 35) -> Image.Image:
    """
    Clean sticker edges by scanning inward from each border.
    Rows/columns that are majority background get fully painted as background,
    removing bleed-in content from neighboring cells.
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    pixels = img.load()
    w, h = img.size
    bg_rgba = (*bg_color, 255)

    # Scan up to 4% of dimension from each edge (reduced to preserve text)
    edge_h = max(8, int(h * 0.04))
    edge_w = max(8, int(w * 0.04))

    # Only clean rows/cols that are almost entirely background (>90%)
    # This avoids wiping out text which typically occupies <50% of a row
    clean_thresh = 0.90

    # Horizontal edges (top/bottom) — scan rows
    for y_range in [range(h - 1, h - edge_h - 1, -1),  # bottom
                    range(0, edge_h)]:                    # top
        for y in y_range:
            bg_count = sum(1 for x in range(w) if _is_bg_pixel(pixels[x, y], bg_color, tolerance))
            ratio = bg_count / w
            if ratio > clean_thresh:
                for x in range(w):
                    if not _is_bg_pixel(pixels[x, y], bg_color, tolerance):
                        pixels[x, y] = bg_rgba
            else:
                break

    # Vertical edges (left/right) — scan columns
    for x_range in [range(w - 1, w - edge_w - 1, -1),  # right
                    range(0, edge_w)]:                    # left
        for x in x_range:
            bg_count = sum(1 for y in range(h) if _is_bg_pixel(pixels[x, y], bg_color, tolerance))
            ratio = bg_count / h
            if ratio > clean_thresh:
                for y in range(h):
                    if not _is_bg_pixel(pixels[x, y], bg_color, tolerance):
                        pixels[x, y] = bg_rgba
            else:
                break

    return img


def crop_cell(img: Image.Image, box: tuple, bg_color: tuple = None) -> Image.Image:
    """Crop a cell from the grid at full resolution (no downscaling)."""
    cell = img.crop(box)
    if bg_color:
        cell = _clean_edges(cell, bg_color)
    return cell


def fit_to_line_size(img: Image.Image,
                     max_w=STICKER_MAX_W, max_h=STICKER_MAX_H) -> Image.Image:
    """Downscale to LINE sticker dimensions and ensure even pixel sizes."""
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    w, h = img.size
    if w % 2 != 0:
        w -= 1
    if h % 2 != 0:
        h -= 1
    return img.resize((w, h), Image.LANCZOS)


def remove_bg_simple(img: Image.Image, tolerance: int = 30) -> Image.Image:
    """Remove green/gray background using flood-fill from image borders.

    Only removes background pixels that are connected to the image edge,
    so face shadows and other interior gray-ish areas are preserved.
    Includes green spill removal for clean edges.
    """
    from collections import deque

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    w, h = img.size
    pixels = img.load()

    # Detect bg color from corners
    corners = [pixels[2, 2], pixels[w - 3, 2],
               pixels[2, h - 3], pixels[w - 3, h - 3]]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    # Detect if background is greenish (green channel significantly higher)
    is_green_bg = bg[1] > bg[0] + 15 and bg[1] > bg[2] + 15

    # Boolean grid: True = confirmed background (to be made transparent)
    is_transparent = [[False] * h for _ in range(w)]
    visited = [[False] * h for _ in range(w)]
    queue = deque()

    def matches_bg(x, y):
        px = pixels[x, y]
        return all(abs(px[i] - bg[i]) < tolerance for i in range(3))

    def is_greenish(px, thresh=20):
        """Check if a pixel has significant green cast."""
        r, g, b = px[0], px[1], px[2]
        avg_rb = (r + b) / 2
        return g > avg_rb + thresh

    # Seed: all border pixels that match background color
    for x in range(w):
        for y in (0, h - 1):
            if matches_bg(x, y):
                visited[x][y] = True
                is_transparent[x][y] = True
                queue.append((x, y))
    for y in range(1, h - 1):
        for x in (0, w - 1):
            if not visited[x][y] and matches_bg(x, y):
                visited[x][y] = True
                is_transparent[x][y] = True
                queue.append((x, y))

    # BFS flood-fill: spread through connected bg-colored pixels
    # Use 8-connected for better coverage of narrow gaps
    directions_8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                    (0, 1), (1, -1), (1, 0), (1, 1)]
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in directions_8:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[nx][ny]:
                visited[nx][ny] = True
                if matches_bg(nx, ny):
                    is_transparent[nx][ny] = True
                    queue.append((nx, ny))

    # Second pass: aggressively remove green pixels adjacent to
    # already-transparent areas (catches green spill in narrow gaps)
    if is_green_bg:
        changed = True
        passes = 0
        while changed and passes < 5:
            changed = False
            passes += 1
            for x in range(w):
                for y in range(h):
                    if is_transparent[x][y]:
                        continue
                    px = pixels[x, y]
                    # Check if this pixel is greenish (lower threshold for
                    # pixels next to transparent areas)
                    r, g_val, b = px[0], px[1], px[2]
                    avg_rb = (r + b) / 2
                    green_dominant = g_val > avg_rb + 15
                    # Also catch bg-matching pixels not reached by flood fill
                    bg_like = matches_bg(x, y)
                    if not green_dominant and not bg_like:
                        continue
                    # Check if adjacent to transparent pixel
                    has_transparent_neighbor = False
                    for dx, dy in directions_8:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and is_transparent[nx][ny]:
                            has_transparent_neighbor = True
                            break
                    if has_transparent_neighbor:
                        is_transparent[x][y] = True
                        changed = True

    # Third pass: remove enclosed green pockets (trapped background regions
    # that flood-fill can't reach from the border)
    if is_green_bg:
        def is_pure_green(px):
            """Check if pixel is pure green (background), not yellow/teal."""
            r, g_val, b_val = px[0], px[1], px[2]
            # Pure green bg: green is high, red AND blue are both low
            # Yellow: red AND green both high → NOT pure green
            # Teal: green AND blue both high → NOT pure green
            return (g_val > 80 and g_val > r + 30 and g_val > b_val + 30)

        component_visited = [[False] * h for _ in range(w)]
        for sx in range(w):
            for sy in range(h):
                if component_visited[sx][sy] or is_transparent[sx][sy]:
                    continue
                px = pixels[sx, sy]
                if not is_pure_green(px):
                    continue
                # BFS to find connected pure-green region
                region = []
                cq = deque([(sx, sy)])
                component_visited[sx][sy] = True
                while cq:
                    cx, cy = cq.popleft()
                    region.append((cx, cy))
                    for dx, dy in directions_8:
                        nx, ny = cx + dx, cy + dy
                        if (0 <= nx < w and 0 <= ny < h
                                and not component_visited[nx][ny]
                                and not is_transparent[nx][ny]):
                            cpx = pixels[nx, ny]
                            if is_pure_green(cpx):
                                component_visited[nx][ny] = True
                                cq.append((nx, ny))
                # Small enclosed pure-green regions are trapped background
                if len(region) <= 2000:
                    for rx, ry in region:
                        is_transparent[rx][ry] = True

    # Apply: make flood-filled pixels transparent
    for x in range(w):
        for y in range(h):
            if is_transparent[x][y]:
                r, g, b, a = pixels[x, y]
                pixels[x, y] = (r, g, b, 0)

    # Edge processing: smooth alpha + green despill for edge pixels
    # Compute distance from transparent boundary (up to 4 pixels deep)
    edge_dist = [[999] * h for _ in range(w)]
    edge_queue = deque()
    for x in range(w):
        for y in range(h):
            if is_transparent[x][y]:
                edge_dist[x][y] = 0
                edge_queue.append((x, y))
    while edge_queue:
        cx, cy = edge_queue.popleft()
        d = edge_dist[cx][cy]
        if d >= 4:
            continue
        for dx, dy in directions_8:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and edge_dist[nx][ny] > d + 1:
                edge_dist[nx][ny] = d + 1
                edge_queue.append((nx, ny))

    for x in range(w):
        for y in range(h):
            if is_transparent[x][y]:
                continue
            dist = edge_dist[x][y]
            r, g, b, a = pixels[x, y]

            # Smooth alpha for pixels very close to transparent boundary
            if dist == 1:
                # Count transparent neighbors
                t_count = sum(
                    1 for dx, dy in directions_8
                    if 0 <= x+dx < w and 0 <= y+dy < h and is_transparent[x+dx][y+dy]
                )
                if t_count >= 5:
                    a = int(a * 0.5)
                elif t_count >= 3:
                    a = int(a * 0.75)

            # Green despill: reduce green cast on edge pixels (up to 4px deep)
            if is_green_bg and dist <= 4:
                avg_rb = (r + b) / 2
                green_excess = g - avg_rb
                if green_excess > 5:
                    # Stronger despill closer to the edge
                    strength = max(0.3, 1.0 - dist * 0.2)  # 1.0, 0.8, 0.6, 0.4, 0.3
                    g = int(g - green_excess * strength)
                    g = max(g, int(avg_rb))  # Don't go below neutral

            pixels[x, y] = (r, g, b, a)

    # Trim fully transparent borders
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    # Add dark outline so white text/decorations stay visible on any background
    img = _add_outline(img)

    return img


def _add_outline(img: Image.Image, outline_color=(50, 50, 50),
                 width: int = 3) -> Image.Image:
    """Add a dark outline around all non-transparent content.

    This makes white text and decorations visible on both light and dark
    chat backgrounds — standard practice for LINE stickers.
    """
    from PIL import ImageFilter

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    alpha = img.split()[3]

    # Expand the alpha mask outward to create an outline region
    expanded = alpha
    for _ in range(width):
        expanded = expanded.filter(ImageFilter.MaxFilter(3))

    # Create a solid-color layer with the expanded alpha as mask
    outline_layer = Image.new("RGBA", img.size, (*outline_color, 255))
    outline_layer.putalpha(expanded)

    # Composite: original content on top of the outline
    return Image.alpha_composite(outline_layer, img)


def process_grid_image(grid_path: Path, output_dir: Path, rows=3, cols=4, remove_bg=True):
    """Crop grid image into individual stickers.

    remove_bg defaults to True since LINE requires transparent PNG backgrounds.
    """
    sticker_dir = output_dir / "stickers"
    sticker_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(grid_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    print(f"裁切 grid 大圖 ({img.size[0]}x{img.size[1]}) → {rows*cols} 張貼圖")

    bg_color = _detect_bg_color(img)
    boxes = detect_grid(img, rows, cols)
    stickers = []

    # Save raw crops (before bg removal) for iteration
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for i, box in enumerate(boxes):
        # Crop at full resolution — no downscaling yet
        sticker = crop_cell(img, box, bg_color=bg_color)

        # Always save the raw crop (with original bg) for reference
        raw_name = f"{i+1:02d}.png"
        raw_copy = sticker.copy()
        if raw_copy.mode != "RGBA":
            raw_copy = raw_copy.convert("RGBA")
        raw_copy.save(raw_dir / raw_name, "PNG")

        if remove_bg:
            # Process bg removal at full resolution for maximum quality
            sticker = remove_bg_simple(sticker)
            # Only downscale to LINE dimensions at the very end
            sticker = fit_to_line_size(sticker)
        else:
            if sticker.mode != "RGBA":
                sticker = sticker.convert("RGBA")
            sticker = fit_to_line_size(sticker)

        filename = f"{i+1:02d}.png"
        sticker.save(sticker_dir / filename, "PNG")
        stickers.append(sticker)
        print(f"  ✓ {filename} ({sticker.size[0]}x{sticker.size[1]})")

    # Main & tab images
    if stickers:
        main = Image.new("RGBA", MAIN_IMAGE_SIZE, (0, 0, 0, 0))
        thumb = stickers[0].copy()
        thumb.thumbnail((220, 220), Image.LANCZOS)
        main.paste(thumb, ((240-thumb.width)//2, (240-thumb.height)//2),
                   thumb if thumb.mode == "RGBA" else None)
        main.save(output_dir / "main.png", "PNG")
        print(f"  ✓ main.png (240x240)")

        tab = Image.new("RGBA", TAB_IMAGE_SIZE, (0, 0, 0, 0))
        thumb2 = stickers[0].copy()
        thumb2.thumbnail((86, 64), Image.LANCZOS)
        tab.paste(thumb2, ((96-thumb2.width)//2, (74-thumb2.height)//2),
                  thumb2 if thumb2.mode == "RGBA" else None)
        tab.save(output_dir / "tab.png", "PNG")
        print(f"  ✓ tab.png (96x74)")

    return stickers


def main():
    parser = argparse.ArgumentParser(description="LINE 貼圖一鍵生成（KIE AI + GPT Image-2）")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pet", action="store_true", help="寵物版貼圖（貓咪風格用語）")
    group.add_argument("--dog", action="store_true", help="寵物版貼圖（狗狗風格用語）")
    group.add_argument("--kid", action="store_true", help="小孩版貼圖")

    parser.add_argument("--photos", nargs="+", help="參考照片的 URL（可多張）")
    parser.add_argument("--text-only", action="store_true", help="純文字生成（不用照片）")
    parser.add_argument("--phrases", help="自訂文字，逗號分隔（例：汪汪,肚子餓,想睡覺）")
    parser.add_argument("--description", default="", help="額外描述主角特徵（例：橘貓、短毛、藍色項圈）")
    parser.add_argument("--output", "-o", default="./output", help="輸出資料夾")
    parser.add_argument("--remove-bg", action="store_true", help="移除灰色背景（上架用）")
    parser.add_argument("--skip-generate", help="跳過生圖，直接裁切已有的圖片")
    parser.add_argument("--rows", type=int, default=3, help="Grid 行數")
    parser.add_argument("--cols", type=int, default=4, help="Grid 列數")

    args = parser.parse_args()

    if not KIE_API_KEY:
        print("錯誤：請在 .env 中設定 KIE_AI_API_KEY")
        sys.exit(1)

    # Determine mode & phrases
    if args.pet:
        mode = "pet"
        phrases = PET_PHRASES
    elif args.dog:
        mode = "pet"
        phrases = PET_DOG_PHRASES
    else:
        mode = "kid"
        phrases = KID_PHRASES

    if args.phrases:
        phrases = [p.strip() for p in args.phrases.split(",")]
        if len(phrases) != 12:
            print(f"警告：提供了 {len(phrases)} 句文字，建議 12 句（4x3 grid）")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Skip generate mode ---
    if args.skip_generate:
        grid_path = Path(args.skip_generate)
        if not grid_path.exists():
            print(f"找不到圖片：{grid_path}")
            sys.exit(1)
        process_grid_image(grid_path, output_dir, args.rows, args.cols, args.remove_bg)
        print(f"\n完成！貼圖已存到：{output_dir.resolve()}")
        return

    # --- Generate ---
    prompt = build_prompt(mode, phrases, args.description)

    if args.text_only or not args.photos:
        task_id = create_task_text_to_image(prompt)
    else:
        image_urls = [upload_photo_to_temp(p) for p in args.photos]
        # Prepend instruction about using reference photos
        photo_prompt = f"用上傳的照片中的形象作為貼圖主體，保留照片中的外觀特徵（毛色、花紋、五官）。其他表情和動作自行生成。\n\n{prompt}"
        task_id = create_task_image_to_image(photo_prompt, image_urls)

    # --- Poll for result ---
    result = poll_task(task_id)

    # Parse result URLs
    result_json = json.loads(result.get("resultJson", "{}"))
    image_urls = result_json.get("resultUrls", [])

    if not image_urls:
        print("錯誤：沒有收到生成的圖片")
        print(f"原始回應：{result}")
        sys.exit(1)

    # Download grid image
    grid_path = output_dir / "grid_raw.png"
    download_image(image_urls[0], grid_path)

    # Crop into individual stickers
    process_grid_image(grid_path, output_dir, args.rows, args.cols, args.remove_bg)

    print(f"\n{'='*50}")
    print(f"完成！共生成 {args.rows * args.cols} 張貼圖")
    print(f"輸出資料夾：{output_dir.resolve()}")
    print(f"\n下一步：")
    print(f"  1. 打開 LINE 拍貼 App")
    print(f"  2. 建立新貼圖組")
    print(f"  3. 匯入 {(output_dir / 'stickers').resolve()} 裡的圖片")
    print(f"  4. 發布即可使用！")


if __name__ == "__main__":
    try:
        main()
    except StickerError as e:
        print(f"\n錯誤：{e}")
        sys.exit(1)
