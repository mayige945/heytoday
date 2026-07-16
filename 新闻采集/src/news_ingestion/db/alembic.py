"""Alembic 迁移闸门（plan §15）。

- ``db upgrade`` 显式执行；其它命令发现库未初始化或落后 ``head`` 时返回退出码 6，
  不自动迁移；
- 初始迁移用 ``Base.metadata.create_all`` 保证表结构与模型完全一致。
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from ..paths import MIGRATIONS_DIR


def _make_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        # alembic Config 基于 ConfigParser，会对 % 做插值；连接串/密码里的 %
        # （如 URL 编码的 %40/%21）会触发 "invalid interpolation syntax"。
        # 转义为 %%，get_main_option 时会被还原回 %。
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head_revision() -> str | None:
    """读取迁移目录的 head revision（不连库）。"""
    script = ScriptDirectory.from_config(_make_config())
    return script.get_current_head()


def current_revision(engine: Engine) -> str | None:
    """当前库的 revision；未初始化（无 alembic_version 表）返回 None。"""
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        return context.get_current_revision()


def is_at_head(engine: Engine) -> bool:
    current = current_revision(engine)
    head = head_revision()
    return current is not None and current == head


def needs_init_or_upgrade(engine: Engine) -> bool:
    """True 表示库未初始化或落后 head（其它命令应返回退出码 6）。"""
    return not is_at_head(engine)


def _url_for(engine: Engine) -> str:
    # str(engine.url) 会把密码 mask 成 ***，env.py 据此重建 engine 时会用 ***
    # 当密码导致 PG 认证失败（OperationalError）。这里仅在进程内向 alembic
    # 配置传递连接串，必须保留真实密码（不写日志、不持久化、不出进程）。
    return engine.url.render_as_string(hide_password=False)


def run_upgrade(engine: Engine) -> None:
    """显式执行 ``alembic upgrade head``。"""
    command.upgrade(_make_config(_url_for(engine)), "head")


def stamp_head(engine: Engine) -> None:
    """强制标记到 head（仅用于灾后修复 / 测试，不走业务路径）。"""
    command.stamp(_make_config(_url_for(engine)), "head")
