import os
import asyncio
import signal
import traceback
import pytesseract
import logging
import sys
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import Message
from playwright.async_api import async_playwright

# --- 1. LOGLAMA ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BorsaMatrisi")
sys.stdout.reconfigure(line_buffering=True)

pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# --- 2. AYARLAR ---
API_ID       = int(os.environ.get("API_ID", 0))
API_HASH     = os.environ.get("API_HASH", "")
BOT_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
SESSION_STR  = os.environ.get("SESSION_STRING", "")
TARGET_BOT   = "ucretsizderinlikbot"

# --- 3. CLIENT'LAR ---
user_app = Client(
    "userbot",
    session_string=SESSION_STR,
    api_id=API_ID,
    api_hash=API_HASH
)
bot_app = Client(
    "mainbot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# --- 4. GÖRSEL ÜRETICI ---
async def generate_premium_image(hisse_kodu, alici_html, satici_html):
    html_template = f"""<!DOCTYPE html>
    <html lang="tr"><head><meta charset="UTF-8"><style>
        body {{ background-color: #041a12; font-family: sans-serif; color: #ffffff;
               width: 600px; height: 700px; padding: 30px; box-sizing: border-box; }}
        .header {{ border-bottom: 2px solid #00ffaa; color: #00ffaa;
                   font-size: 28px; font-weight: bold; padding-bottom: 10px; }}
        .box {{ border: 2px solid #00ffaa; padding: 15px; margin-top: 20px; border-radius: 8px; }}
    </style></head><body>
        <div class="header">BORSA MATRİSİ — {hisse_kodu.upper()}</div>
        <div class="box">{alici_html}</div>
        <div class="box">{satici_html}</div>
    </body></html>"""
    file_path = f"temp_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 660, "height": 760})
        await page.set_content(html_template)
        await page.screenshot(path=file_path, full_page=True)
        await browser.close()
    return file_path

# --- 5. OCR ---
def process_ocr(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang="tur")
    logger.info(f"OCR tamamlandı:\n{text[:200]}")
    # TODO: Gerçek parse mantığı buraya eklenecek
    return "<div>İŞ YATIRIM: 1.50M</div>", "<div>GARANTİ: 1.20M</div>"

# --- 6. HANDLER'LAR ---
@bot_app.on_message(filters.command("test"))
async def test_cmd(client: Client, message: Message):
    logger.info(f"✅ /test — kullanıcı: {message.from_user.id}")
    await message.reply_text("✅ Sistem çalışıyor!")

@bot_app.on_message(filters.command("akd") | filters.command("derinlik"))
async def handle_request(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ Kullanım: /akd HISSE")
        return

    hisse = message.command[1].upper()
    logger.info(f"📥 /akd isteği — hisse: {hisse}, kullanıcı: {message.from_user.id}")
    wait_msg = await message.reply_text(f"⏳ {hisse} taranıyor...")

    try:
        await user_app.send_message(TARGET_BOT, f"/akd {hisse}")
        await asyncio.sleep(6)

        img_path = None
        async for msg in user_app.get_chat_history(TARGET_BOT, limit=3):
            if msg.photo:
                img_path = await user_app.download_media(msg.photo)
                break

        if not img_path:
            await wait_msg.edit("❌ Hedef bottan görsel gelmedi.")
            return

        alici, satici = await asyncio.to_thread(process_ocr, img_path)
        final_img = await generate_premium_image(hisse, alici, satici)
        await message.reply_photo(final_img, caption=f"⚡️ {hisse} derinlik verisi")

        for f in [img_path, final_img]:
            if f and os.path.exists(f):
                os.remove(f)

        await wait_msg.delete()

    except Exception:
        logger.error(traceback.format_exc())
        await wait_msg.edit("❌ Bir hata oluştu. Loglara bakılıyor...")

# --- 7. BAŞLATICI — KRİTİK DÜZELTME ---
# asyncio.run() KULLANILMIYOR. Pyrogram'ın kendi .run() metodu kullanılıyor.
async def main():
    logger.info("🚀 Clientlar başlatılıyor...")

    async with user_app, bot_app:
        logger.info("✅ Her iki client aktif — komut bekleniyor...")
        # Manuel stop event: idle() yerine bu pattern iki client'la güvenli çalışır
        stop_event = asyncio.Event()

        def _stop(*_):
            logger.info("🛑 Durdurma sinyali alındı.")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _stop)

        await stop_event.wait()

    logger.info("👋 Kapatıldı.")

if __name__ == "__main__":
    # Pyrogram ile uyumlu tek doğru başlatma yöntemi:
    bot_app.run(main())
