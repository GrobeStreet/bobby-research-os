from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping


PROTOCOL = "trove-rubin-delivery-envelope:test-v1"


class ContractError(RuntimeError):
    pass


class PermanentDeliveryError(ContractError):
    """Delivery cannot become valid without changing its content/contract."""


class TransientDeliveryError(ContractError):
    """Delivery may succeed unchanged after retry."""


class InvariantViolation(ContractError):
    """The implementation attempted an unsafe transport state transition."""


class SimulatedCrash(ContractError):
    """Crash injected after durability but before acknowledgement."""


class Outcome(str, Enum):
    EVIDENCE_ACKED = "evidence_acked"
    QUARANTINE_ACKED = "quarantine_acked"
    RETRY_NO_ACK = "retry_no_ack"


class FailPoint(str, Enum):
    AFTER_EVIDENCE_DURABLE = "after_evidence_durable"
    AFTER_QUARANTINE_DURABLE = "after_quarantine_durable"


@dataclass(frozen=True)
class TransportPosition:
    transport_namespace: str
    consumer_group: str
    topic: str
    partition: int
    offset: int

    def __post_init__(self) -> None:
        if not self.transport_namespace:
            raise ValueError("transport_namespace is required")
        if not self.consumer_group:
            raise ValueError("consumer_group is required")
        if not self.topic:
            raise ValueError("topic is required")
        if self.partition < 0:
            raise ValueError("partition must be >= 0")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")

    @property
    def stream_key(self) -> tuple[str, str, str, int]:
        return (
            self.transport_namespace,
            self.consumer_group,
            self.topic,
            self.partition,
        )

    @property
    def delivery_key(self) -> tuple[str, str, str, int, int]:
        return (*self.stream_key, self.offset)


@dataclass(frozen=True)
class RawDelivery:
    position: TransportPosition
    payload: bytes
    broker_delivery_id: str | None = None

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True)
class RubinTriggerEnvelope:
    position: TransportPosition
    trigger_alert: Mapping[str, Any]
    locus_context: Mapping[str, Any]
    broker_delivery_id: str | None = None


@dataclass(frozen=True)
class DurableReceipt:
    durable: bool
    created: bool
    delivery_key: tuple[str, str, str, int, int]


