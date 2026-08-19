from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from antares_client.stream import _parse_message


TRIGGER_PROPERTY = "trove_rubin_trigger_alert_id"


class SeamError(RuntimeError):
    pass


class TriggerContractError(SeamError):
    pass


class DurabilityError(SeamError):
    pass


@dataclass(frozen=True)
class AntaresDelivery:
    """Minimal API shape proposed for antares-client.

    This is a prototype of the smallest public seam we need from the ANTARES
    client: preserve the existing parsed Locus, but stop discarding the Kafka
    coordinates of the message that produced it.
    """

    topic: str
    partition: int
    offset: int
    locus: Any


class DeliveryStreamingClientMixin:
    """Reference implementation of a proposed StreamingClient.poll_delivery().

    Production code should not ship this mixin against private client internals.
    Its purpose is to demonstrate the tiny upstream API addition required in
    antares-client. The implementation is intentionally one-poll/one-delivery.
    """

    def poll_delivery(self, timeout: float | None = None) -> AntaresDelivery | None:
        # A future antares-client implementation would put this logic inside the
        # package next to _timed_poll(), where _consumer and _parse_message are
        # already internal implementation details.
        message = self._consumer.poll(timeout=timeout)
        if message is None:
            return None
        locus = _parse_message(message)
        return AntaresDelivery(
            topic=message.topic(),
            partition=message.partition(),
            offset=message.offset(),
            locus=locus,
        )


def resolve_explicit_trigger(locus: Any, *, property_name: str = TRIGGER_PROPERTY) -> Any:
    """Resolve only an explicit ANTARES-filter trigger marker.

    Critical safety rule: never access ``locus.alerts`` here because that property
    may lazy-load historical alerts over HTTP. We inspect only ``locus._alerts``
    that were actually embedded in this broker delivery. If ANTARES did not embed
    the referenced alert, the delivery is insufficient and must fail closed.
    """

    properties = getattr(locus, "properties", None)
    if not isinstance(properties, dict):
        raise TriggerContractError("streamed locus has no properties mapping")
    trigger_id = properties.get(property_name)
    if not isinstance(trigger_id, str) or not trigger_id:
        raise TriggerContractError("explicit trigger alert id is missing")

    embedded = getattr(locus, "_alerts", None)
    if embedded is None:
        raise TriggerContractError(
            "trigger alert is explicit but not embedded in the streamed locus"
        )
    matches = [alert for alert in embedded if getattr(alert, "alert_id", None) == trigger_id]
    if len(matches) != 1:
        raise TriggerContractError(
            f"expected exactly one embedded trigger alert {trigger_id!r}, found {len(matches)}"
        )
    return matches[0]


def process_one_delivery(
    *,
    client: Any,
    delivery: AntaresDelivery,
    persist_evidence: Callable[[Any, Any, dict[str, Any]], bool],
    persist_quarantine: Callable[[AntaresDelivery, Exception], bool],
    transport_namespace: str,
) -> str:
    """Durability-before-commit reference loop.

    The public ANTARES ``commit()`` remains the acknowledgement mechanism. The
    caller must configure ``enable_auto_commit=False`` and must not poll the next
    message until this function returns. A permanent trigger-contract error may be
    acknowledged only after durable quarantine. Other persistence failures escape
    without commit so the same Kafka position is replayed after restart/retry.
    """

    if not transport_namespace:
        raise ValueError("transport_namespace is required")

    metadata = {
        "transport_namespace": transport_namespace,
        "topic": delivery.topic,
        "partition": delivery.partition,
        "offset": delivery.offset,
    }

    try:
        trigger = resolve_explicit_trigger(delivery.locus)
        durable = persist_evidence(trigger, delivery.locus, metadata)
        if durable is not True:
            raise DurabilityError("evidence persistence did not prove durability")
    except TriggerContractError as exc:
        quarantined = persist_quarantine(delivery, exc)
        if quarantined is not True:
            raise DurabilityError("quarantine persistence did not prove durability")
        client.commit()
        return "quarantine_committed"

    client.commit()
    return "evidence_committed"
