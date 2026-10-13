from sqlalchemy import func, select
from sqlalchemy.orm import Session

from career_agent.database.discovery_repository import reconcile_board
from career_agent.database.models import Job
from career_agent.discovery.adapters import PublicBoardAdapter
from tests.helpers import board, client_for, fixture


def test_canonical_url_aliases_merge_without_losing_sources(engine):
    first_board, second_board = board(), board("lever")
    with client_for(fixture("greenhouse")) as client:
        first = PublicBoardAdapter(client).fetch(first_board)[0]
    second = first.model_copy(update={"provider": "lever", "external_id": "other"})
    with Session(engine) as session, session.begin():
        reconcile_board(session, first_board, [first])
        reconcile_board(session, second_board, [second])
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        record = session.scalar(select(Job))
        assert len(record.payload["sources"]) == 2
    # Disappearance from only one source does not close a still-listed second source.
    with Session(engine) as session, session.begin():
        reconcile_board(session, first_board, [])
    with Session(engine) as session:
        record = session.scalar(select(Job))
        assert record.payload["posting"]["is_listed"]
        assert record.payload["posting"]["provider"] == "lever"


def test_same_title_location_on_cross_board_is_reviewed_not_lost(engine):
    with client_for(fixture("greenhouse")) as client:
        first = PublicBoardAdapter(client).fetch(board())[0]
    second = first.model_copy(
        update={
            "provider": "lever",
            "external_id": "other",
            "source_url": "https://jobs.lever.co/example/other",
        }
    )
    with Session(engine) as session, session.begin():
        reconcile_board(session, board(), [first])
        reconcile_board(session, board("lever"), [second])
    with Session(engine) as session:
        records = list(session.scalars(select(Job)))
        assert len(records) == 2
        assert all(len(r.payload["possible_duplicate_ids"]) == 1 for r in records)