class SyntheticEnvelopeCodec:
    """Test-only wire codec for exercising transport semantics.

    This is deliberately NOT an ANTARES production wire format. It models the
    minimum information a future supported ANTARES/TROVE adapter must expose.
    Transport coordinates come only from the Kafka delivery object, never from
    untrusted payload fields.
    """

    @staticmethod
    def encode(
        *,
        trigger_alert: Mapping[str, Any],
        locus_context: Mapping[str, Any],
    ) -> bytes:
        return json.dumps(
            {
                "protocol": PROTOCOL,
                "trigger_alert": trigger_alert,
                "locus_context": locus_context,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def decode(raw: RawDelivery) -> RubinTriggerEnvelope:
        try:
            body = json.loads(raw.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PermanentDeliveryError("delivery payload is not valid UTF-8 JSON") from exc
        if not isinstance(body, dict):
            raise PermanentDeliveryError("delivery payload must be a mapping")
        if body.get("protocol") != PROTOCOL:
            raise PermanentDeliveryError("unsupported or missing delivery protocol")

        trigger = body.get("trigger_alert")
        if not isinstance(trigger, dict):
            raise PermanentDeliveryError("explicit trigger_alert is required")
        alert_id = trigger.get("alert_id")
        if not isinstance(alert_id, str) or not alert_id:
            raise PermanentDeliveryError("explicit trigger_alert.alert_id is required")

        context = body.get("locus_context")
        if not isinstance(context, dict):
            raise PermanentDeliveryError("explicit locus_context is required")
        locus_id = context.get("locus_id")
        if not isinstance(locus_id, str) or not locus_id:
            raise PermanentDeliveryError("explicit locus_context.locus_id is required")

        return RubinTriggerEnvelope(
            position=raw.position,
            trigger_alert=trigger,
            locus_context=context,
            broker_delivery_id=raw.broker_delivery_id,
        )


class DurableEvidenceStore:
    """Deterministic stand-in for the already-validated v3 evidence boundary."""

    def __init__(self, audit: list[str] | None = None) -> None:
        self.rows: dict[tuple[str, str, str, int, int], RubinTriggerEnvelope] = {}
        self.transient_once: set[tuple[str, str, str, int, int]] = set()
        self.permanent: set[tuple[str, str, str, int, int]] = set()
        self.nondurable: set[tuple[str, str, str, int, int]] = set()
        self._transient_seen: set[tuple[str, str, str, int, int]] = set()
        self.audit = audit if audit is not None else []

    def persist(self, envelope: RubinTriggerEnvelope) -> DurableReceipt:
        key = envelope.position.delivery_key
        if key in self.transient_once and key not in self._transient_seen:
            self._transient_seen.add(key)
            self.audit.append(f"evidence:transient:{key}")
            raise TransientDeliveryError("synthetic transient evidence-store failure")
        if key in self.permanent:
            self.audit.append(f"evidence:permanent:{key}")
            raise PermanentDeliveryError("synthetic permanent evidence-store failure")
        if key in self.nondurable:
            self.audit.append(f"evidence:nondurable:{key}")
            return DurableReceipt(False, False, key)

        existing = self.rows.get(key)
        if existing is not None:
            if existing != envelope:
                raise PermanentDeliveryError(
                    "transport identity was reused for different trigger evidence"
                )
            self.audit.append(f"evidence:durable-replay:{key}")
            return DurableReceipt(True, False, key)

        self.rows[key] = envelope
        self.audit.append(f"evidence:durable:{key}")
        return DurableReceipt(True, True, key)


@dataclass(frozen=True)
class QuarantineRecord:
    position: TransportPosition
    payload: bytes
    payload_sha256: str
    broker_delivery_id: str | None
    error_type: str
    error_text: str


class DurableQuarantineStore:
    """Append/idempotent stand-in for a durable poison-message quarantine."""

    def __init__(self, audit: list[str] | None = None) -> None:
        self.rows: dict[tuple[str, str, str, int, int], QuarantineRecord] = {}
        self.transient_once: set[tuple[str, str, str, int, int]] = set()
        self.nondurable: set[tuple[str, str, str, int, int]] = set()
        self._transient_seen: set[tuple[str, str, str, int, int]] = set()
        self.audit = audit if audit is not None else []

    def persist(self, raw: RawDelivery, error: PermanentDeliveryError) -> DurableReceipt:
        key = raw.position.delivery_key
        if key in self.transient_once and key not in self._transient_seen:
            self._transient_seen.add(key)
            self.audit.append(f"quarantine:transient:{key}")
            raise TransientDeliveryError("synthetic transient quarantine failure")
        if key in self.nondurable:
            self.audit.append(f"quarantine:nondurable:{key}")
            return DurableReceipt(False, False, key)

        candidate = QuarantineRecord(
            position=raw.position,
            payload=raw.payload,
            payload_sha256=raw.payload_sha256,
            broker_delivery_id=raw.broker_delivery_id,
            error_type=error.__class__.__name__,
            error_text=str(error),
        )
        existing = self.rows.get(key)
        if existing is not None:
            # Error text can gain detail across deployments; transport identity and
            # original bytes are what must remain stable for safe replay.
            if (
                existing.position != candidate.position
                or existing.payload != candidate.payload
                or existing.broker_delivery_id != candidate.broker_delivery_id
            ):
                raise InvariantViolation(
                    "quarantine delivery identity was reused for different raw bytes"
                )
            self.audit.append(f"quarantine:durable-replay:{key}")
            return DurableReceipt(True, False, key)

        self.rows[key] = candidate
        self.audit.append(f"quarantine:durable:{key}")
        return DurableReceipt(True, True, key)


class DeliveryProcessor:
    """The invariant under test: durability precedes acknowledgement."""

    def __init__(
        self,
        *,
        decode: Callable[[RawDelivery], RubinTriggerEnvelope],
        evidence: DurableEvidenceStore,
        quarantine: DurableQuarantineStore,
        failpoint: FailPoint | None = None,
    ) -> None:
        self.decode = decode
        self.evidence = evidence
        self.quarantine = quarantine
        self.failpoint = failpoint

    def process(
        self,
        raw: RawDelivery,
        acknowledge: Callable[[TransportPosition], None],
    ) -> Outcome:
        try:
            envelope = self.decode(raw)
            receipt = self.evidence.persist(envelope)
            if not receipt.durable:
                raise InvariantViolation(
                    "evidence store returned before proving durable persistence"
                )
            if self.failpoint == FailPoint.AFTER_EVIDENCE_DURABLE:
                raise SimulatedCrash("crash after evidence durability before acknowledgement")
            acknowledge(raw.position)
            return Outcome.EVIDENCE_ACKED
        except PermanentDeliveryError as permanent:
            try:
                receipt = self.quarantine.persist(raw, permanent)
            except TransientDeliveryError:
                return Outcome.RETRY_NO_ACK
            if not receipt.durable:
                raise InvariantViolation(
                    "quarantine returned before proving durable persistence"
                )
            if self.failpoint == FailPoint.AFTER_QUARANTINE_DURABLE:
                raise SimulatedCrash(
                    "crash after quarantine durability before acknowledgement"
                )
            acknowledge(raw.position)
            return Outcome.QUARANTINE_ACKED
        except TransientDeliveryError:
            return Outcome.RETRY_NO_ACK


class InMemoryKafka:
    """Small deterministic Kafka-like log for crash/restart semantics.

    A session permits at most one unacknowledged delivery at a time. This models
    the deliberately conservative transport loop we want for TROVE: do not poll
    the next record until the current record is durable or durably quarantined.
    """

    def __init__(self, audit: list[str] | None = None) -> None:
        self.records: dict[tuple[str, str, int], dict[int, RawDelivery]] = {}
        self.committed_next: dict[tuple[str, str, str, int], int] = {}
        self.audit = audit if audit is not None else []

    def append(self, raw: RawDelivery) -> None:
        log_key = (
            raw.position.transport_namespace,
            raw.position.topic,
            raw.position.partition,
        )
        bucket = self.records.setdefault(log_key, {})
        if raw.position.offset in bucket:
            raise ValueError("duplicate synthetic Kafka offset")
        bucket[raw.position.offset] = raw

    def session(
        self,
        *,
        transport_namespace: str,
        consumer_group: str,
        topic: str,
        partition: int,
    ) -> "ConsumerSession":
        return ConsumerSession(
            broker=self,
            transport_namespace=transport_namespace,
            consumer_group=consumer_group,
            topic=topic,
            partition=partition,
        )


class ConsumerSession:
    def __init__(
        self,
        *,
        broker: InMemoryKafka,
        transport_namespace: str,
        consumer_group: str,
        topic: str,
        partition: int,
    ) -> None:
        self.broker = broker
        self.stream_key = (transport_namespace, consumer_group, topic, partition)
        log_key = (transport_namespace, topic, partition)
        offsets = sorted(broker.records.get(log_key, {}))
        if self.stream_key in broker.committed_next:
            self.cursor = broker.committed_next[self.stream_key]
        else:
            self.cursor = offsets[0] if offsets else 0
        self.log_key = log_key
        self.in_flight: RawDelivery | None = None

    @property
    def committed_next_offset(self) -> int | None:
        return self.broker.committed_next.get(self.stream_key)

    def poll(self) -> RawDelivery | None:
        if self.in_flight is not None:
            raise InvariantViolation("cannot poll past an unresolved delivery")
        bucket = self.broker.records.get(self.log_key, {})
        available = [offset for offset in bucket if offset >= self.cursor]
        if not available:
            return None
        offset = min(available)
        raw = bucket[offset]
        expected_namespace, expected_group, expected_topic, expected_partition = self.stream_key
        if (
            raw.position.transport_namespace != expected_namespace
            or raw.position.consumer_group != expected_group
            or raw.position.topic != expected_topic
            or raw.position.partition != expected_partition
        ):
            # The synthetic broker stores one raw delivery per group so this is a
            # harness-construction error, not a production behavior.
            raise InvariantViolation("delivery coordinates do not match consumer session")
        self.in_flight = raw
        self.cursor = offset + 1
        self.broker.audit.append(f"poll:{raw.position.delivery_key}")
        return raw

    def acknowledge(self, position: TransportPosition) -> None:
        if self.in_flight is None:
            raise InvariantViolation("cannot acknowledge without an in-flight delivery")
        if position != self.in_flight.position:
            raise InvariantViolation("cannot acknowledge a different delivery")
        next_offset = position.offset + 1
        current = self.broker.committed_next.get(self.stream_key)
        if current is not None and next_offset < current:
            raise InvariantViolation("acknowledgement would move committed offset backwards")
        self.broker.committed_next[self.stream_key] = next_offset
        self.broker.audit.append(f"ack:{position.delivery_key}")
        self.in_flight = None


def run_until_blocked(
    session: ConsumerSession,
    processor: DeliveryProcessor,
    *,
    limit: int = 100,
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for _ in range(limit):
        raw = session.poll()
        if raw is None:
            return outcomes
        outcome = processor.process(raw, session.acknowledge)
        outcomes.append(outcome)
        if outcome == Outcome.RETRY_NO_ACK:
            return outcomes
    raise InvariantViolation("synthetic delivery loop exceeded safety limit")
