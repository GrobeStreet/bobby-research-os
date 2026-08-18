from __future__ import annotations

from dataclasses import dataclass, field

from .models import BrokerTarget


@dataclass(frozen=True)
class IngestResult:
    target_created: bool
    observations_created: int
    observations_duplicate: int


@dataclass
class _TargetState:
    target: BrokerTarget
    observation_keys: set[tuple] = field(default_factory=set)


class InMemoryIngestLedger:
    def __init__(self) -> None:
        self._targets: dict[str, _TargetState] = {}

    def ingest(self, target: BrokerTarget) -> IngestResult:
        key = target.idempotency_key
        created = key not in self._targets
        if created:
            state = _TargetState(target=target)
            self._targets[key] = state
        else:
            state = self._targets[key]
            state.target = target

        new_count = 0
        duplicate_count = 0
        for obs in target.observations:
            obs_key = obs.dedupe_key
            if obs_key in state.observation_keys:
                duplicate_count += 1
                continue
            state.observation_keys.add(obs_key)
            new_count += 1

        return IngestResult(created, new_count, duplicate_count)

    def observation_count(self, key: str) -> int:
        return len(self._targets[key].observation_keys)
