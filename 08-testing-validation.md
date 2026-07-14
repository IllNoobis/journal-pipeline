# Feature: Testing & Validation Plan

Build and verify in this order — don't wire the orchestrator together until every stage passes standalone.

## 1. Config
- [ ] `python -c "import config"` succeeds with all three credential files present.
- [ ] Deliberately remove one credential file and confirm a clear, specific error (not a generic traceback).

## 2. YouTube upload
- [ ] `upload_to_youtube.py` on a short (~1 min) test clip produces a real video visible in YouTube Studio.
- [ ] Confirm `privacyStatus` is `unlisted` in the API response, not `private` or `public`.
- [ ] Second run against the same file: confirm it asks before re-uploading rather than silently duplicating.
- [ ] First-run OAuth flow: browser consent screen appears once; second run reuses `youtube_token.json` with no browser prompt.

## 3. Captions / transcript
- [ ] Immediately after upload, confirm `wait_for_captions.py` correctly reports "not ready" rather than erroring out.
- [ ] After the normal YouTube processing delay, confirm it successfully fetches and the formatted `[HH:MM:SS] text` output matches what's actually said in the test clip.
- [ ] Force a `TranscriptsDisabled` case (e.g. a video with captions off) and confirm it fails with a clear message instead of hanging.

## 4. Extraction (use a test transcript with known ground truth)
Script a short test session covering:
- At least 2 genuine executed trades, with entry/stop/target spoken aloud.
- At least 1 theoretical statement ("if it breaks the high I'd go long").
- At least 1 backtest/replay mention, clearly distinguished from live trading.
- At least 1 moment where you deliberately don't state a number (e.g. don't say your stop out loud), to verify the model leaves it null instead of guessing.

Checks:
- [ ] Pass 1 segmentation correctly separates actual / theoretical / backtest windows.
- [ ] Pass 2 extracts the 2 genuine trades with zero fabricated numeric fields.
- [ ] The theoretical and backtest windows produce no trade records.
- [ ] The deliberately-unstated field comes back `null`, not a guessed value.
- [ ] `confidence` scores are visibly lower on the trade with less explicit detail.

## 5. Sheets logging
- [ ] First run appends the expected number of rows in the correct column order.
- [ ] Second run against the same trades file appends **zero** additional rows.
- [ ] A `video_link` cell opens YouTube within a couple seconds of the actual trade moment.
- [ ] A trade with `confidence < 0.75` shows `status = "Needs Review"`; one above threshold shows `"Auto-logged"`.

## 6. Full orchestrator run
- [ ] One real ~2 hour session end to end, unattended through the caption wait.
- [ ] Kill the process mid-run (during extraction) and confirm re-running resumes correctly without re-uploading or re-fetching the transcript.
- [ ] Final printed summary line matches the actual sheet contents.

## 7. Only after all of the above pass
Consider Discord/OpenCode triggering (explicitly out of scope for this build — see `IMPLEMENTATION_PLAN.md` Section 8) as a separate follow-on project.
