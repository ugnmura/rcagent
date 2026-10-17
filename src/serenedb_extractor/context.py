from dataclasses import dataclass, field

from serenedb_extractor.catalog import schema
from serenedb_extractor.catalog.store import CatalogStore
from serenedb_extractor.config import Settings
from serenedb_extractor.db import Database
from serenedb_extractor.query.indexcover import EstimateCache


@dataclass
class AppContext:
    settings: Settings
    db: Database
    store: CatalogStore
    estimates: EstimateCache = field(default_factory=EstimateCache)

    @classmethod
    def from_settings(cls, settings: Settings) -> "AppContext":
        db = Database(settings)
        try:
            schema.bootstrap(db)
        except BaseException:
            db.close()
            raise
        return cls(settings, db, CatalogStore(db))
