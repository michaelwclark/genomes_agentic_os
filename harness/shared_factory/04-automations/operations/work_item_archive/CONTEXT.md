# Work Item Archive Context

This nightly health automation moves terminal, date-prefixed work-item packets
from a project's canonical `work-items/` root into `work-items/99-archived/`
after the configured retention interval. It preserves packet contents and
migrates canonical work-state paths when state exists.
