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

# Tesseract yolu (Dockerfile'daki kuruluma göre)
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# --- 2. AYARLAR ---
API_ID      = int(os.environ.get("API_ID", 0))
API_HASH    = os.environ.get("API_HASH", "")
BOT_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
SESSION_STR = os.environ.get("SESSION_STRING", "")
TARGET_BOT  = "ucretsizderinlikbot"

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
               width: 600px; padding: 30px; box-sizing: border-box; }}
        .header {{ border-bottom: 2px solid #00ffaa; color: #00ffaa;
                   font-size: 28px; font-weight: bold; padding-bottom: 10px; margin-bottom: 20px; }}
        .box {{ border: 2px solid #00ffaa; padding: 15px; margin-top: 20px; border-radius: 8px; }}
    </style></head><body>
        <div class="header">BORSA MATRİSİ — {hisse_kodu.upper()}</div>
        <div class="box">{alici_html}</div>
        <div class="box">{satici_html}</div>
    </body></html>"""

    file_path = f"/tmp/temp_{hisse_kodu}.png"

    async with async_playwright() as p:
        # Sistem Chromium'unu kullan (Playwright'ın indirdiğini değil)
        browser = await p.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        page = await browser.new_page(viewport={"width": 660, "height": 760})
        await page.set_content(html_template, wait_until="networkidle")
        await page.screenshot(path=file_path, full_page=True)
        await browser.close()

    logger.info(f"✅ Görsel oluşturuldu: {file_path}")
    return file_path

# --- 5. OCR ---
def process_ocr(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang="tur")
    logger.info(f"📄 OCR sonucu:\n{text[:300]}")
    # TODO: Gerçek parse mantığı buraya
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
        # Hedef bota mesaj gönder
        logger.info(f"📤 Hedef bota gönderiliyor: /akd {hisse}")
        await user_app.send_message(TARGET_BOT, f"/akd {hisse}")

        # Cevap için bekle (hedef bot yavaş olabilir)
        await asyncio.sleep(8)

        # Son mesajları tara (limit=5: birden fazla mesaj gelmiş olabilir)
        img_path = None
        logger.info("🔍 Hedef botun cevabı aranıyor...")
        async for msg in user_app.get_chat_history(TARGET_BOT, limit=5):
            logger.info(f"   → Mesaj id:{msg.id} | photo:{bool(msg.photo)} | text:{msg.text[:30] if msg.text else '-'}")
            if msg.photo:
                img_path = await user_app.download_media(msg.photo, file_name=f"/tmp/ocr_{hisse}.jpg")
                logger.info(f"✅ Görsel indirildi: {img_path}")
                break

        if not img_path:
            logger.warning("⚠️ Hedef bottan görsel gelmedi.")
            await wait_msg.edit("❌ Hedef bottan görsel gelmedi. Bot meşgul olabilir, tekrar dene.")
            return

        # OCR
        alici, satici = await asyncio.to_thread(process_ocr, img_path)

        # Görsel oluştur
        final_img = await generate_premium_image(hisse, alici, satici)

        # Kullanıcıya gönder
        await message.reply_photo(final_img, caption=f"⚡️ {hisse} derinlik verisi")
        await wait_msg.delete()

        # Temizlik
        for f in [img_path, final_img]:
            if f and os.path.exists(f):
                os.remove(f)

    except Exception:
        err = traceback.format_exc()
        logger.error(f"💥 HATA:\n{err}")
        await wait_msg.edit("❌ Bir hata oluştu. Loglara bakılıyor...")

# --- 7. BAŞLATICI ---
async def main():
    logger.info("🚀 Clientlar başlatılıyor...")
    async with bot_app, user_app:
        logger.info("✅ Her iki client aktif — komut bekleniyor...")
        stop_event = asyncio.Event()

        def _stop(*_):
            logger.info("🛑 Durdurma sinyali alındı.")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _stop)

        await stop_event.wait()

    logger.info("👋 Kapatıldı.")

if __name__ == "__main__":
    bot_app.run(main())
