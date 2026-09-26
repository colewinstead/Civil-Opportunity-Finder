"""Run enabled collection or a named source without starting the web server."""
import argparse
import json

from fastapi.encoders import jsonable_encoder

from app.config import Settings
from app.database import Base, create_database
from app.logging_config import configure_logging
from app.models import CollectionRun
from app.scrapers.registry import sync_sources
from app.services.collection import CollectionService


def run(source: str | None = None, allow_demo: bool = False) -> int:
    configure_logging()
    settings = Settings()
    engine, sessions = create_database(settings.database_url)
    try:
        Base.metadata.create_all(engine)
        with sessions.begin() as session:
            sync_sources(session)
        service = CollectionService(sessions, settings)
        service.recover_interrupted()
        run_id = service.collect(source, allow_demo)
        with sessions() as session:
            result = session.get(CollectionRun, run_id)
            print(json.dumps(jsonable_encoder(result), indent=2))
            return 0 if result.outcome == "SUCCEEDED" else 1
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Registered source slug; omit to run active non-demo sources")
    args = parser.parse_args()
    raise SystemExit(run(args.source))


if __name__ == "__main__":
    main()
