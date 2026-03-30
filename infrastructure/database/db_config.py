from tortoise import Tortoise

TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.asyncpg",
            "credentials": {
                "host": "localhost",
                "port": 5432,
                "user": "your_user",
                "password": "your_password",
                "database": "your_db",
            }
        }
    },
    "apps": {
        "models": {
            "models": ["infrastructure.database.models", "aerich.models"],
            "default_connection": "default",
        }
    }
}

async def init_db():
    await Tortoise.init(config=TORTOISE_ORM)
    #await Tortoise.generate_schemas()

async def close_db():
    await Tortoise.close_connections()