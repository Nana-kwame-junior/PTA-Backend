from __future__ import with_statement
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.append(os.getcwd())

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# Import your app's metadata object for 'autogenerate' support
try:
    from app.core.config import settings
    # ensure all models are imported so they register on Base.metadata
    try:
        import app.models  # noqa: F401
    except Exception:
        pass
    from app.core.database import Base
    target_metadata = Base.metadata
except Exception:
    target_metadata = None

# override sqlalchemy.url with the app settings if available
try:
    config.set_main_option('sqlalchemy.url', settings.database_url_sync)
except Exception:
    pass


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
