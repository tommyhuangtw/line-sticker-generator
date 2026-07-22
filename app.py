"""
LINE 貼圖生成器 Web UI
=====================
Flask server providing a simple web interface for generating LINE stickers.
"""

import base64
import hashlib
import io
import json
import os
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory

from generate_stickers import (
    StickerError,
    KIE_API_KEY, FAL_API_KEY,
    PET_PHRASES, PET_DOG_PHRASES, KID_PHRASES, CHARACTER_PHRASES,
    ALL_PHRASE_STYLES, DRAWING_STYLES, AUDIENCES, AUDIENCE_LIST,
    build_prompt, generate_phrases_with_ai,
    api_request, check_task_status,
    create_task_text_to_image, create_task_image_to_image,
    fal_create_task_text_to_image, fal_create_task_image_to_image,
    fal_check_task_status,
    download_image, process_grid_image, process_portrait_image,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload

OUTPUT_BASE = Path(__file__).parent / "output"
OUTPUT_BASE.mkdir(exist_ok=True)

# Bundled read-only example sticker sets (shown in the history gallery so a
# fresh clone isn't empty). Served from examples/ instead of output/.
EXAMPLES_BASE = Path(__file__).parent / "examples"


def resolve_task_dir(task_id):
    """Return the directory for a task id, checking output/ then examples/."""
    task_dir = OUTPUT_BASE / task_id
    if task_dir.exists():
        return task_dir
    return EXAMPLES_BASE / task_id

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")


def upload_to_cloudinary(file_bytes: bytes, filename: str) -> str:
    """Upload image bytes to Cloudinary (signed upload), return the public URL."""
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
        raise StickerError(
            "請在 .env 中設定 CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET"
        )

    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"

    # Generate signature for signed upload
    timestamp = str(int(time.time()))
    params_to_sign = f"folder=line_stickers&timestamp={timestamp}{CLOUDINARY_API_SECRET}"
    signature = hashlib.sha1(params_to_sign.encode()).hexdigest()

    # Build multipart form data
    boundary = "----CloudinaryBoundary9876"
    parts = [
        ("api_key", CLOUDINARY_API_KEY),
        ("timestamp", timestamp),
        ("signature", signature),
        ("folder", "line_stickers"),
    ]

    body = b""
    for name, value in parts:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()

    # File part
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    body += b"Content-Type: application/octet-stream\r\n\r\n"
    body += file_bytes
    body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return data["secure_url"]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise StickerError(f"Cloudinary 上傳失敗: {e.code} {error_body}")
    except (urllib.error.URLError, KeyError) as e:
        raise StickerError(f"Cloudinary 上傳失敗: {e}")


def _optimize_cloudinary_url(url: str) -> str:
    """Add Cloudinary transformations to reduce image size for the KIE API.

    Inserts /f_jpg,q_auto,w_2048,c_limit/ into the URL to convert PNGs to
    compressed JPGs (max 2048px wide). This prevents oversized images from
    causing KIE API 500 errors.
    """
    marker = "/upload/"
    if marker not in url:
        return url
    return url.replace(marker, f"{marker}f_jpg,q_auto,w_2048,c_limit/")


# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/phrases/<mode>")
def get_phrases(mode):
    """Return default phrases for a given mode and optional style."""
    style = request.args.get("style", "")
    styles = ALL_PHRASE_STYLES.get(mode, ALL_PHRASE_STYLES["pet"])
    if style and style in styles:
        return jsonify(styles[style])
    # Return first style as default
    return jsonify(list(styles.values())[0])


@app.route("/api/phrase-styles/<mode>")
def get_phrase_styles(mode):
    """Return available phrase style names for a mode."""
    styles = ALL_PHRASE_STYLES.get(mode, ALL_PHRASE_STYLES["pet"])
    return jsonify(list(styles.keys()))


@app.route("/api/audiences")
def get_audiences():
    """Return available audience options."""
    return jsonify([
        {"id": k, "label": v["label"], "desc": v["desc"]}
        for k, v in AUDIENCES.items()
    ])


@app.route("/api/audience-phrases/<audience_id>")
def get_audience_phrases(audience_id):
    """Return default phrases for a given audience."""
    aud = AUDIENCES.get(audience_id)
    if not aud:
        return jsonify(AUDIENCES["通用日常"]["phrases"])
    return jsonify(aud["phrases"])


@app.route("/api/generate-phrases", methods=["POST"])
def gen_phrases():
    """Use AI to generate 12 sticker phrases based on character personality."""
    data = request.get_json()
    character_name = data.get("characterName", "")
    personality = data.get("personality", "")
    try:
        phrases = generate_phrases_with_ai(character_name, personality)
        return jsonify({"phrases": phrases})
    except StickerError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload", methods=["POST"])
def upload_photo():
    """Upload a photo to Cloudinary and return the URL."""
    if "photo" not in request.files:
        return jsonify({"error": "沒有收到照片"}), 400

    photo = request.files["photo"]
    if photo.filename == "":
        return jsonify({"error": "沒有選擇檔案"}), 400

    try:
        file_bytes = photo.read()
        url = upload_to_cloudinary(file_bytes, photo.filename)
        return jsonify({"url": url})
    except StickerError as e:
        return jsonify({"error": str(e)}), 500


# How long to keep polling the de-text task before giving up and keeping the
# sticker-#1 main/tab. Measured from when the task was submitted.
PORTRAIT_WAIT_SECONDS = 180

PORTRAIT_PROMPT = """請把這張貼圖裡的文字完全移除，只保留角色本身。

【嚴格規則】
・角色的外觀、配色、線條、姿勢、表情都要跟原圖完全一致，不要重畫、不要改風格
・移除畫面上所有文字、字母、數字、對話框，並把原本被文字蓋住的地方自然補完
・角色置中、佔畫面主要區域，四周留出背景空間
・背景改成單一的純亮綠色（#00B140），像綠幕一樣乾淨，方便後續去背
"""


def save_meta(task_dir: Path, meta: dict):
    """Persist metadata.json for a task."""
    with open(task_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def submit_portrait_task(task_dir: Path, meta: dict) -> dict:
    """Ask the provider to strip the text from sticker #1 for main/tab.

    Feeding back an already-generated sticker (rather than generating a fresh
    portrait from the photos) keeps the character identical to the set. The
    raw crop is used because it still has the green background intact.

    Records portraitTaskId/portraitProvider on meta, or portraitError when it
    could not be submitted. Never raises — main/tab already exist as fallback.
    """
    source = task_dir / "raw" / "01.png"
    if not source.exists():
        meta["portraitError"] = "找不到 raw/01.png，無法產生無文字主圖"
        return meta

    try:
        with open(source, "rb") as f:
            public_url = _optimize_cloudinary_url(
                upload_to_cloudinary(f.read(), "sticker01.png"))
    except StickerError as e:
        meta["portraitError"] = f"上傳貼圖到 Cloudinary 失敗：{e}"
        return meta

    for provider, submit in (
        ("kie", lambda: create_task_image_to_image(
            PORTRAIT_PROMPT, [public_url], aspect_ratio="1:1")),
        ("fal", lambda: fal_create_task_image_to_image(
            PORTRAIT_PROMPT, [public_url], image_size="square_hd")),
    ):
        if not (KIE_API_KEY if provider == "kie" else FAL_API_KEY):
            continue
        try:
            meta["portraitTaskId"] = submit()
            meta["portraitProvider"] = provider
            meta["portraitDeadline"] = time.time() + PORTRAIT_WAIT_SECONDS
            meta.pop("portraitError", None)
            return meta
        except StickerError as e:
            meta["portraitError"] = f"{provider} 去文字任務提交失敗：{e}"

    return meta


def poll_portrait_task(task_dir: Path, meta: dict) -> bool:
    """Check the de-text task once; apply it to main/tab when ready.

    Returns True when the portrait step has settled (succeeded, failed, or
    timed out) and the caller should report the task as done. Returns False
    while it is still generating.
    """
    portrait_id = meta.get("portraitTaskId")
    provider = meta.get("portraitProvider", "kie")

    def settle(error: str = None):
        meta.pop("portraitTaskId", None)
        meta.pop("portraitDeadline", None)
        if error:
            meta["portraitError"] = error
        else:
            meta["portraitApplied"] = True
        save_meta(task_dir, meta)
        return True

    try:
        data = (fal_check_task_status(portrait_id) if provider == "fal"
                else check_task_status(portrait_id))
    except StickerError as e:
        return settle(f"查詢去文字任務失敗：{e}")

    state = data.get("state", "unknown")
    if state == "fail":
        return settle(f"去文字生圖失敗：{data.get('failMsg', '未知原因')}")
    if state != "success":
        if time.time() >= meta.get("portraitDeadline", 0):
            return settle("去文字生圖逾時，主圖沿用第一張貼圖")
        return False

    try:
        urls = json.loads(data.get("resultJson", "{}")).get("resultUrls", [])
        if not urls:
            return settle("去文字任務沒有回傳圖片 URL")
        portrait_path = task_dir / "portrait_raw.png"
        download_image(urls[0], portrait_path)
        process_portrait_image(portrait_path, task_dir, remove_bg=True)
        return settle()
    except Exception as e:
        return settle(f"處理無文字主圖失敗：{e}")


@app.route("/api/generate", methods=["POST"])
def generate():
    """Start a sticker generation task."""
    if not KIE_API_KEY:
        return jsonify({"error": "API key 未設定"}), 500

    data = request.get_json()
    mode = data.get("mode", "pet")
    phrases = data.get("phrases", [])
    description = data.get("description", "")
    personality = data.get("personality", "")
    drawing_style = data.get("drawingStyle", "")
    audience = data.get("audience", "")
    photo_urls = data.get("photoUrls", [])

    if not phrases or len(phrases) == 0:
        phrases_map = {
            "pet": PET_PHRASES, "dog": PET_DOG_PHRASES,
            "kid": KID_PHRASES, "character": CHARACTER_PHRASES,
        }
        phrases = phrases_map.get(mode, PET_PHRASES)

    prompt_mode = mode if mode == "character" else ("pet" if mode in ("pet", "dog") else "kid")
    prompt = build_prompt(prompt_mode, phrases, description, personality, drawing_style, audience)

    # Pick provider: prefer KIE, fall back to fal.ai
    provider = "kie" if KIE_API_KEY else ("fal" if FAL_API_KEY else None)
    if not provider:
        return jsonify({"error": "沒有設定任何圖片生成 API key（KIE_AI_API_KEY 或 FAL_KEY）"}), 500

    try:
        photo_prompt = prompt
        if photo_urls:
            optimized_urls = [_optimize_cloudinary_url(u) for u in photo_urls]
            photo_prompt = (
                "用上傳的照片中的形象作為貼圖主體，保留照片中的外觀特徵"
                "（毛色、花紋、五官）。其他表情和動作自行生成。\n\n" + prompt
            )
        else:
            optimized_urls = []

        if provider == "kie":
            try:
                if optimized_urls:
                    task_id = create_task_image_to_image(photo_prompt, optimized_urls)
                else:
                    task_id = create_task_text_to_image(prompt)
            except StickerError:
                # KIE failed — try fal.ai as fallback
                if FAL_API_KEY:
                    provider = "fal"
                    if optimized_urls:
                        task_id = fal_create_task_image_to_image(photo_prompt, optimized_urls)
                    else:
                        task_id = fal_create_task_text_to_image(prompt)
                else:
                    raise
        else:
            if optimized_urls:
                task_id = fal_create_task_image_to_image(photo_prompt, optimized_urls)
            else:
                task_id = fal_create_task_text_to_image(prompt)

        # Create output directory and save metadata
        task_dir = OUTPUT_BASE / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "provider": provider,
            "mode": mode,
            "description": description,
            "personality": personality,
            "drawingStyle": drawing_style,
            "audience": audience,
            "phrases": phrases,
            "photoUrls": photo_urls,
            "createdAt": time.time(),
        }
        with open(task_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False)

        return jsonify({"taskId": task_id})

    except StickerError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status/<task_id>")
def status(task_id):
    """Check task status. When done, download and crop the image."""
    # Determine which provider to use for status check
    task_dir = OUTPUT_BASE / task_id
    meta_path = task_dir / "metadata.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    provider = meta.get("provider", "kie")

    try:
        if provider == "fal":
            data = fal_check_task_status(task_id)
        else:
            data = check_task_status(task_id)
    except StickerError as e:
        return jsonify({"state": "error", "message": str(e)}), 500

    state = data.get("state", "unknown")

    if state == "fail":
        # If KIE failed, automatically retry with fal.ai
        if provider == "kie" and FAL_API_KEY:
            try:
                meta = {}
                if meta_path.exists():
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)

                # Rebuild the prompt from saved metadata
                mode = meta.get("mode", "pet")
                phrases = meta.get("phrases", [])
                description = meta.get("description", "")
                personality = meta.get("personality", "")
                drawing_style = meta.get("drawingStyle", "")
                audience = meta.get("audience", "")
                photo_urls = meta.get("photoUrls", [])

                prompt_mode = mode if mode == "character" else ("pet" if mode in ("pet", "dog") else "kid")
                prompt = build_prompt(prompt_mode, phrases, description, personality, drawing_style, audience)

                if photo_urls:
                    optimized_urls = [_optimize_cloudinary_url(u) for u in photo_urls]
                    photo_prompt = (
                        "用上傳的照片中的形象作為貼圖主體，保留照片中的外觀特徵"
                        "（毛色、花紋、五官）。其他表情和動作自行生成。\n\n" + prompt
                    )
                    new_task_id = fal_create_task_image_to_image(photo_prompt, optimized_urls)
                else:
                    new_task_id = fal_create_task_text_to_image(prompt)

                # Create new task directory and save metadata
                new_task_dir = OUTPUT_BASE / new_task_id
                new_task_dir.mkdir(parents=True, exist_ok=True)
                meta["provider"] = "fal"
                meta["fallbackFrom"] = task_id
                with open(new_task_dir / "metadata.json", "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False)

                # Tell the frontend to switch to the new task
                return jsonify({
                    "state": "retry",
                    "newTaskId": new_task_id,
                    "message": "KIE AI 生圖失敗，已自動切換到 fal.ai 重試",
                })
            except StickerError:
                pass  # fal.ai also failed, fall through to return error

        return jsonify({
            "state": "fail",
            "message": data.get("failMsg", "生圖失敗"),
        })

    if state == "success":
        task_dir = OUTPUT_BASE / task_id
        sticker_dir = task_dir / "stickers"

        def finished():
            return jsonify({
                "state": "done",
                "stickers": sorted(f.name for f in sticker_dir.glob("*.png")),
                "gridImage": "grid_raw.png",
                "portraitError": meta.get("portraitError"),
            })

        # Already cropped — the only work left may be the de-text main/tab.
        if sticker_dir.exists() and any(sticker_dir.iterdir()):
            if meta.get("portraitTaskId") and not poll_portrait_task(task_dir, meta):
                return jsonify({"state": "portrait", "progress": 95})
            return finished()

        # Download and crop
        try:
            result_json = json.loads(data.get("resultJson", "{}"))
            image_urls = result_json.get("resultUrls", [])
            if not image_urls:
                return jsonify({"state": "error", "message": "沒有收到圖片 URL"}), 500

            task_dir.mkdir(parents=True, exist_ok=True)
            grid_path = task_dir / "grid_raw.png"
            download_image(image_urls[0], grid_path)
            process_grid_image(grid_path, task_dir, rows=3, cols=4, remove_bg=True)

            # main/tab currently carry sticker #1's text. Ask the provider to
            # strip it; the frontend keeps polling until that settles.
            submit_portrait_task(task_dir, meta)
            save_meta(task_dir, meta)
            if meta.get("portraitTaskId"):
                return jsonify({"state": "portrait", "progress": 95})
            return finished()

        except Exception as e:
            return jsonify({"state": "error", "message": str(e)}), 500

    # Still processing
    return jsonify({
        "state": state,
        "progress": data.get("progress", 0),
    })


@app.route("/api/preview/<task_id>/<path:filename>")
def preview(task_id, filename):
    """Serve a generated sticker image for preview."""
    task_dir = resolve_task_dir(task_id)

    # Could be in stickers/ subdirectory or root
    if (task_dir / "stickers" / filename).exists():
        return send_from_directory(task_dir / "stickers", filename)
    elif (task_dir / filename).exists():
        return send_from_directory(task_dir, filename)
    else:
        return "Not found", 404


@app.route("/api/download/<task_id>")
def download(task_id):
    """Download all stickers as a ZIP file."""
    task_dir = resolve_task_dir(task_id)
    sticker_dir = task_dir / "stickers"

    if not sticker_dir.exists():
        return "Not found", 404

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add individual stickers
        for f in sorted(sticker_dir.glob("*.png")):
            zf.write(f, f"stickers/{f.name}")

        # Add main and tab images if they exist
        for extra in ("main.png", "tab.png", "grid_raw.png"):
            extra_path = task_dir / extra
            if extra_path.exists():
                zf.write(extra_path, extra)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"line_stickers_{task_id[:8]}.zip",
    )


