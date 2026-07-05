# Examples

Runnable example plugins. Each directory is a complete plugin source tree —
`manifest.json` + `wrapper.py` — that the CLI can validate, build, sign, and
conformance-test as-is:

```bash
pip install atlas-sdk

atlas validate examples/hello_sensor
atlas test     examples/hello_sensor

atlas keygen -o my_publisher
atlas build examples/hello_sensor --sign my_publisher.key -o hello_sensor.atlas
atlas verify hello_sensor.atlas
```

| Example | Runtime | Shows |
|---|---|---|
| [`hello_sensor/`](hello_sensor) | `python` | The minimal contract: one manifest, one `wrapper.py` with an async `invoke`, echoing input back |

`hello_sensor` is exactly what `atlas init hello_sensor --runtime python`
scaffolds (plus a real description) — CI validates and conformance-tests it on
every push, so the scaffold can never drift from the contract.
