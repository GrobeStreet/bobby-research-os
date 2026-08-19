from __future__ import annotations

from types import SimpleNamespace

import pytest

from prototype import (
    AntaresDelivery,
    DeliveryStreamingClientMixin,
    DurabilityError,
    TriggerContractError,
    process_one_delivery,
    resolve_explicit_trigger,
)


class FakeMessage:
    def __init__(self, *, topic="antares.rubin", partition=4, offset=19, value=b"x"):
        self._topic = topic
        self._partition = partition
        self._offset = offset
        self._value = value

    def topic(self):
        return self._topic

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset

    def value(self):
        return self._value

    def error(self):
        return None


class FakeConsumer:
    def __init__(self, message):
        self.message = message

    def poll(self, timeout=None):
        return self.message


class FakeClient(DeliveryStreamingClientMixin):
    def __init__(self):
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1


class GuardedLocus:
    def __init__(self, trigger_id, embedded):
        self.properties = {"trove_rubin_trigger_alert_id": trigger_id}
        self._alerts = embedded

    @property
    def alerts(self):
        raise AssertionError("lazy locus.alerts must never be accessed")


def alert(alert_id):
    return SimpleNamespace(alert_id=alert_id)


def delivery(locus):
    return AntaresDelivery("antares.rubin", 4, 19, locus)


def test_poll_delivery_preserves_raw_message_coordinates(monkeypatch):
    locus = SimpleNamespace(locus_id="ANT1")
    monkeypatch.setattr("prototype._parse_message", lambda message: locus)
    client = DeliveryStreamingClientMixin()
    client._consumer = FakeConsumer(FakeMessage())
    got = client.poll_delivery(timeout=0.1)
    assert got.topic == "antares.rubin"
    assert got.partition == 4
    assert got.offset == 19
    assert got.locus is locus


def test_explicit_trigger_resolves_embedded_alert_without_lazy_load():
    wanted = alert("lsst:2")
    locus = GuardedLocus("lsst:2", [alert("lsst:1"), wanted, alert("ztf:3")])
    assert resolve_explicit_trigger(locus) is wanted


def test_missing_trigger_fails_closed():
    locus = GuardedLocus("", [alert("lsst:1")])
    with pytest.raises(TriggerContractError, match="missing"):
        resolve_explicit_trigger(locus)


def test_explicit_trigger_without_embedded_alert_fails_closed_no_http():
    locus = GuardedLocus("lsst:1", None)
    with pytest.raises(TriggerContractError, match="not embedded"):
        resolve_explicit_trigger(locus)


def test_ambiguous_or_absent_embedded_trigger_fails_closed():
    with pytest.raises(TriggerContractError, match="found 0"):
        resolve_explicit_trigger(GuardedLocus("lsst:2", [alert("lsst:1")]))
    with pytest.raises(TriggerContractError, match="found 2"):
        resolve_explicit_trigger(GuardedLocus("lsst:2", [alert("lsst:2"), alert("lsst:2")]))


def test_success_persists_before_commit_and_preserves_coordinates():
    events = []
    client = FakeClient()
    locus = GuardedLocus("lsst:2", [alert("lsst:2")])

    def persist(trigger, context, metadata):
        events.append(("persist", trigger.alert_id, metadata.copy()))
        return True

    original_commit = client.commit
    def commit():
        events.append(("commit",))
        original_commit()
    client.commit = commit

    result = process_one_delivery(
        client=client,
        delivery=delivery(locus),
        persist_evidence=persist,
        persist_quarantine=lambda *_: pytest.fail("no quarantine expected"),
        transport_namespace="antares:prod",
    )
    assert result == "evidence_committed"
    assert client.commit_calls == 1
    assert events[0] == (
        "persist",
        "lsst:2",
        {
            "transport_namespace": "antares:prod",
            "topic": "antares.rubin",
            "partition": 4,
            "offset": 19,
        },
    )
    assert events[1] == ("commit",)


def test_transient_persistence_exception_never_commits():
    client = FakeClient()
    locus = GuardedLocus("lsst:2", [alert("lsst:2")])
    with pytest.raises(RuntimeError, match="db unavailable"):
        process_one_delivery(
            client=client,
            delivery=delivery(locus),
            persist_evidence=lambda *_: (_ for _ in ()).throw(RuntimeError("db unavailable")),
            persist_quarantine=lambda *_: True,
            transport_namespace="antares:prod",
        )
    assert client.commit_calls == 0


def test_nondurable_evidence_never_commits():
    client = FakeClient()
    locus = GuardedLocus("lsst:2", [alert("lsst:2")])
    with pytest.raises(DurabilityError):
        process_one_delivery(
            client=client,
            delivery=delivery(locus),
            persist_evidence=lambda *_: False,
            persist_quarantine=lambda *_: True,
            transport_namespace="antares:prod",
        )
    assert client.commit_calls == 0


def test_permanent_trigger_failure_commits_only_after_durable_quarantine():
    events = []
    client = FakeClient()
    locus = GuardedLocus("lsst:2", None)

    def quarantine(delivery, exc):
        events.append(("quarantine", delivery.offset, type(exc).__name__))
        return True

    original_commit = client.commit
    def commit():
        events.append(("commit",))
        original_commit()
    client.commit = commit

    result = process_one_delivery(
        client=client,
        delivery=delivery(locus),
        persist_evidence=lambda *_: pytest.fail("evidence should not persist"),
        persist_quarantine=quarantine,
        transport_namespace="antares:prod",
    )
    assert result == "quarantine_committed"
    assert events == [("quarantine", 19, "TriggerContractError"), ("commit",)]


def test_nondurable_quarantine_never_commits():
    client = FakeClient()
    locus = GuardedLocus("lsst:2", None)
    with pytest.raises(DurabilityError):
        process_one_delivery(
            client=client,
            delivery=delivery(locus),
            persist_evidence=lambda *_: True,
            persist_quarantine=lambda *_: False,
            transport_namespace="antares:prod",
        )
    assert client.commit_calls == 0
