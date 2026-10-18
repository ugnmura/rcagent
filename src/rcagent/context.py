from dataclasses import dataclass, field

from rcagent.catalog import schema
from rcagent.catalog.store import CatalogStore
from rcagent.config import Settings
from rcagent.db import Database
from rcagent.evidence import EvidenceLog
from rcagent.query.indexcover import EstimateCache


@dataclass
class AppContext:
    settings: Settings
    db: Database
    store: CatalogStore
    estimates: EstimateCache = field(default_factory=EstimateCache)
    evidence: EvidenceLog = field(default_factory=lambda: EvidenceLog(None))

    @classmethod
    def from_settings(cls, settings: Settings) -> "AppContext":
        db = Database(settings)
        try:
            schema.bootstrap(db)
        except BaseException:
            db.close()
            raise
        return cls(settings, db, CatalogStore(db), evidence=EvidenceLog(db))
