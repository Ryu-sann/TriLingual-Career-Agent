from alembic import context

from career_agent.database.connection import database_url, engine_for
from career_agent.database.models import Base

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = config.attributes.get("connection")
    if connection is not None:
        run(connection)
    else:
        engine = engine_for(database_url())
        with engine.connect() as connection:
            run(connection)
        engine.dispose()
