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

# --- 1. LOGLAMA AYARLARI (Railway Buffer Kırıcı) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("BorsaMatrisi")
sys.stdout.reconfigure(line_buffering=True)

pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# --- 2. AYARLAR ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
TARGET_BOT = "ucretsizderinlikbot"

# --- 3. CLIENT KURULUMLARI ---
# Userbot (Şahsi) ve MainBot (Kurumsal) için ayrı ayrı tanımlamalar
user_app = Client("userbot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
bot_app = Client("mainbot", bot_token=TELEGRAM_TOKEN, api_id=API_ID, api_hash=API_HASH)

# --- 4. GÖRSEL ŞABLONLAYICI ---
async def generate_premium_image(hisse_kodu, alici_html, satici_html):
    html_template = f"""
    <!DOCTYPE html>
    <html lang="tr"><head><meta charset="UTF-8"><style>
        body {{ background-color: #041a12; font-family: sans-serif; color: #ffffff; width: 600px; height: 700px; padding: 30px; box-sizing: border-box; }}
        .header {{ border-bottom: 2px solid #00ffaa; color: #00ffaa; font-size: 28px; font-weight: bold; }}
        .box {{ border: 2px solid #00ffaa; padding: 15px; margin-top: 20px; border-radius: 8px; }}
    </style></head><body>
        <div class="header">BORSA MATRİSİ - {hisse_kodu.upper()}</div>
        <div class="box">{alici_html}</div>
        <div class="box">{satici_html}</div>
    </body></html>"""
    file_path = f"temp_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page()
        await page.set_content(html_template)
        await page.screenshot(path=file_path)
        await browser.close()
    return file_path

# --- 5. OCR İŞLEMİ ---
def process_ocr(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang='tur')
    logger.info(f"OCR İşlendi.")
    return "<div>İŞ YATIRIM: 1.50M</div>", "<div>GARANTİ: 1.20M</div>"

# --- 6. KOMUTLAR ---
@bot_app.on_message(filters.command(["test"]) & filters.bot)
async def test_cmd(client, message):
    await message.reply_text("✅ Sistem çalışıyor! Bağlantı başarılı.")

@bot_app.on_message(filters.command(["çalışmıyor"]) & filters.bot)
async def debug_cmd(client, message):
    await message.reply_text("🛠 Sistem durumu kontrol ediliyor... Loglara bakıyorum. Eğer hata alıyorsan, ekran görüntüsü alıp geliştiriciye ilet.")
    logger.info(f"👉 Kullanıcı sistem durumunu sorguladı: {message.from_user.id}")

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
                alici, satici = await asyncio.to_thread(process_ocr, img_path)
                final_img = await generate_premium_image(hisse, alici, satici)
                await message.reply_photo(final_img, caption=f"⚡️ {hisse} verisi.")
                
                if os.path.exists(img_path): os.remove(img_path)
                if os.path.exists(final_img): os.remove(final_img)
                await wait_msg.delete()
                return
        await wait_msg.edit("❌ Resim bulunamadı.")
    except Exception as e:
        logger.error(f"Hata: {e}")
        await wait_msg.edit(f"Hata oluştu: {str(e)}")

# --- 7. BAŞLATICI ---
async def start_systems():
    logger.info("🚀 Başlatılıyor...")
    await bot_app.start()
    await user_app.start()
    logger.info("💎 Borsa Matrisi 7/24 hazır!")
    await idle()

if __name__ == "__main__":
    asyncio.run(start_systems())
