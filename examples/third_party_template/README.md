# Third-party plugin template

Copy this directory into your project and rename `template.*` registrations to
names owned by your package. The template implements all four extension points:

- `TemplateDatasetProvider` yields task items;
- `TemplateModelAdapter` declares availability and predicts values;
- `TemplateMetric` computes a direction-aware metric;
- `TemplateTaskAdapter` connects items to the model capability.

`register_plugins()` is the only hook required by the generic CLI. The optional
`register_presets()` hook exposes a reusable suite configuration.

Run the unchanged template from the ROAST repository:

```shell
roast plugins list --plugin examples.third_party_template.plugin
roast resolve-manifest --manifest examples/third_party_template/manifest.json --plugin examples.third_party_template.plugin
roast run --manifest examples/third_party_template/manifest.json --plugin examples.third_party_template.plugin
```

To adapt it:

1. Replace the in-memory values in `TemplateDatasetProvider` with your loader.
2. Replace `predict_value()` with the capability implemented by your model.
3. Update `TemplateTaskAdapter` to call that capability.
4. Replace or extend `TemplateMetric` and declare its ranking direction.
5. Change the registered names and manifest preset to your package namespace.
6. Keep optional third-party imports inside factories or adapter constructors so
   importing the plugin module does not require every optional dependency.

Plugin options must remain JSON-compatible. Availability failures should return an
unavailable `Availability` value rather than failing module import. Artifact paths
and result parsing follow the versioned ROAST schema documented in
`docs/artifacts.md`.
