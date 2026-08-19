from __future__ import annotations

import json

import pytest

from transport_contract import (
    DeliveryProcessor,
    DurableEvidenceStore,
    DurableQuarantineStore,
    FailPoint,
    InMemoryKafka,
    InvariantViolation,
    Outcome,
    PermanentDeliveryError,
    RawDelivery,
    SimulatedCrash,
    SyntheticEnvelopeCodec,
    TransportPosition,
    run_until_blocked,
)


NS = "antares:test-cluster"
GROUP = "trove-rubin-test"
TOPIC = "rubin-filtered"
PARTITION = 3


def position(offset: int, *, group: str = GROUP) -> TransportPosition:
    return TransportPosition(NS, group, TOPIC, PARTITION, offset)


def good_payload(alert_id: str = "lsst:123", locus_id: str = "ANT123") -> bytes:
    return SyntheticEnvelopeCodec.encode(
        trigger_alert={
            "alert_id": alert_id,
            "mjd": 61221.1,
            "properties": {"lsst_diaSource_psfFlux": -12304.0},
        },
        locus_context={"locus_id": locus_id, "tags": ["rubin"]},
    )


def raw(offset: int, payload: bytes | None = None) -> RawDelivery:
    return RawDelivery(position(offset), good_payload() if payload is None else payload)


def processor(*, evidence=None, quarantine=None, failpoint=None, decode=None):
    return DeliveryProcessor(
        decode=decode or SyntheticEnvelopeCodec.decode,
        evidence=evidence or DurableEvidenceStore(),
        quarantine=quarantine or DurableQuarantineStore(),
        failpoint=failpoint,
    )


def test_success_durable_before_ack():
    audit = []
    broker = InMemoryKafka(audit)
    broker.append(raw(10))
    evidence = DurableEvidenceStore(audit)
    quarantine = DurableQuarantineStore(audit)
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    result = run_until_blocked(session, processor(evidence=evidence, quarantine=quarantine))
    assert result == [Outcome.EVIDENCE_ACKED]
    assert session.committed_next_offset == 11
    key = position(10).message_key
    assert audit.index(f"evidence:durable:{key}") < audit.index(f"ack:{key}:{GROUP}")


def test_crash_after_evidence_durable_before_ack_replays_safely_after_restart():
    audit = []
    broker = InMemoryKafka(audit)
    broker.append(raw(20))
    evidence = DurableEvidenceStore(audit)
    quarantine = DurableQuarantineStore(audit)
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    first = session.poll()
    assert first is not None
    with pytest.raises(SimulatedCrash):
        processor(evidence=evidence, quarantine=quarantine, failpoint=FailPoint.AFTER_EVIDENCE_DURABLE).process(first, session.acknowledge)
    assert session.committed_next_offset is None
    assert len(evidence.rows) == 1

    restarted = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    result = run_until_blocked(restarted, processor(evidence=evidence, quarantine=quarantine))
    assert result == [Outcome.EVIDENCE_ACKED]
    assert restarted.committed_next_offset == 21
    assert any(item.startswith("evidence:durable-replay:") for item in audit)


def test_transient_failure_does_not_ack_or_poll_past_failed_offset():
    broker = InMemoryKafka()
    broker.append(raw(30))
    broker.append(raw(31))
    evidence = DurableEvidenceStore()
    evidence.transient_once.add(position(30).message_key)
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    outcomes = run_until_blocked(session, processor(evidence=evidence))
    assert outcomes == [Outcome.RETRY_NO_ACK]
    assert session.committed_next_offset is None
    assert session.in_flight is not None
    with pytest.raises(InvariantViolation, match="cannot poll past"):
        session.poll()

    restarted = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    outcomes = run_until_blocked(restarted, processor(evidence=evidence))
    assert outcomes == [Outcome.EVIDENCE_ACKED, Outcome.EVIDENCE_ACKED]
    assert restarted.committed_next_offset == 32


def test_permanent_poison_is_durably_quarantined_before_ack():
    audit = []
    broker = InMemoryKafka(audit)
    broker.append(raw(40, b"not-json"))
    quarantine = DurableQuarantineStore(audit)
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    outcome = run_until_blocked(session, processor(quarantine=quarantine))
    assert outcome == [Outcome.QUARANTINE_ACKED]
    assert len(quarantine.rows) == 1
    assert session.committed_next_offset == 41
    key = position(40).message_key
    assert audit.index(f"quarantine:durable:{key}") < audit.index(f"ack:{key}:{GROUP}")


def test_quarantine_transient_failure_does_not_ack_poison():
    broker = InMemoryKafka()
    broker.append(raw(50, b"not-json"))
    quarantine = DurableQuarantineStore()
    quarantine.transient_once.add(position(50).message_key)
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    outcome = run_until_blocked(session, processor(quarantine=quarantine))
    assert outcome == [Outcome.RETRY_NO_ACK]
    assert session.committed_next_offset is None
    assert quarantine.rows == {}


