from __future__ import annotations

import inspect
from importlib import metadata


def show(label, obj):
    print(f"\n=== {label} ===")
    try:
        print(inspect.signature(obj))
    except (TypeError, ValueError):
        pass
    try:
        print(inspect.getsource(obj))
    except (TypeError, OSError) as exc:
        print(f"SOURCE_UNAVAILABLE: {exc}")


def main():
    import antares_client.stream as stream
    from antares_client.models import Locus
    from tom_alertstreams.alertstreams.antares import AntaresAlertStream

    print("antares-client", metadata.version("antares-client"))
    print("tom-alertstreams", metadata.version("tom-alertstreams"))
    show("stream module _parse_message", stream._parse_message)
    show("StreamingClient.__init__", stream.StreamingClient.__init__)
    show("StreamingClient._timed_poll", stream.StreamingClient._timed_poll)
    show("StreamingClient.poll", stream.StreamingClient.poll)
    show("StreamingClient.commit", stream.StreamingClient.commit)
    show("Locus.__init__", Locus.__init__)
    alerts_attr = Locus.__dict__.get("alerts")
    show("Locus.alerts descriptor", alerts_attr.fget if isinstance(alerts_attr, property) else alerts_attr)
    show("AntaresAlertStream.listen", AntaresAlertStream.listen)


if __name__ == "__main__":
    main()
