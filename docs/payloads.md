# Item payloads and external arrays

`ItemRecord.payload` is a JSON boundary. It accepts only JSON-compatible values and
does not store NumPy arrays, tensors, Fedot data containers, or arbitrary Python
objects directly. Dataset and task plugins are responsible for converting their
framework-specific values at this boundary.

## Inline payloads

Small arrays can be represented directly with JSON values:

```python
ItemRecord(
    item_id="series-1",
    dataset_id="example",
    payload={
        "values": [1.0, 2.0, 3.0],
        "shape": [3],
        "dtype": "float64",
    },
)
```

The record freezes nested objects and arrays in memory and converts them back to
ordinary JSON objects and arrays during serialization.

## External payloads

Large arrays and framework-specific containers should be stored outside the record.
The payload contains a JSON descriptor with the artifact URI and the information
needed by a consumer to load it:

```python
ItemRecord(
    item_id="series-1",
    dataset_id="example",
    payload={
        "artifact_uri": "file:///benchmark/items/series-1.npz",
        "media_type": "application/x-npz",
        "shape": [10000, 32],
        "dtype": "float32",
    },
)
```

At the current contract stage, ROAST does not dereference this URI or prescribe an
array format. The consumer-owned task adapter interprets the descriptor and converts
the loaded value into the representation required by its model library. BMF-106
will define the standard artifact layout and persistence behavior for these arrays.

## Payload references and metadata

`ItemRecord.metadata` contains descriptive attributes such as source labels, folds,
or tags. It must not be used to hide the payload itself or its artifact URI. Until a
dedicated reference field exists, the reference belongs explicitly in `payload`.

A future version of the record schema may introduce `payload_ref` as a first-class
field. That change should be versioned and designed together with artifact
resolution rather than added before the persistence contract exists.
