import os
import asyncio
import traceback
import pytesseract
import logging
import sys
from PIL import Image
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from playwright.async_api import async_playwright

# 1. LOGLARI ANLIK AKIŞA ZORLA
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("BorsaMatrisi")
sys.stdout.reconfigure(line_buffering=True)

pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# 2. AYARLAR
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_BOT = "ucretsizderinlikbot"

# 3. CLIENTLAR (Bot ve Userbot'u birbirinden ayırdık)
user_app = Client("userbot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
bot_app = Client("mainbot", bot_token=TELEGRAM_TOKEN)

# 4. GÖRSEL İŞLEMCİ
async def generate_premium_image(hisse_kodu, alici_html, satici_html):
    html_template = f"""<html><body><h1 style="color:white">{hisse_kodu.upper()}</h1>{alici_html}{satici_html}</body></html>"""
    file_path = f"temp_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page()
        await page.set_content(html_template)
        await page.screenshot(path=file_path)
        await browser.close()
    return file_path

# 5. KOMUTLAR
@bot_app.on_message(filters.command(["kontrol"]) & filters.bot)
async def kontrol_test(client, message):
    logger.info(f"👉 /kontrol alındı: {message.from_user.id}")
    await message.reply_text("✅ Sistem aktif ve bağlantı sorunsuz!")

@bot_app.on_message(filters.command(["akd", "derinlik"]) & filters.bot)
async def handle_request(client, message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ Kullanım: /akd HİSSE")
        return
    
    hisse = message.command[1].upper()
    wait_msg = await message.reply_text(f"⏳ {hisse} taranıyor...")
    
    try:
        await user_app.send_message(TARGET_BOT, f"/akd {hisse}")
        await asyncio.sleep(5)
        
        async for msg in user_app.get_chat_history(TARGET_BOT, limit=1):
            if msg.photo:
                img_path = await user_app.download_media(msg.photo)
                # OCR ve görsel oluşturma işlemleri buraya...
                await message.reply_photo(img_path, caption=f"⚡️ {hisse} verisi.")
                await wait_msg.delete()
                return
        await wait_msg.edit("❌ Resim bulunamadı.")
    except Exception as e:
        logger.error(f"Hata: {e}")
        await wait_msg.edit(f"Hata: {str(e)}")

# 6. BAŞLATICI
async def start_systems():
    logger.info("🚀 Başlatılıyor...")
    await bot_app.start()
    await user_app.start()
    logger.info("💎 Sistem 7/24 hazır!")
    await idle()

if __name__ == "__main__":
    asyncio.run(start_systems())
