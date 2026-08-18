from __future__ import annotations

from dataclasses import dataclass

from .models import BrokerTarget


@dataclass(frozen=True)
class TroveIngestResult:
    target_id: int
    target_created: bool
    observations_created: int
    observations_duplicate: int

    @property
    def should_revet(self) -> bool:
        return self.target_created or self.observations_created > 0


def ingest_into_trove(target: BrokerTarget) -> TroveIngestResult:
    """Persist a normalized Rubin/ANTARES locus through TROVE's real Django models.

    This intentionally stops at persistence. It does not invoke TROVE's scientific
    vetting functions. The caller can use ``should_revet`` to decide whether the
    existing TROVE vetting path should run. Duplicate broker delivery therefore
    does not imply duplicate expensive vetting.
    """

    from tom_dataproducts.models import ReducedDatum
    from trove_targets.models import Target

    trove_target, target_created = Target.objects.get_or_create(
        name=target.trove_target_name,
        defaults={
            "type": "SIDEREAL",
            "ra": target.ra_deg,
            "dec": target.dec_deg,
            "permissions": "PUBLIC",
        },
    )

    created_count = 0
    duplicate_count = 0

    for obs in target.observations:
        value = {"filter": obs.band}
        if obs.magnitude is not None:
            value["magnitude"] = obs.magnitude
            if obs.magnitude_error is not None:
                value["error"] = obs.magnitude_error
        elif obs.limiting_magnitude is not None:
            value["limit"] = obs.limiting_magnitude
        else:
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
        else:
            duplicate_count += 1
            # Fill provenance only when an older row lacks it. Do not rewrite
            # existing provenance during broker redelivery.
            changed = False
            if not reduced_datum.source_name:
                reduced_datum.source_name = "Rubin/ANTARES"
                changed = True
            if obs.alert_id and not reduced_datum.source_location:
                reduced_datum.source_location = obs.alert_id
                changed = True
            if changed:
                reduced_datum.save()

    return TroveIngestResult(
        target_id=trove_target.id,
        target_created=target_created,
        observations_created=created_count,
        observations_duplicate=duplicate_count,
    )
