# Temporal processing specification

Each processed event retains the original timestamp inside `original_event` and records `temporal.event_timestamp` separately from `temporal.processing_timestamp`. Processing timestamps are UTC and injected through a clock interface in tests.

Events are consumed in ingestion order (SQLite row insertion order); they are not reordered. The event-time watermark before an event is the maximum event time among successfully completed earlier source rows, persisted per source order so retries/replays see the same context. `out_of_order` is true when the current event time is earlier than that watermark. `late_arrival` is true when it is more than `allowed_lateness_seconds` behind that watermark. Equality at the allowed-lateness boundary is not late.

Windows are fixed UTC epoch-aligned tumbling windows of `window_seconds`; output includes inclusive `window_start` and exclusive `window_end`. Late events are still processed and assigned to their original event-time window. v0.3 does not wait for watermarks, retract prior results, or reorder late events. A single SQLite-backed processor serializes watermark updates; multiple independent processors are not a supported ordering guarantee.
