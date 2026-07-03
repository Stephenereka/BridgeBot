import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    APPLICATION_ID = int(os.getenv('APPLICATION_ID', '1522711651692974130'))
    DB_PATH = os.getenv('DB_PATH', 'bridgebot.db')
