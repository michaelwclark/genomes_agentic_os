# Auto-Dev Program

Auto-Dev is the single operator-facing SDLC family. Start at `program.md`, use
`components.yml` as the machine-readable map, and route detailed execution to
the named workflow or shared foundation.

The durable implementation engine remains `development_delivery`; Auto-Dev
adds investigation, artifact authorship, implicit routing, provider adapters,
and one coherent operator/documentation surface.

Reusable Object Library changes use the canonical `object-library` skill and
`library_self_hosting` workflow. They map build to Develop, exact-artifact
validation to QA, publication to Release, installation/readback to Deploy, and
post-release documentation to a Document rerun. Installed `lib/` remains a
replaceable projection, never a second authoring checkout.
