from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .models import BrokerTarget, Observation

# Proposed tiny TROVE hook contract. custom_code.hooks.target_post_save checks
# this instance-local marker and returns before science work when True.
DEFER_TARGET_POST_SAVE_ATTR = "_trove_defer_target_post_save"


class VetCallable(Protocol):
    def __call__(self, target, *, created: bool = True): ...


@dataclass(frozen=True)
class SequencedIngestResult:
    target_id: int
    target_created: bool
    observations_created: int
    observations_duplicate: int
    vetting_invocations: int

    @property
    def new_evidence(self) -> bool:
        return self.observations_created > 0


def _photometry_value(obs: Observation) -> dict | None:
    value: dict = {"filter": obs.band}
    if obs.magnitude is not None:
        value["magnitude"] = obs.magnitude
        if obs.magnitude_error is not None:
            value["error"] = obs.magnitude_error
        return value
    if obs.limiting_magnitude is not None:
        value["limit"] = obs.limiting_magnitude
        return value
    return None


def _persist_observations(trove_target, broker_target: BrokerTarget) -> tuple[int, int]:
    from tom_dataproducts.models import ReducedDatum

    created_count = 0
    duplicate_count = 0

    for obs in broker_target.observations:
        value = _photometry_value(obs)
        if value is None:
            continue

        # Broker alert identity is checked first because Kafka/broker redelivery is
        # the failure mode this boundary must make harmless.
        if obs.alert_id and ReducedDatum.objects.filter(
            target=trove_target,
            data_type="photometry",
            source_name="Rubin/ANTARES",
            source_location=obs.alert_id,
        ).exists():
            duplicate_count += 1
            continue

        reduced_datum, created = ReducedDatum.objects.get_or_create(
            target=trove_target,
            data_type="photometry",
            timestamp=obs.observed_at,
            value=value,
            defaults={
                "source_name": "Rubin/ANTARES",
                "source_location": obs.alert_id or "",
            },
        )
        if created:
            created_count += 1
            continue

        duplicate_count += 1
        # Respect an existing datum's provenance. Only fill missing provenance;
        # never rewrite a row attributed to another source.
        changed = False
        if not reduced_datum.source_name:
            reduced_datum.source_name = "Rubin/ANTARES"
            changed = True
        if obs.alert_id and not reduced_datum.source_location:
            reduced_datum.source_location = obs.alert_id
            changed = True
        if changed:
            reduced_datum.save()

    return created_count, duplicate_count


def _get_or_create_target_without_science(broker_target: BrokerTarget):
    """Create a real TROVE Target while deferring its automatic science hook.

    TROVE's BaseTarget.save() always invokes the configured target_post_save hook.
    The proposed TROVE hook guard recognizes the instance-local defer marker set
    here. This preserves Target.save() itself (healpix/galactic/mwebv fields still
    populate) while preventing science from running before Rubin photometry exists.
    """

    from django.db import IntegrityError, transaction
    from trove_targets.models import Target

    existing = Target.objects.filter(name=broker_target.trove_target_name).first()
    if existing is not None:
        return existing, False

    try:
        # Inner savepoint lets a concurrent unique-name winner be recovered without
        # poisoning the outer atomic transaction.
        with transaction.atomic():
            trove_target = Target(
                name=broker_target.trove_target_name,
                type="SIDEREAL",
                ra=broker_target.ra_deg,
                dec=broker_target.dec_deg,
                permissions="PUBLIC",
            )
            setattr(trove_target, DEFER_TARGET_POST_SAVE_ATTR, True)
            try:
                trove_target.save()
            finally:
                # The marker is deliberately ephemeral and instance-local.
                if hasattr(trove_target, DEFER_TARGET_POST_SAVE_ATTR):
                    delattr(trove_target, DEFER_TARGET_POST_SAVE_ATTR)
        return trove_target, True
    except IntegrityError:
        # Another worker may have created the same unique target between our read
        # and write. Treat that as existing identity, then dedupe observations.
        return Target.objects.get(name=broker_target.trove_target_name), False


def ingest_then_vet(
    broker_target: BrokerTarget,
    *,
    vet_callable: VetCallable | None = None,
) -> SequencedIngestResult:
    """Persist Rubin evidence first, then invoke TROVE vetting exactly once if new.

    Sequencing contract for a successful handler call:

    1. establish Target identity with automatic target_post_save science deferred;
    2. persist only unseen Rubin/ANTARES photometry;
    3. if one or more new photometry rows were inserted, invoke TROVE's existing
       target_post_save science path exactly once with ``created=True``;
    4. if the broker delivery is entirely duplicate, invoke no vetting.

    The ``created=True`` call is intentional: TROVE's current science work lives
    under the hook's ``if created`` branch, and existing ingestion code uses a
    forced re-vetting pattern for updated targets.

    This proves delivery/redelivery idempotency. It does not claim distributed
    exactly-once semantics across process crashes or non-transactional external
    side effects inside downstream vetting.
    """

    from django.db import transaction

    if vet_callable is None:
        from custom_code.hooks import target_post_save

        vet_callable = target_post_save

    with transaction.atomic():
        trove_target, target_created = _get_or_create_target_without_science(broker_target)
        created_count, duplicate_count = _persist_observations(trove_target, broker_target)

        vetting_invocations = 0
        if created_count > 0:
            # Important: the photometry rows already exist in this transaction when
            # downstream TROVE science is invoked.
            vet_callable(trove_target, created=True)
            vetting_invocations = 1

    return SequencedIngestResult(
        target_id=trove_target.id,
        target_created=target_created,
        observations_created=created_count,
        observations_duplicate=duplicate_count,
        vetting_invocations=vetting_invocations,
    )
