from collections.abc import Generator
from contextlib import contextmanager
from urllib.parse import unquote

import pymysql
from redis import Redis

from app.core.config import settings


def _parse_mysql_url(database_url: str) -> tuple[str, int, str, str, str]:
    normalized_url = database_url.replace("mysql+pymysql://", "mysql://", 1)
    scheme = "mysql://"
    if not normalized_url.startswith(scheme):
        raise ValueError("DATABASE_URL must start with mysql:// or mysql+pymysql://")

    remainder = normalized_url[len(scheme) :]
    if "@" not in remainder:
        raise ValueError("DATABASE_URL must include credentials and host")

    auth_part, location_part = remainder.rsplit("@", 1)
    if "/" not in location_part:
        raise ValueError("DATABASE_URL must include a database name")

    host_port_part, database_name = location_part.split("/", 1)
    if not host_port_part:
        raise ValueError("DATABASE_URL host is missing")

    host = host_port_part
    port = 3306

    if host_port_part.startswith("["):
        closing_bracket = host_port_part.find("]")
        if closing_bracket == -1:
            raise ValueError("Invalid IPv6 host format in DATABASE_URL")
        host = host_port_part[1:closing_bracket]
        trailing = host_port_part[closing_bracket + 1 :]
        if trailing:
            if not trailing.startswith(":"):
                raise ValueError("Invalid IPv6 host/port format in DATABASE_URL")
            port = int(trailing[1:])
    elif ":" in host_port_part:
        host, port_part = host_port_part.rsplit(":", 1)
        port = int(port_part)

    if ":" in auth_part:
        username, password = auth_part.split(":", 1)
    else:
        username, password = auth_part, ""

    return host, port, unquote(username), unquote(password), database_name


def _parse_redis_url(redis_url: str) -> tuple[str, int, int, str]:
    scheme = "redis://"
    if not redis_url.startswith(scheme):
        raise ValueError("REDIS_URL must start with redis://")

    remainder = redis_url[len(scheme) :]
    auth_and_host, db_part = remainder.rsplit("/", 1) if "/" in remainder else (remainder, "0")

    password = ""
    host_port_part = auth_and_host
    if "@" in auth_and_host:
        auth_part, host_port_part = auth_and_host.rsplit("@", 1)
        password = unquote(auth_part.lstrip(":"))

    host = host_port_part or "redis"
    port = 6379
    if ":" in host_port_part:
        host, port_part = host_port_part.rsplit(":", 1)
        port = int(port_part)

    db = int(db_part) if db_part else 0
    return host or "redis", port, db, password


@contextmanager
def get_mysql_connection() -> Generator:
    host, port, user, password, database = _parse_mysql_url(settings.database_url)
    connection = pymysql.connect(
        host=host or "mysql",
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=3,
        read_timeout=3,
        write_timeout=3,
        charset="utf8mb4",
    )
    try:
        yield connection
    finally:
        connection.close()


def get_redis_client() -> Redis:
    host, port, db, password = _parse_redis_url(settings.redis_url)
    return Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
