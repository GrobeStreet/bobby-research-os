# Status

## 2026-08-18

**Prototype:** PASS on synthetic interface tests.

Local verification command:

```bash
PYTHONPATH=src pytest -q
```

Result:

```text
........                                                                 [100%]
8 passed
```

Environment note: the current ChatGPT runtime could not reach PyPI to install build dependencies, so verification was run directly against `src/` with the already-installed pytest runner. This is an environment-network limitation, not evidence that editable installation has been validated.

## Gate before upstream PR

Do not open a TROVE PR yet.

Required first:

- maintainer confirmation of broker path;
- one representative real/sanitized Rubin ANTARES fixture or intended topic/schema;
- fixture-driven mapping decision for LSST identity and photometry;
- upstream test against TROVE's actual persistence/hooks.