def test_crash_after_quarantine_durable_before_ack_replays_safely():
    broker = InMemoryKafka()
    broker.append(raw(60, b"not-json"))
    quarantine = DurableQuarantineStore()
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    msg = session.poll()
    assert msg is not None
    with pytest.raises(SimulatedCrash):
        processor(quarantine=quarantine, failpoint=FailPoint.AFTER_QUARANTINE_DURABLE).process(msg, session.acknowledge)
    assert session.committed_next_offset is None
    assert len(quarantine.rows) == 1

    restarted = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    assert run_until_blocked(restarted, processor(quarantine=quarantine)) == [Outcome.QUARANTINE_ACKED]
    assert restarted.committed_next_offset == 61


def test_nondurable_evidence_receipt_makes_ack_impossible():
    broker = InMemoryKafka()
    broker.append(raw(70))
    evidence = DurableEvidenceStore()
    evidence.nondurable.add(position(70).message_key)
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    msg = session.poll()
    assert msg is not None
    with pytest.raises(InvariantViolation, match="proving durable persistence"):
        processor(evidence=evidence).process(msg, session.acknowledge)
    assert session.committed_next_offset is None


def test_nondurable_quarantine_receipt_makes_ack_impossible():
    broker = InMemoryKafka()
    broker.append(raw(80, b"bad"))
    quarantine = DurableQuarantineStore()
    quarantine.nondurable.add(position(80).message_key)
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    msg = session.poll()
    assert msg is not None
    with pytest.raises(InvariantViolation, match="quarantine returned"):
        processor(quarantine=quarantine).process(msg, session.acknowledge)
    assert session.committed_next_offset is None


def test_transport_coordinates_are_not_trusted_from_payload():
    payload = json.loads(good_payload().decode())
    payload["transport"] = {"transport_namespace": "evil", "consumer_group": "evil", "topic": "evil", "partition": 999, "offset": 999}
    delivery = raw(90, json.dumps(payload).encode())
    envelope = SyntheticEnvelopeCodec.decode(delivery)
    assert envelope.position == position(90)


def test_missing_explicit_trigger_is_permanent_and_quarantined():
    payload = SyntheticEnvelopeCodec.encode(trigger_alert={"alert_id": "lsst:1"}, locus_context={"locus_id": "ANT1"})
    body = json.loads(payload.decode())
    del body["trigger_alert"]
    broker = InMemoryKafka()
    broker.append(raw(100, json.dumps(body).encode()))
    quarantine = DurableQuarantineStore()
    session = broker.session(transport_namespace=NS, consumer_group=GROUP, topic=TOPIC, partition=PARTITION)
    assert run_until_blocked(session, processor(quarantine=quarantine)) == [Outcome.QUARANTINE_ACKED]
    assert len(quarantine.rows) == 1


def test_delivery_identity_reuse_with_different_trigger_fails_closed():
    evidence = DurableEvidenceStore()
    first = SyntheticEnvelopeCodec.decode(raw(110, good_payload(alert_id="lsst:a")))
    second = SyntheticEnvelopeCodec.decode(raw(110, good_payload(alert_id="lsst:b")))
    evidence.persist(first)
    with pytest.raises(PermanentDeliveryError, match="reused for different"):
        evidence.persist(second)


def test_consumer_group_is_progress_identity_not_message_identity():
    one = position(120, group="group-a")
    two = position(120, group="group-b")
    assert one.message_key == two.message_key
    assert one.progress_key != two.progress_key


def test_two_consumer_groups_share_evidence_identity_but_commit_independently():
    broker = InMemoryKafka()
    broker.append(raw(130))
    evidence = DurableEvidenceStore()
    quarantine = DurableQuarantineStore()

    group_a = broker.session(transport_namespace=NS, consumer_group="group-a", topic=TOPIC, partition=PARTITION)
    assert run_until_blocked(group_a, processor(evidence=evidence, quarantine=quarantine)) == [Outcome.EVIDENCE_ACKED]
    group_b = broker.session(transport_namespace=NS, consumer_group="group-b", topic=TOPIC, partition=PARTITION)
    assert run_until_blocked(group_b, processor(evidence=evidence, quarantine=quarantine)) == [Outcome.EVIDENCE_ACKED]

    assert len(evidence.rows) == 1
    assert group_a.committed_next_offset == 131
    assert group_b.committed_next_offset == 131


def test_position_validation_is_fail_closed():
    with pytest.raises(ValueError):
        TransportPosition("", GROUP, TOPIC, 0, 0)
    with pytest.raises(ValueError):
        TransportPosition(NS, "", TOPIC, 0, 0)
    with pytest.raises(ValueError):
        TransportPosition(NS, GROUP, TOPIC, -1, 0)
    with pytest.raises(ValueError):
        TransportPosition(NS, GROUP, TOPIC, 0, -1)
