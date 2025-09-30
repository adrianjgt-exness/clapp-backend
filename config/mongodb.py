# app/config/mongo_config.py
from pymongo import AsyncMongoClient

from .logger import logger
from .settings import settings


def _init_client():
    uri = (
        f"mongodb://{settings.MONGO_USER_RW}:{settings.MONGO_PASS}"
        f"@{settings.MONGO_HOSTS}/mongodb_clapp_test?authSource=admin"
    )
    client = AsyncMongoClient(uri)
    logger.info("Mongo client ready")
    return client


mongo_client = _init_client()
db = mongo_client["clapp"]
