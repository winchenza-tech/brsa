import os
import logging
import sys
from pyrogram import Client, filters, idle

# Logları zorla ekrana bas
logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("TestBot")

# Değişkenleri al
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# TOKEN'IN YÜKLENİP YÜKLENMEDİĞİNİ KONTROL ET (DEBUG)
if not TOKEN:
    logger.error("❌ HATA: TELEGRAM_TOKEN bulunamadı! Variables panelini kontrol et.")
else:
    logger.info(f"✅ Token yüklendi (Başlangıç: {TOKEN[:5]}...)")

# Bot başlat
bot = Client("test_bot", bot_token=TOKEN, api_id=int(API_ID or 0), api_hash=API_HASH)

@bot.on_message(filters.command(["test"]))
async def test(client, message):
    logger.info("👉 /test komutu alındı!")
    await message.reply_text("✅ Bot çalışıyor! Bağlantı başarılı.")

async def start():
    await bot.start()
    logger.info("💎 Bot aktif ve komut bekliyor...")
    await idle()

if __name__ == "__main__":
    bot.run(start())
