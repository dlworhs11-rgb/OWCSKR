# data/models

Glyph classifiers that `tools/ocr_run.py` uses to read the GAME DATA table and the team-totals page:

- `table.npz`: table digits (E A D DMG H MIT)
- `totals.npz`: team-totals digits

Each file holds the training features (`X`), labels (`y`), training statistics, and a hash of the training inputs:
the content of `data/manual/mapstats/2026-10-11.json` plus the path, size and mtime of every training frame under
`data/vod`. `tools/glyph_models.py` does the following:

- training frames present, hash matches: loads the cache
- training frames present, hash differs or no cache: retrains, prints per-digit sample counts and skipped cells,
  and rewrites both files. It fails if any digit 0-9 has no sample.
- training frames absent, cache present (the server): loads the cache as it is
- neither: stops with an error. `ocr_run.py` exits 2 and the self-check reports it as fatal.

## Building and copying

On the PC that has `data/vod`:

    python -I tools/glyph_models.py --rebuild

Copy `data/models/table.npz` and `data/models/totals.npz` to the same folder on the server.
The models replace only the training frames. A server without `data/vod` still needs the two GAME DATA reference
frames `data/vod/maps/m_3480.png` and `data/vod/maps/m_9465.png` (`live_capture.classify`), and `data/ref/`,
`data/name_lib/`, `data/header_lib/`, `data/digit_lib/`; the self-check (`tools/selfcheck.py`) reports any that are
missing as fatal.

The cache does not notice a changed `data/manual/mapstats/2026-10-11.json` while the training frames are absent:
after changing that file, rebuild on the PC and copy the `.npz` files again.

## Not in git

The `.npz` files are ignored (`.gitignore`), like `data/vod`. They are features derived from broadcast frames, and
they are rebuilt from local inputs. Only this README is committed.
