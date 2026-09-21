## What

<!-- One or two sentences. What changes on the board, in the image, or in the tooling. -->

## Why

<!-- The reason, or the failed run / bug that drove it. -->

## Checks

- [ ] `pytest` passes locally
- [ ] `ruff check . && ruff format --check .` clean
- [ ] Rendering change? Snapshots regenerated with `pytest --update-snapshots` and the diff reviewed
- [ ] Image change? Considered whether `image/README.md` or `CLAUDE.md` needs updating
