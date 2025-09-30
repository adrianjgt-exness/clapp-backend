# app/config/redis_config.py
import atexit
import base64
import ssl
import tempfile

from redis.asyncio.sentinel import Sentinel

from .logger import logger
from .settings import settings

_TEMP = []


def _b64_to_temp(b64: str | None):
    if not b64:
        return None
    data = base64.b64decode(b64)
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(data)
    tmp.flush()
    _TEMP.append(tmp.name)
    return tmp.name


# clean-up temp files on exit
@atexit.register
def _cleanup():
    import os

    for f in _TEMP:
        try:
            os.remove(f)
        except OSError:
            pass


def _init_client():
    if not settings.SENTINEL_HOST:
        logger.critical("Redis Sentinel vars missing")
        raise RuntimeError("Redis configuration is missing.")

    ca = _b64_to_temp(settings.CA_CERT_B64)
    cert = _b64_to_temp(settings.CLIENT_CERT_B64)
    key = _b64_to_temp(settings.CLIENT_KEY_B64)

    ssl_kwargs = dict(
        ssl=True,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        ssl_ca_certs=ca,
        ssl_certfile=cert,
        ssl_keyfile=key,
    )

    sentinel = Sentinel(
        [(settings.SENTINEL_HOST, settings.SENTINEL_PORT)],
        sentinel_kwargs={
            **ssl_kwargs,
            "username": settings.SENTINEL_USER,
            "password": settings.SENTINEL_PASSWORD,
            "socket_timeout": 0.5,
            "socket_connect_timeout": 0.5,
        },
        **{
            **ssl_kwargs,
            "username": settings.REDIS_USER,
            "password": settings.REDIS_PASSWORD,
            "decode_responses": True,
            "socket_timeout": 0.5,
            "socket_connect_timeout": 0.5,
        },
    )

    logger.info("Redis Sentinel client ready")
    return sentinel.master_for("mymaster")


redis_client = _init_client()  # None if mis-configured
