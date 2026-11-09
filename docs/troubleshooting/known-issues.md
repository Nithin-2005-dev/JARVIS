# Known issues and limitations

- The event contract is illustrative, not a production payment or audit schema.
- Pool exhaustion is injected at request boundary; occupancy, wait queues, concurrency, and recovery are not modeled.
- A downstream timeout marks the notification queued, but no retry/backoff event is emitted.
- Service calls and database writes are synthetic.
- Metadata fields are not strictly validated beyond requiring an object.
- The default timestamp is fixed for reproducibility; select `--start-time` to change the timeline.
- IDs are deterministic for fixture generation and are not globally unique across independent streams/seeds.
