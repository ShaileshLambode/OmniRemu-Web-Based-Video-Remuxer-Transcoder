# OmniRemux Implementation Plan — Latest Commit Review

**Reviewed commit:** [234f1a8](https://github.com/ShaileshLambode/OmniRemu-Web-Based-Video-Remuxer-Transcoder/commit/234f1a855649de4f894cfc2271c07d6a0f28aa4b)  
**Review date:** 2026-10-27  
**Purpose:** A staged, testable plan for resolving open issues after the latest engine-fix commit. This document is a plan, not evidence that runtime validation has passed.

## Executive summary

Commit 234f1a8 makes useful changes to frame-rate parsing, audio strategy mapping, cancellation cleanup, local-file scanning scope, filename sanitization, HTTP byte-range responses, trim progress, and the hardcoded sample path. These are implementation improvements, but no successful automated checks or real-media integration run was confirmed during this review.

Keep issues open until their acceptance criteria pass. Prioritize local API security and filesystem confinement before feature polish.

## Current assessment

| Issue | Area | Latest-commit assessment | Next action |
|---|---|---|---|
| #1 | Show/Open in Folder | Not re-verified by this commit; prior helper changes still need Windows end-to-end testing | Test on Windows and record results |
| #2 | Local API origin/authorization | Not fixed; wildcard CORS remains | Harden request trust and state-changing endpoints |
| #3 | Path confinement | Partially improved by scanning only APP_DIR; API path validation and overwrite safety remain | Centralize path validation and output containment |
| #4 | Frontend HTML injection | Dynamic innerHTML templates remain in local-file and stream rendering | Use DOM APIs and textContent for untrusted values |
| #5 | Resource limits | Cancellation cleanup improved; upload/concurrency/job retention limits not established | Add limits, bounded queue, retention, cleanup |
| #6 | Audio strategy correctness | Core strategy logic added; behavior needs unit and FFmpeg/ffprobe verification | Test strategy/preset matrix with real sample media |
| #7 | GIF/control consistency | GIF filter still uses fps=15; UI/control agreement not resolved | Align product behavior and tests |
| #8 | Hardcoded sample path | Removed in code; empty-workspace and first-file behavior need verification | Test clean install and no-video state |
| #9 | Automated tests/CI | No test additions or successful CI checks confirmed for this commit | Add tests and CI workflow |
| #10 | Safe frame-rate parsing | Safe parser added; edge cases still need tests | Keep open until tests pass |
| #11 | License/Windows launchers | start.bat changed; stop.bat still needs process-safety validation; license not verified | Check LICENSE and test scripts |
| #14 | Open Outputs Folder UI errors | Not addressed by this commit | Check HTTP status/body before showing success |
| #15 | File-manager helper tests | Not addressed by this commit | Add mocked platform/path unit tests |
| #16 | Windows Show in Folder verification | Not addressed by this commit | Complete manual Windows checklist |

Duplicate tracking: #12 duplicates #10, and #13 duplicates #11. Use #10 and #11 as the canonical tracking issues.

A follow-up issue tracks output-name collision safety: get_unique_output_path() can return an existing writable path, while FFmpeg is invoked with -y, allowing an existing output to be overwritten. The fix must choose a truly unused name or implement an explicit, safe overwrite policy.

## Implementation principles

1. Work in small, reviewable commits; avoid bundling security fixes with UI polish.
2. Write a regression test before or alongside each fix.
3. Never mark an issue resolved based only on code inspection. Require automated checks and, where needed, manual Windows/real-media verification.
4. Do not broaden file access for convenience. Treat every client-supplied path and filename as untrusted.
5. Preserve existing functionality: uploads, local-file loading, probing, conversion, trim, preview/seeking, cancellation, and file-manager actions.
6. Use temporary directories and mocked subprocess calls for tests that should not access real user files or launch desktop applications.

## Phase 0 — Establish a reproducible baseline

**Goal:** Know exactly what works before changing more code.

- [ ] Record Python version, OS/Windows version, FFmpeg and ffprobe versions.
- [ ] Confirm repository status and current branch; preserve the reviewed commit SHA.
- [ ] Document install/start/test steps in README.
- [ ] Add a tiny, redistributable or generated test-media fixture, or document commands to generate one.
- [ ] Capture current behavior for upload, probe, conversion, trim, cancellation, preview seeking, and open-folder actions.
- [ ] Run compile/syntax checks and record current failures without hiding them.

**Exit gate:** Baseline steps are repeatable on a clean checkout.

## Phase 1 — P1 security: local API request protection (#2)

**Goal:** Prevent hostile websites or untrusted callers from invoking sensitive local actions.

- [ ] Define the intended local-origin threat model and allowed browser workflow.
- [ ] Remove wildcard CORS unless an explicit, justified use case requires it.
- [ ] Validate Host and Origin against the expected local origin; reject malformed/untrusted values.
- [ ] Add a per-launch unpredictable token or equivalent protection for state-changing API requests.
- [ ] Protect conversion, cancellation, open-folder, and shutdown endpoints as appropriate.
- [ ] Return consistent 4xx errors for rejected requests.
- [ ] Ensure token delivery/storage does not expose it through logs or URLs.
- [ ] Add tests for allowed same-origin calls, hostile Origin, missing/invalid token, unexpected Host, and preflight behavior.

**Exit gate:** Untrusted origins and requests without authorization cannot trigger sensitive actions, while the normal UI still works.

## Phase 2 — P1 filesystem confinement and output safety (#3 + new output-collision issue)

**Goal:** Ensure inputs and outputs remain within approved locations and never overwrite unexpectedly.

- [ ] Define approved input roots and whether uploaded files, workspace files, and outputs are readable.
- [ ] Create one central helper that resolves and validates paths for probe, conversion, preview, and file-manager operations.
- [ ] Reject paths outside approved roots; handle Windows drive paths, UNC paths, traversal, symlinks/reparse points where applicable, and path normalization.
- [ ] Treat custom output names as basenames only; reject separators, absolute paths, drive prefixes, .., and invalid names.
- [ ] Resolve the final output path and prove it remains inside OUTPUTS_DIR.
- [ ] Fix get_unique_output_path(): never return an existing writable path as if it were unique. Use collision-safe naming and avoid race-prone check-then-create behavior where practical.
- [ ] Remove unintended -y overwrite behavior or make overwrite an explicit, confirmed, validated option.
- [ ] Keep local-file discovery scoped to the intended workspace and return only the paths the UI actually needs.
- [ ] Add tests for traversal, absolute paths, Windows drive/UNC paths, Unicode names, duplicate names, concurrent output allocation, and symlink escapes where supported.

**Exit gate:** No API path can escape approved roots and an existing output is never silently overwritten.

## Phase 3 — P1 frontend injection safety (#4)

**Goal:** Render file names and metadata strictly as text.

- [ ] Audit every innerHTML assignment in static/index.html.
- [ ] Replace dynamic templates containing filenames, paths, codec, language, channel layout, subtitle text, or logs with DOM element creation and textContent.
- [ ] Keep innerHTML only for static, trusted markup; do not interpolate untrusted values.
- [ ] Verify event handlers are attached explicitly rather than embedded in strings.
- [ ] Add regression coverage for HTML special characters and script-like filenames/metadata.
- [ ] Manually verify local-file cards and stream details still render correctly.

**Exit gate:** Untrusted media metadata is never interpreted as HTML or script.

## Phase 4 — P1 resource limits and job lifecycle (#5)

**Goal:** Bound resource use and guarantee consistent job cleanup.

- [ ] Validate Content-Length as a positive integer and reject missing, malformed, negative, or over-limit sizes.
- [ ] Enforce a configurable maximum upload size before writing the full body.
- [ ] Stream uploads safely and delete incomplete uploads after disconnect/error.
- [ ] Add a bounded conversion queue and a configurable maximum number of active FFmpeg processes.
- [ ] Define behavior when the queue is full; return a clear response.
- [ ] Make cancellation idempotent and race-safe; do not report cancellation as complete until process termination/cleanup is confirmed.
- [ ] Ensure failed/cancelled jobs remove only their own partial output and never another job's file.
- [ ] Add subprocess timeout and robust process termination handling.
- [ ] Define retention for job records, uploads, thumbnails, and outputs; do not delete user outputs without an explicit policy.
- [ ] Test oversized uploads, queue saturation, client disconnect, disk/write failure, cancellation races, and retention cleanup.

**Exit gate:** Uploads and concurrent conversions are bounded; cancelled/failed jobs reach one consistent terminal state without unmanaged processes or partial files.

## Phase 5 — P1 media correctness: audio strategies (#6)

**Goal:** Ensure UI choices produce the documented audio output.

- [ ] Define behavior for Auto, Direct Copy, AAC Stereo, AAC 5.1, and Mute for each preset.
- [ ] Review stream mapping so video, audio, subtitles, attachments, and multiple audio tracks are intentionally handled.
- [ ] Confirm Mute produces no audio stream.
- [ ] Confirm AAC Stereo outputs AAC with two channels and the intended bitrate/downmix.
- [ ] Confirm AAC 5.1 outputs six channels only when the source and encoder path can support it; otherwise fail clearly or disable the option.
- [ ] Confirm Direct Copy preserves all intended audio tracks and reports incompatible-container/codecs clearly.
- [ ] Confirm Auto uses compatible AAC copy where intended and transcodes when required.
- [ ] Avoid duplicate -map arguments or conflicting codec options across presets.
- [ ] Add unit tests for generated FFmpeg argv and integration tests with AAC, EAC3/AC3, DTS, no audio, multiple tracks, stereo, and 5.1 fixtures.
- [ ] Verify outputs with ffprobe rather than relying only on exit code.

**Exit gate:** Each visible strategy has a documented and verified result for supported presets.

## Phase 6 — P2 controls and progress correctness (#7)

**Goal:** Make controls truthful and input validation predictable.

- [ ] Decide supported GIF frame rate and make the UI and FFmpeg filter use the same value. The current filter is fps=15; do not claim 60 FPS unless implemented and tested.
- [ ] Verify GIF dimensions, palette filter, output format, and no-audio behavior.
- [ ] Validate trim start/end values, reject invalid/negative/out-of-range values, and define end-before-start behavior.
- [ ] Confirm trim and resolution/CRF settings are applied only to supported presets; disable or explain controls that do not apply.
- [ ] Validate resolution, CRF, and other options server-side rather than trusting frontend controls.
- [ ] Test progress and ETA for full-length and trimmed conversions, including unknown/zero duration.
- [ ] Add command-construction tests and small output verification tests.

**Exit gate:** UI labels match output properties, invalid settings fail clearly, and progress does not mislead users.

## Phase 7 — P2 regression suite and CI (#9, #10, #15)

**Goal:** Make future regressions detectable automatically.

- [ ] Add a standard test runner and clear test directory structure.
- [ ] Unit-test parse_fps for 24/1, 30000/1001, 24000/1001, zero denominator, missing values, malformed strings, negative and non-finite values.
- [ ] Unit-test path validation, output collision handling, filename sanitization, API authorization, and HTTP range parsing.
- [ ] Unit-test FFmpeg argument generation for all supported preset/audio combinations.
- [ ] Mock subprocess and file-manager launch calls in unit tests.
- [ ] Add job lifecycle tests for success, error, cancellation, and duplicate cancellation.
- [ ] Add integration tests that are skipped with an explicit reason when FFmpeg/ffprobe are unavailable.
- [ ] Add GitHub Actions for supported Python versions, syntax/compile checks, linting, and tests.
- [ ] Ensure CI results are visible on pull requests and document the local test command.

**Exit gate:** CI passes on the branch, and each fixed issue has a focused regression test.

## Phase 8 — P2 launchers, license, and open-folder behavior (#1, #11, #14, #16)

**Goal:** Make Windows launch/stop and Explorer actions safe and truthful.

- [ ] Verify the repository contains the license stated in README; add the correct license text only after confirming intent and copyright details.
- [ ] Review start.bat quoting, working directory, Python selection, FFmpeg prerequisites, and startup failure messaging.
- [ ] Review stop.bat process matching. Filtering LISTENING on port 5050 is an improvement, but confirm it cannot kill an unrelated process that happens to own that port; ideally identify the actual OmniRemux process safely.
- [ ] In frontend open-folder handlers, check HTTP status and response JSON before displaying success; restore button state on every path.
- [ ] Unit-test reveal_in_file_manager() with temporary paths and mocked platform launch calls.
- [ ] On Windows, manually verify that Show in Folder opens Explorer and selects the exact output file; test spaces, Unicode, missing targets, and folder-only behavior.
- [ ] Record OS/version and outcomes in issues #1 and #16.

**Exit gate:** Launcher scripts affect only the intended server; the UI never claims an API action succeeded when it failed; Windows Explorer behavior is manually verified.

## Phase 9 — Final acceptance and issue closure

- [ ] Run the full automated suite and CI.
- [ ] Run a real-media smoke matrix: upload, workspace load, probe, remux, transcode, audio extraction, GIF, trim, preview seek, cancellation, output collision, open folder, and shutdown.
- [ ] Test both normal and adversarial inputs: unusual filenames, malformed options, invalid paths, invalid range requests, large uploads, and absent streams.
- [ ] Verify outputs using ffprobe and compare expected codec, stream count, channel count, duration, frame rate, and dimensions.
- [ ] Review logs for leaked absolute paths, secrets/tokens, unbounded error bodies, or misleading success messages.
- [ ] Update each GitHub issue with test evidence and commit references.
- [ ] Close an issue only when every acceptance criterion for that issue is met. Keep deferred/non-critical work open and clearly labeled.

## Recommended execution order

1. Baseline and test scaffolding.
2. #2 request authorization.
3. #3 path confinement and output collision safety.
4. #4 frontend injection safety.
5. #5 resource limits and job lifecycle.
6. #6 audio strategy correctness.
7. #7 controls, GIF, trim, and progress.
8. #9/#10 regression tests and CI.
9. #1/#11/#14/#15/#16 launch and file-manager verification.
10. Full acceptance pass and evidence-based issue closure.

**Do not start by polishing the UI or adding features.** Complete the security boundary first, then media correctness, then CI and end-to-end verification.
