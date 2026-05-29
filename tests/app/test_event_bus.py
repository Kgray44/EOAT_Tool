from __future__ import annotations

import logging

from app.event_bus import EventBus


def test_event_handler_failure_logged_and_other_subscribers_still_run(caplog):
    bus = EventBus()
    seen: list[str] = []

    def bad_handler(_event):
        raise RuntimeError("synthetic handler failure")

    def good_handler(event):
        seen.append(event.event_type)

    bus.subscribe("ExampleEvent", bad_handler)
    bus.subscribe("ExampleEvent", good_handler)

    with caplog.at_level(logging.ERROR, logger="app.event_bus"):
        bus.emit("ExampleEvent")

    assert seen == ["ExampleEvent"]
    assert len(bus.handler_errors()) == 1
    assert "synthetic handler failure" in bus.handler_errors()[0].error
    assert "Event handler failed" in caplog.text
