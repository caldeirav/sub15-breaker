# Local registry concurrency correction (metric v2 / evidence v2.2)

Predeclared before final validation, 2026-10-31. Native focused run `36de1727cdae485ab48fc2b73cb258b6` failed its exact 12-row gate: a scorer could not register a judge because concurrent SQLite scorer-version allocation raised `UNIQUE constraint failed: scorer_versions.scorer_id, scorer_versions.scorer_version`. Eleven rows completed; the missing `user_task_0-reference` / `utility` row was not silently omitted from acceptance. Retain the failed run, source snapshots and `SCORER_ERROR` assessment on `tr-25b45caca0f9a9ec8307467b74d6b012`.

The correction serializes native registry **writes within this evaluation process**, not model inference or answer selection. There is no retry, fallback verdict, criterion change, prompt tuning or gate relaxation. A concurrency regression checks at most one version-registration write is active. This supports the declared one-process local pilot; it does not claim cross-process/distributed registry safety or a scalable per-case production registry.

Repeat the affected native 3-case / 12-review validation once against corrected source, then run the 17-case / 68-review local pilot. This is a specific framework integration fix, not repeated unchanged sampling for unanimity. Actual bound native judge versions remain visible, and every verdict remains independently selectable.
