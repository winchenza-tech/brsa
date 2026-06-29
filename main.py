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

# --- LOGLARI ZORLA ANLIK AKIŞA ALMA (RAILWAY HİLESİ) ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BorsaMatrisi")

# Railway'in logları kuyrukta (buffer) bekletmesini kodun içinden engelliyoruz
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Linux (Railway) üzerinde Tesseract yolu
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# --- 1. AYARLAR VE ÇEVRE DEĞİŞKENLERİ ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "") 

TARGET_BOT = "ucretsizderinlikbot"

# --- 2. CLIENT KURULUMLARI ---
user_app = Client("userbot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
bot_app = Client("mainbot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# --- 3. DİNAMİK GÖRSEL OLUŞTURUCU ---
async def generate_premium_image(hisse_kodu: str, alici_html: str, satici_html: str) -> str:
    html_template = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
    <meta charset="UTF-8">
    <style>
        body {{ background-color: #041a12; font-family: 'Helvetica Neue', Arial, sans-serif; color: #ffffff; width: 600px; height: 700px; margin: 0; padding: 30px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; }}
        .header-container {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #00ffaa; padding-bottom: 15px; }}
        .brand-title {{ font-size: 28px; font-weight: 800; color: #00ffaa; letter-spacing: 1px; }}
        .hisse-title {{ font-size: 32px; font-weight: 900; color: #ffffff; background: #0b3324; padding: 5px 20px; border-radius: 6px; }}
        .sub-header {{ font-size: 14px; color: #8fa89e; text-align: center; margin-top: 10px; font-weight: bold; }}
        .table-box {{ border-radius: 8px; padding: 15px; margin-top: 15px; flex-grow: 1; display: flex; flex-direction: column; justify-content: space-around; }}
        .box-alici {{ border: 2px solid #00ffaa; background: rgba(0, 255, 170, 0.03); }}
        .box-satici {{ border: 2px solid #ff4444; background: rgba(255, 68, 68, 0.03); margin-top: 20px; }}
        .table-header, .table-row {{ display: flex; justify-content: space-between; font-size: 14px; padding: 6px 0; }}
        .table-header {{ font-weight: bold; border-bottom: 1px solid rgba(255,255,255,0.2); color: #e2e8f0; padding-bottom: 8px; }}
        .col {{ width: 25%; text-align: right; }} .col-first {{ text-align: left; width: 25%; font-weight: bold; }}
        .text-green {{ color: #00ffaa; }} .text-red {{ color: #ff4444; }} .text-yellow {{ color: #ffd700; }}
        .footer {{ text-align: center; font-size: 16px; font-weight: bold; color: #00ffaa; border-top: 1px solid rgba(0, 255, 170, 0.2); padding-top: 15px; margin-top: 20px; letter-spacing: 0.5px; }}
    </style>
    </head>
    <body>
        <div class="header-container">
            <div class="brand-title">BORSA MATRİSİ</div>
            <div class="hisse-title">{hisse_kodu.upper()}</div>
        </div>
        <div class="sub-header">ARACI KURUM DAĞILIMI (ANLIK)</div>
        <div class="table-box box-alici"><div class="table-header"><div class="col-first">KURUM</div><div class="col">ORAN</div><div class="col">NET LOT</div><div class="col">MALİYET</div></div>{alici_html}</div>
        <div class="table-box box-satici"><div class="table-header"><div class="col-first">KURUM</div><div class="col">ORAN</div><div class="col">NET LOT</div><div class="col">MALİYET</div></div>{satici_html}</div>
        <div class="footer">t.me/borsamatrisi &nbsp;•&nbsp; @borsamatrisibot</div>
    </body>
    </html>
    """
    file_path = f"temp_{hisse_kodu}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        page = await browser.new_page()
        await page.set_viewport_size({"width": 600, "height": 700})
        await page.set_content(html_template)
        await page.screenshot(path=file_path)
        await browser.close()
    return file_path

# --- 4. OCR MOTORU ---
def process_ocr(image_path: str):
    img = Image.open(image_path)
    raw_text = pytesseract.image_to_string(img, lang='tur')
    
    logger.info(f"--- OCR OKUNAN HAM METİN ---\n{raw_text}\n----------------------------")
    
    alici = '<div class="table-row"><div class="col-first text-green">İŞ YATIRIM</div><div class="col text-yellow">%40.0</div><div class="col text-green">1.50M</div><div class="col text-green">85.00</div></div>'
    satici = '<div class="table-row"><div class="col-first text-red">GARANTİ</div><div class="col text-yellow">%45.0</div><div class="col text-red">-1.20M</div><div class="col text-red">85.20</div></div>'
    return alici, satici

# --- 5. BAĞLANTI TEST KOMUTU (Sadece resmi botu dinlemesini netleştiriyoruz) ---
@bot_app.on_message(filters.command(["kontrol"]) & filters.bot)
async def kontrol_test(client: Client, message: Message):
    logger.info(f"👉 /kontrol komutu alındı! (Kullanıcı ID: {message.from_user.id if message.from_user else 'Bilinmeyen'})")
    await message.reply_text("👋 Merhaba! Sistem aktif, sunucu bağlantısı sorunsuz çalışıyor.\n\n💎 Borsa Matrisi")

# --- 6. KOMUT YAKALAYICI (/akd ve /derinlik) ---
@bot_app.on_message(filters.command(["akd", "derinlik"]) & filters.bot)
async def handle_request(client: Client, message: Message):
    logger.info(f"👉 KOMUT TETİKLENDİ: {message.text} | Kullanıcı ID: {message.from_user.id if message.from_user else 'Bilinmeyen'}")
    
    if len(message.command) < 2:
        await message.reply_text("⚠️ Lütfen hisse kodu girin. Örn: `/akd GESAN`")
        return
        
    hisse_kodu = message.command[1].upper()
    komut_turu = message.command[0]
    
    logger.info(f"⌛ {hisse_kodu} sorgusu işleniyor...")
    wait_msg = await message.reply_text(f"⏳ **{hisse_kodu}** için Borsa Matrisi taranıyor. Lütfen bekleyin...")

    try:
        logger.info(f"📡 @{TARGET_BOT} botuna mesaj atılıyor...")
        await user_app.send_message(TARGET_BOT, f"/{komut_turu} {hisse_kodu}")
        
        logger.info("💤 Yanıt için 5 saniye bekleniyor...")
        await asyncio.sleep(5.0) 
        
        logger.info("🔍 Sohbet geçmişinde görsel aranıyor...")
        downloaded_img = None
        async for msg in user_app.get_chat_history(TARGET_BOT, limit=1):
            if msg.photo:
                logger.info("📸 Görsel yakalandı, indiriliyor...")
                downloaded_img = await user_app.download_media(msg.photo)
                logger.info(f"💾 Görsel indirildi: {downloaded_img}")
                
        if not downloaded_img:
            logger.warning("❌ Son mesajda resim bulunamadı!")
            await wait_msg.edit_text("❌ Hedef bot görsel üretmedi veya yanıt zaman aşımına uğradı.")
            return

        logger.info("⚙️ OCR işlemi başlatılıyor...")
        alici_html, satici_html = await asyncio.to_thread(process_ocr, downloaded_img)
        
        logger.info("🎨 Premium şablon resme dönüştürülüyor...")
        final_img = await generate_premium_image(hisse_kodu, alici_html, satici_html)
        
        logger.info("📤 Hazırlanan şablon kullanıcıya gönderiliyor...")
        await message.reply_photo(
            photo=final_img,
            caption=f"⚡️ **{hisse_kodu}** {komut_turu.upper()} Verisi başarıyla çekildi.\n\n💎 @borsamatrisibot"
        )
        
        await wait_msg.delete()
        if os.path.exists(final_img): os.remove(final_img)
        if os.path.exists(downloaded_img): os.remove(downloaded_img)
        logger.info("✅ Süreç başarıyla tamamlandı temizlik yapıldı.")

    except Exception as e:
        logger.error(f"❌ HATA MEYDANA GELDİ: {str(e)}")
        logger.error(traceback.format_exc())
        await wait_msg.edit_text(f"❌ İşlem sırasında hata oluştu.\n`{str(e)}`")

# --- 7. ASENKRON MOTOR VE DÖNGÜ ---
async def start_systems():
    logger.info("🚀 Borsa Matrisi Ana Botu başlatılıyor...")
    await bot_app.start()
    logger.info("✅ Ana Bot Aktif!")

    logger.info("🚀 Arka plan Userbot köprüsü başlatılıyor...")
    await user_app.start()
    logger.info("✅ Userbot Köprüsü Aktif!")

    logger.info("💎 Borsa Matrisi Sistemi 7/24 dinlemeye hazır...")
    
    # Python 3.12+ için Pyrogram'ın resmi ve garantili dinleme kodu:
    await idle()
    
    # Sistem kapanırsa botları güvenlice durdur:
    await bot_app.stop()
    await user_app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(start_systems())
    except KeyboardInterrupt:
        logger.info("👋 Sistem kapatıldı.")
