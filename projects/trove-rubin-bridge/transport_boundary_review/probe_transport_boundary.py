from __future__ import annotations

import hashlib
import inspect
import json
from importlib import metadata
from pathlib import Path


EXPECTED_ANTARES = "1.14.0"
EXPECTED_TOM_ALERTSTREAMS = "1.2.1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    from antares_client.stream import StreamingClient
    from tom_alertstreams.alertstreams.antares import AntaresAlertStream
    from tom_alertstreams.management.commands import readstreams

    versions = {
        "antares-client": metadata.version("antares-client"),
        "tom-alertstreams": metadata.version("tom-alertstreams"),
    }
    assert versions["antares-client"] == EXPECTED_ANTARES, versions
    assert versions["tom-alertstreams"] == EXPECTED_TOM_ALERTSTREAMS, versions

    init_src = inspect.getsource(StreamingClient.__init__)
    iter_src = inspect.getsource(StreamingClient.iter)
    poll_src = inspect.getsource(StreamingClient.poll)
    timed_poll_src = inspect.getsource(StreamingClient._timed_poll)
    commit_src = inspect.getsource(StreamingClient.commit)
    tom_listen_src = inspect.getsource(AntaresAlertStream.listen)
    readstreams_src = inspect.getsource(readstreams.Command.handle)

    # Runtime/source-surface assertions. These are intentionally fail-closed: if
    # any dependency surface changes, this probe must be re-reviewed rather than
    # silently carrying old assumptions forward.
    assert "enable.auto.commit" in init_src
    assert "enable.auto.offset.store" not in init_src
    assert "message.topic()" in timed_poll_src
    assert "message.partition()" not in timed_poll_src
    assert "message.offset()" not in timed_poll_src
    assert len(inspect.signature(StreamingClient.commit).parameters) == 1
    assert "self.alert_handler[base_topic](locus)" in tom_listen_src
    assert ".commit(" not in tom_listen_src
    assert "Thread(target=alert_stream.listen" in readstreams_src

    class Locus:
        locus_id = "ANT-transport-probe"

    class FakeStream:
        _TOPIC_PREFIX = "antares."

        def __init__(self, messages):
            self.messages = list(messages)
            self.commit_calls = 0

        def iter(self):
            yield from self.messages

        def commit(self):
            self.commit_calls += 1

    # Prove that the current TOM wrapper gives handlers only a Locus and does not
    # acknowledge/commit after a successful handler return.
    fake = FakeStream([("antares.rubin_probe", Locus())])
    wrapper = object.__new__(AntaresAlertStream)
    wrapper.stream = fake
    seen = []
    wrapper.alert_handler = {"rubin_probe": lambda locus: seen.append(locus.locus_id)}
    wrapper.listen()
    assert seen == ["ANT-transport-probe"]
    assert fake.commit_calls == 0

    # Prove that a handler exception escapes listen() and aborts the stream loop;
    # the second message is never handled.
    fake_failure = FakeStream(
        [
            ("antares.rubin_probe", Locus()),
            ("antares.rubin_probe", Locus()),
        ]
    )
    wrapper_failure = object.__new__(AntaresAlertStream)
    wrapper_failure.stream = fake_failure
    attempts = []

    def poison_handler(locus):
        attempts.append(locus.locus_id)
        raise RuntimeError("synthetic poison message")

    wrapper_failure.alert_handler = {"rubin_probe": poison_handler}
    exception_escaped = False
    try:
        wrapper_failure.listen()
    except RuntimeError as exc:
        assert str(exc) == "synthetic poison message"
        exception_escaped = True
    assert exception_escaped
    assert attempts == ["ANT-transport-probe"]

    # A handler can infer its configured route, but the actual Kafka message
    # coordinates are not delivered by the current high-level ANTARES/TOM path.
    result = {
        "status": "BLOCKED_CURRENT_TRANSPORT_SURFACE",
        "versions": versions,
        "source_sha256": {
            "antares_streaming_client_init": sha256_text(init_src),
            "antares_streaming_client_iter": sha256_text(iter_src),
            "antares_streaming_client_poll": sha256_text(poll_src),
            "antares_streaming_client_timed_poll": sha256_text(timed_poll_src),
            "antares_streaming_client_commit": sha256_text(commit_src),
            "tom_antares_listen": sha256_text(tom_listen_src),
            "tom_readstreams_handle": sha256_text(readstreams_src),
        },
        "observed": {
            "antares_high_level_return_shape_is_topic_locus": True,
            "kafka_partition_exposed_to_application": False,
            "kafka_offset_exposed_to_application": False,
            "trigger_alert_explicitly_exposed_by_stream_return": False,
            "auto_commit_configurable": True,
            "auto_offset_store_explicitly_configurable_by_client": False,
            "client_commit_method_exists": True,
            "tom_handler_receives_only_locus": True,
            "tom_wrapper_commits_after_success": False,
            "tom_handler_exception_escapes_listen": True,
            "tom_readstreams_has_listener_supervision": False,
        },
        "activation_blockers": [
            "No explicit triggering Alert is delivered by the current TOM handler surface.",
            "Kafka partition/offset are hidden by the ANTARES high-level return path and TOM handler surface.",
            "Default automatic commits can advance independently of TROVE durable-ingest completion.",
            "Disabling automatic commit alone gives the current TOM wrapper no durable acknowledgement/progress path.",
            "A handler exception terminates the listener thread; readstreams provides no restart supervisor.",
            "A poison-message policy cannot safely 'log and continue': later commits on the same partition can skip an uncommitted failed offset unless failure is durably quarantined or the partition is stopped.",
        ],
        "minimum_next_contract": {
            "trigger": "explicit current ANTARES Alert, not inferred from locus history",
            "transport_identity": "stable namespace + topic + partition + offset (+ broker delivery id if available)",
            "ack": "only after durable evidence success, or after durable quarantine for a permanent poison message",
            "transient_failure": "no acknowledgement; stop/retry without committing past the failed offset",
            "permanent_failure": "durably quarantine raw/lossless trigger plus coordinates, then intentionally acknowledge to unblock the partition",
            "listener": "supervised/restarted; exception must be observable",
            "consumer_group": "stable, explicit group identity across restarts/deployments",
        },
    }

    output = Path(__file__).with_name("transport-boundary-status.json")
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
