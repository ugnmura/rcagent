from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    pos: int
    name: str
    kind: str
