# Contracts And Compatibility

Focus: public shapes stay backward compatible or version deliberately; risky behavior rolls out behind gates.

## Write
- Public API shapes (serializers, response contracts, event payloads) stay
  backward compatible or version deliberately.
- Feature flags/config gates for behavior that must roll out safely;
  document new knobs at their definition site.

## Review
- Silent response-shape changes, removed fields, renamed enums, and
  flag-less risky behavior swaps are blocking on shared surfaces.

Blocking: on shared surfaces.
