# Issue #68: installed-stack launcher validation — 2026-11-05

Scope: functional recovery/startup and shutdown on the retained Apple Silicon Mac,
not a new benchmark, general model-quality result, full card acceptance or the
two-hour reliability qualification (#39).

## Approved policy and installation

- The owner approved evolving the mapped MLX pin from1.13.1 to **1.14.0**. App
  remains0.4.28+2; Qwen MLX4-bit/context8192 remains unchanged. Historical evidence
  is not rewritten or requalified by the version edit.
- **LM Studio/model are check-only.** Only the retained VM/Kind/services and actual
  UI are started by `bash scripts/run_demo.sh`. Preparation requires `--prepare`.
- Enrolled `.infra/demo-stack/installation.json` with explicit normal-user XDG
  roots and the existing rootful machine/provider. No installation, build,
  download, VM/cluster replacement, model reload or store/ledger reset occurred.
- Preserved `.env` contents and changed only its permission to0600. Scoped driver
  credentials were renewed through the existing lifecycle.

## Offline checks

- `uv lock --check`, `uv sync --locked --check`: pass; environment unchanged.
- `uv pip check --python .venv/bin/python`:174 compatible installed packages.
- `uv run --locked --no-sync python -m pytest -q`: **787 passed**; one existing
  MLflow/SQLAlchemy deprecation warning.
- Shell syntax checks for every project shell entry point and `git diff --check`:
  pass.
- Fixture coverage includes explicit XDG roots, missing/busy/incompatible models,
  mapped-engine mismatch, image/artifact/storage/mode/endpoint/VM drift, occupied
  ports, preflight failure without mutation, concurrent launcher/direct UI/service
  locks, partial failure, boot/PID/container ownership, timezone-stable boot
  identity, borrowed tracking-storage verification, detached subprocesses,
  preparation opt-in and durable cleanup failure propagation.
- Browser fixture tests were not rerun: external Playwright tooling was not
  present. No frontend build/service or browser package was installed. Existing
  offline UI/preparation/API tests ran in the full suite; live HTTP checks include
  the actual page and authenticated status.

## Live checks and discovered fixes

1. Started from the retained **stopped VM**, resumed registry/Kind/services and
   served the UI. Authenticated status showed `preparation=not_started`, no active
   card and no prepared readiness. No local generation, classifier priming or
   Gemini call was requested by this startup.
2. This exposed an inherited process-group bug: terminal Ctrl-C also reached
   Podman's newly started krunkit helper. Machine startup now uses a separate
   process session; subsequent shutdown checks preserve the shared VM.
3. A subsequent restart exposed stale controller rollout success while a resumed
   store pod was not yet ready. The lifecycle now distinguishes transient
   `StoreNotReady` observations from ownership/image/configuration failures,
   bounds readiness polling, and checks the actual serving health path. No pod
   deletion, rollout restart or data repair was used.
4. Explicit preparation on mapped MLX1.14.0 passed local service/model probes,
   resident classifier priming, **six native controls and two learned-reviewer
   canaries**, reaching **Demo ready**. The first prepared shutdown exposed the
   same signal-group problem in the store port-forward: final capacity readback
   failed although native/route restoration and dependency preservation completed.
   Store/gateway forwarders and supervised infrastructure commands now run in
   separate process sessions. Cleanup failures are persisted and propagate through
   a second `Controller.close()` rather than being swallowed by ASGI shutdown.

Failed/intermediate evidence remains retained. Retesting follows code fixes, not
automatic inference retries or a search for preferred verdicts. No D01–D05 pair
or paid Gemini review has been run for this change.

## Final retest — passed

- `bash scripts/run_demo.sh --prepare`: **Demo ready**, confirmed through the
  actual page and authenticated `/api/live/status`.
- Eight setup cases recorded; usage journal contains one acting-model probe and
  three local LLM-guard attempts, **zero judge/Gemini attempts**.
- `--status` during the prepared session reports the active UI without attempting
  to revalidate its temporary template or interrupt the model. A second launcher
  exits nonzero at the lifecycle lock, before starting any dependency/session.
- Terminal process-group SIGINT: **exit0**, no ASGI shutdown failure, final
  `capacity-final.json` present, no `cleanup-failure.json`.
- Native hook/routes restored; post-exit launcher status is service-ready.
  Independent quiescence check finds **no Actors or prepared/executing actions**.
- Enrolled owner/deployment/image/target-profile files are byte-identical before
  and after the test. Retained MLflow storage identities still match enrollment.
  VM/model/MLflow/Kind/services remain running; the test UI is stopped.
- Private evidence:
  `.infra/live-demo-ui/sessions/27a2e6820d08448d9e1bd016fd55ecd3/`.
  Private terminal log:
  `.infra/demo-stack/logs/issue68-prepared-d6c5709adbfd4d98bd538a0b2cce8424.log`.

## Owner-reported acceptance

On 2026-11-05, the owner confirmed that the demo works and authorized committing,
opening a PR and merging this change. This is functional demo acceptance; it does
not assert that a physical reboot, full external-review campaign or reliability
qualification was performed.

## Remaining validation

- A **physical Mac reboot** has not been performed. Reboot, start only LM Studio
  and its approved model manually, then invoke the launcher once and check the
  retained identities/history and UI readiness.
- Full explicit card-pair/external-review acceptance, >1h idle behavior and #17/#39
  qualification are separate from this functional startup change.
