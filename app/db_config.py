# db_config.py

# Django loyihangizdagi db.sqlite3 faylining aniq absolyut yo'li
DATABASE_URL = "sqlite:///Users/asadbek/Desktop/cfm/contest/backend/app/db.sqlite3"

TORTOISE_CONFIG = {
    "connections": {
        "default": DATABASE_URL
    },
    "apps": {
        "models": {
            "models": ["models"],  # models.py faylingiz nomi
            "default_connection": "default",
        }
    }
}
