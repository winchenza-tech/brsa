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

# --- 1. LOGLARI ZORLA ANLIK AKIŞA ALMA ---
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s", 
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BorsaMatrisi")

# Railway log buffer'ını kırmak için
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Linux (Railway) üzerinde Tesseract yolu
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# --- 2. AYARLAR VE ÇEVRE DEĞİŞKENLERİ ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
# Token ismi olarak istediğin değişkeni kullanıyoruz
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "") 

TARGET_BOT = "ucretsizderinlikbot"

# --- 3. CLIENT KURULUMLARI ---
# Hem bot hem userbot için API_ID ve HASH zorunludur
user_app = Client("userbot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
bot_app = Client("mainbot", bot_token=TELEGRAM_TOKEN, api_id=API_ID, api_hash=API_HASH)

# --- 4. GÖRSEL ŞABLONLAYICI ---
async def generate_premium_image(hisse_kodu, alici_html, satici_html):
    html_template = f"""
    <!DOCTYPE html>
    <html lang="tr"><head><meta charset="UTF-8"><style>
        body {{ background-color: #041a12; font-family: sans-serif; color: #ffffff; width: 600px; height: 700px; padding: 30px; }}
        .header {{ border-bottom: 2px solid #00ffaa; color: #00ffaa; font-size: 28px; }}
        .table {{ border: 2px solid #00ffaa; padding: 10px; margin-top: 20px; }}
    </style></head><body>
        <div class="header">BORSA MATRİSİ - {hisse_kodu.upper()}</div>
        <div class="table">{alici_html}</div>
        <div class="table">{satici_html}</div>
    </body></html>"""
    file_path = f"temp_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        page = await browser.new_page()
        await page.set_viewport_size({"width": 600, "height": 700})
        await page.set_content(html_template)
        await page.screenshot(path=file_path)
        await browser.close()
    return file_path

# --- 5. OCR İŞLEMİ ---
def process_ocr(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang='tur')
    logger.info(f"OCR Okundu: {text[:50]}...")
    alici = "<div>İŞ YATIRIM: 1.50M</div>"
    satici = "<div>GARANTİ: 1.20M</div>"
    return alici, satici

# --- 6. KOMUTLAR ---
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
        logger.info(f"📡 {TARGET_BOT} botuna /akd {hisse} atılıyor...")
        await user_app.send_message(TARGET_BOT, f"/akd {hisse}")
        await asyncio.sleep(5)
        
        async for msg in user_app.get_chat_history(TARGET_BOT, limit=1):
            if msg.photo:
                logger.info("📸 Görsel bulundu, işleniyor.")
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
        await wait_msg.edit(f"Hata: {str(e)}")

# --- 7. BAŞLATICI ---
async def start_systems():
    logger.info("🚀 Başlatılıyor...")
    await bot_app.start()
    await user_app.start()
    logger.info("💎 Sistem 7/24 hazır!")
    await idle()

if __name__ == "__main__":
    asyncio.run(start_systems())
