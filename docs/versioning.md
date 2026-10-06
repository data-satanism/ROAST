# Versioning policy

ROAST versions its Python API, declarative manifest formats, and portable
artifact schemas explicitly. These versions solve different compatibility
problems and do not advance together automatically.

## Python package and API

The package version follows Semantic Versioning (`MAJOR.MINOR.PATCH`):

- `PATCH` fixes defects without intentionally changing documented behavior;
- `MINOR` adds backward-compatible public APIs, plugins, or optional features;
- `MAJOR` may remove, rename, or incompatibly change a documented public API.

The public API is the set of names documented in this repository, including the
short imports exported by `roast.__all__`. Private names and modules beginning
with `_` are not compatibility promises.

Before version `1.0.0`, the API is still being established. An incompatible
pre-1.0 change increments `MINOR`, is called out in release notes, and should
include a migration path. After `1.0.0`, incompatible API changes require a
`MAJOR` release.

## Serialized BMF schema

Portable configuration, record, result, and artifact objects carry an integer
`schema_version`. The current value is `1` and is independent of the Python
package version.

Increment `schema_version` when a reader would need different logic, including:

- removing or renaming a field;
- changing a field type, meaning, or required status;
- changing directory layout or record identity semantics;
- adding fields to strict objects whose readers reject unknown fields.

Fixing documentation or implementation while preserving serialized meaning does
not increment the schema version. A package may support more than one schema
version during migration. Dropping support for a previously documented schema is
a breaking public API change and follows the package rules above.

## Manifest formats

Declarative envelopes use independently versioned format markers such as
`roast_manifest@1` and `roast_showcase@1`. A backward-incompatible envelope
change increments the marker (`@2`). Additive behavior that leaves every valid
version-1 document unchanged may remain at `@1`.

Manifest resolution produces a versioned `BenchmarkSuiteConfig`; changing the
envelope marker does not by itself change the artifact schema, and changing the
artifact schema does not silently reinterpret an existing manifest format.

## Plugin compatibility

Plugin packages should declare the compatible ROAST package range and test their
registered contracts against its lowest and highest supported versions. Plugin
registration names and consumer-owned option schemas are versioned by the plugin
package. When the meaning of an existing registered name changes incompatibly,
publish a new versioned name or a major plugin release.
