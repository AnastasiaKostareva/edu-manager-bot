from tortoise import Tortoise


def get_tortoise_config():
    from application.config import get_config
    config = get_config()
    return {
        "connections": {
            "default": {
                "engine": "tortoise.backends.asyncpg",
                "credentials": {
                    "host": config.database.host,
                    "port": config.database.port,
                    "user": config.database.user,
                    "password": config.database.password,
                    "database": config.database.database,
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


TORTOISE_ORM = get_tortoise_config()


async def init_db():
    await Tortoise.init(config=TORTOISE_ORM)


async def close_db():
    await Tortoise.close_connections()