from __future__ import annotations

from dataclasses import dataclass
from typing import List, NamedTuple, Tuple

from scheduler import model

Datalist = List[Tuple[str, str]]


@dataclass(frozen=True)
class SchedulerStagedEntry:
    entry: model.ScheduleEntry
    server_ref: str


class SupportRequestDatalists(NamedTuple):
    tech: Datalist
    medical: Datalist
    training: Datalist
