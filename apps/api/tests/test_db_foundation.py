from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.core.url_parsers import parse_mysql_url, parse_redis_url
from app.db.base import Base
from app.db.session import build_sqlalchemy_database_url, check_database_connection
import app.models  # noqa: F401


def test_mysql_url_parser_handles_special_characters() -> None:
    host, port, user, password, database = parse_mysql_url(
        "mysql+pymysql://academy:NiewinPas$699#@953@mysql:3306/healthcare_ai_desk"
    )
    assert host == "mysql"
    assert port == 3306
    assert user == "academy"
    assert password == "NiewinPas$699#@953"
    assert database == "healthcare_ai_desk"


def test_redis_url_parser_handles_special_characters() -> None:
    host, port, db, password = parse_redis_url("redis://:NiewinPas$699#@953@redis:6379/0")
    assert host == "redis"
    assert port == 6379
    assert db == 0
    assert password == "NiewinPas$699#@953"


def test_sqlalchemy_database_url_is_mysql_dialect() -> None:
    url = build_sqlalchemy_database_url()
    assert isinstance(url, URL)
    assert url.drivername == "mysql+pymysql"


def test_metadata_can_create_schema_on_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    table_names = set(inspect(engine).get_table_names())
    assert {
        "system_settings",
        "organizations",
        "users",
        "projects",
        "organization_memberships",
        "patient_records",
        "agent_profiles",
        "agent_project_assignments",
        "agent_versions",
        "agent_executions",
        "agent_execution_tasks",
        "agent_execution_audit_logs",
        "agent_execution_approvals",
    }.issubset(table_names)


def test_check_database_connection_executes_query(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    testing_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    from app.db import session as db_session_module

    monkeypatch.setattr(db_session_module, "engine", engine)
    monkeypatch.setattr(db_session_module, "SessionLocal", testing_session_factory)
    check_database_connection()