def _build_task_entry(task_dir, is_example=False):
    """Build a gallery entry dict from a task directory, or None if incomplete."""
    sticker_dir = task_dir / "stickers"
    if not sticker_dir.exists() or not any(sticker_dir.glob("*.png")):
        return None

    meta_path = task_dir / "metadata.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    else:
        meta = {"mode": "unknown", "createdAt": task_dir.stat().st_mtime}

    sticker_files = sorted(f.name for f in sticker_dir.glob("*.png"))
    photo_urls = meta.get("photoUrls", [])
    return {
        "taskId": task_dir.name,
        "mode": meta.get("mode", "unknown"),
        "description": meta.get("description", ""),
        "createdAt": meta.get("createdAt", task_dir.stat().st_mtime),
        "stickers": sticker_files,
        "canRegenerate": bool(photo_urls) and bool(meta.get("phrases")),
        "isExample": is_example,
    }


@app.route("/api/tasks")
def list_tasks():
    """List all completed tasks plus bundled examples for the history gallery."""
    tasks = []
    for task_dir in OUTPUT_BASE.iterdir():
        if task_dir.is_dir():
            entry = _build_task_entry(task_dir)
            if entry:
                tasks.append(entry)

    if EXAMPLES_BASE.exists():
        for task_dir in EXAMPLES_BASE.iterdir():
            if task_dir.is_dir():
                entry = _build_task_entry(task_dir, is_example=True)
                if entry:
                    tasks.append(entry)

    # User tasks first (newest first), bundled examples always last.
    tasks.sort(key=lambda t: (t["isExample"], -t["createdAt"]))
    return jsonify(tasks)


@app.route("/api/tasks/<task_id>/metadata")
def get_task_metadata(task_id):
    """Return full metadata for a task (for re-generation)."""
    task_dir = resolve_task_dir(task_id)
    meta_path = task_dir / "metadata.json"
    if not meta_path.exists():
        return jsonify({"error": "此紀錄沒有保存設定，無法重新生成"}), 404
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    return jsonify(meta)


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """Delete a task and its output files."""
    import shutil
    task_dir = OUTPUT_BASE / task_id
    if not task_dir.exists():
        return jsonify({"error": "Not found"}), 404
    shutil.rmtree(task_dir)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("LINE 貼圖生成器 Web UI")
    print("http://localhost:8080")
    app.run(debug=True, port=8080)
