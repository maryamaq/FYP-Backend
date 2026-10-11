# Demo Fixes Change Log

Backup before changes: c:\Users\laptops galaxy\Desktop\BSAI-7A\_backup_before_demo_fixes.zip

## Files changed

## Why

## Before/after notes for important regions

## Database changes

---

## FEAT-001 (foundation: safety net, database, honest scoring)

Safety net (outside the repo, in `Desktop\BSAI-7A`): `_backup_full_20261011_1821.zip` (backend + frontend source; excludes venv, .git, __pycache__, emotion_images, build, .dart_tool and the `dataset` folders), `uncommitted_before_demo.patch`, `uncommitted_before_demo_status.txt`. The zip lists `routers/sessions.py` and `hardware/eeg_stream.py`. Database backup: `BACKUP DATABASE ... WITH COPY_ONLY` reported OK to `C:\Program Files\Microsoft SQL Server\MSSQL16.SQLEXPRESS\MSSQL\Backup\VirtualClinicDB_before_demo_20261011_1843.bak` (SQL Server wrote it; the file is not readable from the user account, so its size was not checked).

### Files changed / added
- `database/schema.sql`: comment headers `#` -> `--`; advisor role; Sections, Appointments, QuestionFeedback, AdvisorNotifications, SensorData, EEG_Snapshots; new columns; unique indexes; view.
- NEW `database/demo_additions.sql`, `database/demo_seed_psychologist.sql` (optional, `TEST_Psychologist_2`, `test_psych2@example.com`, password `password123`), `database/integrity_checks.sql` (read-only).
- `processing/scorer.py`: added `NO_PHYSIO_Q_WEIGHT`, minimum-sample constants, `fuse_with_missing`, `get_heart_rate`, `get_bp_change`, `hr_score`, `bp_score`; DELETED `get_feedback_weights`. `fuse_scores`, weights, `classify`, `safety_override` untouched.
- `processing/emotions.py`, `processing/eeg.py`: return `None` when there is too little real data (no neutral/0.4 default, no zeros, dead SensorData-eeg fallback removed); database errors are no longer swallowed.
- `routers/sessions.py` `end_session`: one transaction, EEG stopped first, no 72.0 / bp 0 defaults, guarded UPDATE (409 on a second call), `status='completed'`, new MH_Results columns, confidence 0.0, no feedback weights. The advisor/appointment block is unchanged and marked as the hook that FEAT-003 replaces.
- `routers/results.py`, `models/result_models.py`, `models/session_models.py`: additive fields (`tier`, `missing_modalities`, `unreliable_modalities`, `advisor_notified`, `appointment`, `legacy`; end-session response gets `risk_class`, `missing_modalities`). Physiological fields are nullable.
- `test_demo.py`: prints the new optional fields only.
- NEW tests: `tests/test_scoring.py`, `tests/test_schema_build.py`, `tests/test_demo_flow.py`, `tests/db_test_helpers.py`.

### Before / after
- Before: a session without sensors was scored with made-up values (face neutral 0.4, pulse 72, BP 0) and stored `eeg_avg 0`, `avg_pulse 72.0`. The session was closed BEFORE scoring (a scoring error left it closed without a result). Any feedback row replaced the stage weights.
- After: a signal that was not measured is left out and the other physiological weights are rescaled; with no physiological data `final = 0.70 * questionnaire` and `physio_score` is NULL (label "Questionnaire only"). Stored NULL means "not measured". Scoring and saving are one transaction; if it fails the session stays open. Feedback never changes a weight.
- Complete-data results are identical to before (golden tests). Demo student, no sensors: Low 0.623 Healthy, Medium 1.148 Mild Stress, High 2.198 High Risk.
- To confirm with the supervisor: with no physiological data the score is `0.70 * q`. Setting `NO_PHYSIO_Q_WEIGHT = 1.0` in `processing/scorer.py` scores on the questionnaire alone in that case (Medium script 1.64 stays Mild Stress, High script 3.14 becomes Critical Risk). Default kept.

### Database changes (live `VirtualClinicDB`, applied after printing the list, additive only)
Added: `FacialEmotions.image_path/stage_number/question_id` (+FK_FacialEmotions_question); `MH_Results.questionnaire_score/physio_score/missing_modalities`; `QuestionFeedback.usefulness_label/comments/session_id/updated_at` (+FK_QuestionFeedback_session); `UX_Appointments_session_scheduled`, `CK_Appointments_status`, `UX_QuestionFeedback_psychologist_question`, `CK_QuestionFeedback_label`; view `vw_QuestionFeedbackSummary`. Tables Sections, Appointments, QuestionFeedback, AdvisorNotifications, SensorData, EEG_Snapshots, `Students.section_id` and the advisor role already existed (no-ops). Nothing dropped, deleted, updated or retyped. Row counts unchanged: Users 4, Sessions 37, MH_Results 23, Appointments 5. Second run printed only "already present". A fresh `schema.sql` build has the same structure as the live DB after the additions (compared by content: columns, FKs, CHECKs, indexes, defaults, views).

### Notes
- NIT 10: the `end_session` transaction holds a lock on the session row for the few seconds scoring takes, so a read of that same session row can wait briefly.
- Old results (`missing_modalities IS NULL`, 23 rows) are not edited; the API returns them as `legacy: true` with null physiological values.
- The unique index on `QuestionFeedback (psychologist_id, question_id)` means the CURRENT `POST /psychologist/feedback` (plain INSERT) fails on a second feedback for the same question until FEAT-004 makes it an upsert.
- `eeg_stream.py` still writes a `ppg` row with the fallback pulse 72 until FEAT-002 fixes it; `get_heart_rate` would count such rows as real readings until then.

---

## Step A (FEAT-002 capture)

State found: the aborted run had already edited most of group 3. I checked each item against the code and only added the missing tests.

### Files changed (already in place when this step started, now checked)
- `routers/questionnaire.py`, `models/questionnaire_models.py` (3.1): locked owner read (404 owner mismatch, 409 ended), exact question set for the stage and role (422 for missing/repeated/foreign), `response_choice` int 0-4 or numeric string (labels like "Often" get 422, a contract tightening), server calculates `cal_score = choice * weight` (client value ignored), resubmitting a stored stage returns 200 with no new rows.
- `hardware/eeg_stream.py`, `routers/eeg.py`, `websocket/eeg_handler.py` (3.2): no fabricated pulse (None, no ppg row), statuses searching/waiting_signal/connected/no_device/error, `connected` only after a snapshot is saved, thread uses its own DB connection, `connect` returns `{"status":"starting"}`, WebSocket payload has status, pulse_rate (number or null), message.
- `routers/sensors.py`, `models/sensor_models.py`, `utils/auth_utils.py` (`require_open_session`), `main.py` (model warm-up) (3.3): open session required, server-derived stage, image saved with `image_path`, `undetected` when no face, 422 corrupt/oversized, 503 model failure, 500 on disk failure with no row, `GET /sensors/emotion/{emotion_id}/image` (owner or assigned psychologist), BP/pulse range checks.
- Flutter (3.4): `session_screen.dart` (no simulated pulse/BP, "No pulse signal", BP "Not recorded", EEG chip green only for `connected`), `session_provider.dart` (POST /eeg/connect not awaited, `cameraOk`, `focusedQuestionId` cleared on stage change), `camera_service.dart` (5 s capture, `lastError`/`consecutiveFailures`, medium resolution), `questionnaire_screen.dart` (camera banner), `helpers.dart` (BP prompt says manual).
- NEW in this step: `tests/test_capture.py` (9 tests).

### Not done / skipped
- 200 uV fake-inlet `waiting_signal` test and two-thread double-submit test (marked "if time").
- Not tested on a device: Muse + BlueMuse, phone camera capture every 5 s, Flutter screens visually. The real DeepFace model was not run in tests (replaced by a fake); the start-up warm-up was not run.
- `test_demo.py` already sends integer choices, so it needed no change.

### Checks actually run
- `compileall -q .`: OK.
- `flutter analyze` (frontend): No issues found.
- `DB_NAME=VirtualClinicDB_TEST`, `python -m unittest discover -s tests`: 78 tests, OK (69 earlier + 9 new). New tests cover wrong-set answers (missing/repeated/"Often"/foreign) -> 422 with no rows, numeric-string choice and server `cal_score`, repeat stage with no new rows, other user 404, ended session 409, EEG `no_device` with no `EEG_Snapshots`/`SensorData` rows, no-face frame saved as `undetected` with `image_path` and server stage, corrupt 422 / model failure 503 / disk failure 500 with no row, stage follows submitted answers, image read by owner but 404 for another user.

---

## Step B (FEAT-003 risk outcomes)

### Files changed
- NEW `processing/appointments.py`: `rank_psychologists` (sort by active count, then lowest user_id), `assign_psychologist` (returns the existing Scheduled booking for the session, else books the least busy psychologist; only 'Scheduled' counts as active; a unique-index clash re-selects), `notify_advisor` (Medium: one `AdvisorNotifications` row for the student's section advisor; none if there is no advisor, e.g. a teacher).
- `routers/sessions.py` `end_session`: the old inline advisor/appointment block is replaced by these two calls, still in the same transaction before `commit`. The advisor message now names the real risk class (it used to say "Mild Stress" always). Scores, thresholds and labels untouched.
- NEW `routers/appointments.py`: `POST /appointments/book` (student/teacher; own ended session whose stored result is High/Critical Risk, otherwise 409; 503 if no psychologist; a repeat call returns the same booking with `already_booked: true`). Registered in `main.py`.
- `routers/psychologist.py`: `POST /psychologist/appointments/{appointment_id}/status` (own appointment only, 404 otherwise; Scheduled -> Completed|Cancelled; same status again = 200; anything else 409; other value 422).
- `tests/test_route_auth.py`: added the `{appointment_id}` path replacement.
- NEW `tests/test_appointments.py` (3 pure rank tests + 8 DB tests).
- Flutter (`frontend/`, gitignored): `models/result_model.dart` (backend key `bp_avg_systolic`, nullable doubles, new fields tier/missing_modalities/advisor_notified/appointment/legacy; removed `confidence`, `emotion_distress_score`, `pulse_avg`), `screens/results/result_detail_screen.dart` (Low: guidance + Wellness button; Medium: honest advisor line + Wellness button; High/Critical: appointment card or "Book appointment" button; Critical adds a trusted-person/emergency-service line; "Questionnaire only" / "Incomplete data" chip; legacy text; missing values show "Not recorded"; the screening-not-diagnosis sentence), `core/constants/api_constants.dart` (`appointmentBook`).
- Wellness screen: REUSED the existing `screens/home/wellness_screen.dart` (route `/wellness`, tabs Action Plan / Breathe / Learn). No new screen.

### Done
Plan group 4 (4.1 to 4.4) except the items below.

### Not done
- Role-aware back button on the result screen (still goes to /home).
- Wellness screen content not edited.
- Removed the "Confidence" line and the facial "distress score" from the result screen (the backend sends 0.0 / not computed).
- No two-thread concurrent booking test (the unique index `UX_Appointments_session_scheduled` is the safeguard, not exercised under real concurrency).
- Not run on a device: the Flutter result screen, the Book button and the Wellness navigation were only checked with `flutter analyze`.

### Checks actually run
- `compileall -q .`: OK.
- `DB_NAME=VirtualClinicDB_TEST`, `python -m unittest discover -s tests`: 89 tests, OK (78 + 11 new). New tests cover: rank ascending / tie -> lowest id / empty; scripted Low (0.623 Healthy, 0 appointments, 0 notifications), Medium (1.148 Mild Stress, 1 notification, 0 appointments), High (2.198 High Risk, 1 appointment, 0 notifications); a second `/appointments/book` call keeps the count at 1 and returns the same id; teacher Medium creates no notification; book on Low/Medium/another user's session -> 409; psychologist 403 / no token 401; status Completed twice = 200, then Cancelled = 409, bad value 422, student 403, no token 401. (The status test skips itself if the appointment goes to a psychologist whose password is not the test password; I only read the tail of the output, which showed OK.)
- `flutter analyze` (frontend): No issues found.
- The live `VirtualClinicDB` was not touched by tests.


---

## Step C (FEAT-004 feedback + review)

### Files changed
- `routers/psychologist.py`: `POST /psychologist/feedback` is now an upsert on (psychologist_id, question_id) (UPDATE, then INSERT if no row). Labels `useful` / `less_useful` / `irrelevant` are stored in `usefulness_label` with score 5 / 3 / 1; an older client that sends only a score still works (label derived); label + a different score = 422; comment max 500; optional `session_id` must be a session this psychologist may read (404 otherwise); unknown question 404. Plain helpers `label_to_score`, `score_to_label`, `resolve_feedback`, `stage_at`. NEW `GET /psychologist/feedback/summary` (reads `vw_QuestionFeedbackSummary`). NEW `GET /psychologist/session/{session_id}/review` (psychologist role + assigned-psychologist check): session, result (final_score, risk_class, questionnaire_score, physio_score, missing_modalities), stages with answers, EEG points, face entries (`has_image`, `emotion_id`), each with `offset_sec` from `Sessions.start_time`.
- NEW `tests/test_review_stage.py` (15 tests).
- Flutter (`frontend/`, gitignored): NEW `screens/review/session_review_screen.dart` (route `/session_review` in `app.dart`; header, fl_chart stress-index line, Slider, "At this moment" panel, answers list); `services/api_service.dart` (`authHeaders` getter); `core/constants/api_constants.dart` (two URL helpers); `screens/home/psychologist_dashboard_screen.dart` (5 stars replaced by Useful / Less useful / Irrelevant + comment box `_FeedbackBox`; "EEG Graph" button became "Session Review"; the old EEG dialog `_showEEGTimeline` and `_statBox` removed).

### Done
Plan 5.1, 5.2, 5.3 (core). `fl_chart` was already in pubspec, no dependency added. No weight, threshold or DB change. Feedback only writes `QuestionFeedback`; a test checks `Q_Questions.weight` is unchanged.

### Not done
- `GET /psychologist/session/{id}/answers` does not yet return `my_feedback_label` / `my_comments` (the buttons start empty each time the dialog opens).
- Review screen: no -5 s/+5 s or previous/next-stage buttons, no alpha/beta/theta filter chips, no stage-start lines on the chart, no feedback buttons inside the review screen (they are in the dashboard Q-Answers dialog), no "Feedback summary" button in the app (endpoint exists), no `vitals` in the review response, no stage score.
- No Flutter unit test for the nearest-point helper.

### Notes
- Stage windows: answers are saved when a stage is submitted, so a stage runs from the previous submit (or session start) to its own submit. A point before the first submit is stage 1, a point after the last submit has `stage_number: null` ("after the questionnaire"). A point exactly on a boundary belongs to the stage that just ended. The stored `FacialEmotions.stage_number` is not used for display.
- Legacy results (`missing_modalities` NULL) come back as `missing_modalities: null`.

### Checks actually run
- `compileall -q .`: OK.
- `flutter analyze` (frontend): No issues found.
- `DB_NAME=VirtualClinicDB_TEST`, full `unittest discover -s tests`: 104 tests, OK (1 skipped, the existing appointment-status test that skips itself). New tests: `stage_at` (before first, inside, on boundary, after last, no stages); label->score 5/3/1 and the resolve rules (none, bad label, bad score, label only, score only, both agree, both disagree); DB: second feedback updates the same row (1 row, new label/score/comment, question weight unchanged) and the summary endpoint shows it; bad input 422/404/403; review of a synthetic session (unassigned psychologist 404, then assigned: result 0.623 Healthy, 5 stages with all answers, 2 EEG points with offsets 0-5 and stage 1, 2 faces with has_image True/False, no e-mail in the body, student 403, no token 401); a session without EEG/faces returns empty lists and `missing_modalities` eeg,face,hr,bp.
- Not run: the Flutter screens on a device (feedback buttons, slider, chart, `Image.network` with the auth header); the face image endpoint was not called from the review screen.


---

## Step D (final smoke + report)

### Checks actually run
- `DB_NAME=VirtualClinicDB_TEST`, `python -m unittest discover -s tests`: 104 tests, OK.
- `flutter analyze` (frontend): No issues found.
- Scripted API flow on `VirtualClinicDB_TEST` (synthetic TEST_ users, in-process FastAPI TestClient, no uvicorn started): login x4 roles, start session, 5 stages submitted, synthetic JPEG (stored `undetected`, grey picture has no face), synthetic BP, end session (2.558 High Risk, missing face,hr,bp), result (tier High, appointment present), book (same booking, `already_booked`), exactly 1 appointment row, advisor route 200, feedback 200, review 200 (5 stages, 6 EEG points, 1 face). 20 of 21 steps passed; the 1 note is that the assigned test-DB psychologist had a different password, so the script used TEST_Psychologist. EEG rows were inserted by SQL (no HTTP route writes EEG).
- `database\integrity_checks.sql` on LIVE `VirtualClinicDB`, read-only: all checklist items 1, all orphan/mismatch checks 0, 23 legacy results, 0 new results, no test data inserted. Temporary script `_smoke_flow.py` deleted.

### Could not be tested and why
- Muse + BlueMuse/LSL, phone/webcam capture, BP/pulse device, Flutter on a real device: agents have no hardware. DeepFace on a real face was not run.
- Found: `api_constants.dart` baseUrl is `http://172.19.233.179:8000` but the PC IPv4 is now `192.168.1.9`; the user must update it. Not changed here.
- Report: `.agents\tasks\demo-report.md`.

---
## Step E (phone cannot reach backend / demo logins / cleanup)
### Root cause of the `Start Assessment` timeout
`frontend/lib/core/constants/api_constants.dart` baseUrl was `http://172.19.233.179:8000`. The PC's only real IPv4 is `192.168.1.9` (Wi-Fi `Mirza1`); 172.19.x.x is a stale adapter address. Measured against the running backend: `GET /health` on 192.168.1.9 = 0.10 s OK (db_connected true), on 172.19.233.179 = 20.02 s timeout. So every request timed out, which is why the generic `firewall` message appeared.
### No server-side defect found
Full Start-Assessment sequence over the LAN IP (uvicorn on 0.0.0.0:8000, venv): /health 0.03 s, POST /auth/login 0.13 s, POST /session/start 0.10 s, POST /eeg/connect 0.04 s, GET /questionnaire/stages 0.03 s, GET /questionnaire/questions/1 0.03 s, GET /eeg/status 0.03 s. WebSocket `/ws/eeg/{id}?token=` connected in 0.03 s and sent its first payload in 0.01 s. The route handlers are plain `def` so FastAPI runs them in the threadpool, and the 5 s LSL `resolve_streams` happens inside `EEGStream._run` on its own thread, so nothing blocks the event loop. DeepFace is loaded once in the `lifespan` startup, not per request.
### Changed
- `api_constants.dart`: baseUrl -> `http://192.168.1.9:8000` + comment that it must be re-checked per Wi-Fi and needs a full rebuild.
- `api_service.dart`: timeout 10 s -> 20 s (POST /session/end does all the scoring queries); the timeout message now names the request (`GET/POST <path>`) and the configured baseUrl instead of always blaming the firewall.
- `android/app/src/main/AndroidManifest.xml`: added `android.permission.INTERNET` and `android:usesCleartextTraffic="true"`. Debug builds got INTERNET from `src/debug`, a release APK would not, and plain http:// to an IP needs cleartext.
### Deleted
`migrate_psychologist.py` (one-off migration, already applied, imported by nothing), `.gitignore.additions.txt`, `frontend/.agents/` (biometric-fallback-review.md), all backend `__pycache__` folders.
### Checks actually run
`compileall -q .` OK; `DB_NAME=VirtualClinicDB_TEST` + `unittest discover -s tests` 104 tests OK (1 skipped); `flutter analyze` No issues found.
### Could not be tested
No real phone, no Muse headset, no camera, no BP device. Sessions 38 and 39 were created on the LIVE database by the timing test and are still open (no questionnaire answers, no result rows).

---
## STEP A (facial emotion "undetected" + EEG/PPG hardware check)

### A1 Facial emotion: root cause
The 11 `FacialEmotions` rows of the real run (session 40, live `VirtualClinicDB`) are all `undetected`,
each with an `image_path`. The older sessions (25, 32) show real labels because the OLD code called
DeepFace with `enforce_detection=False`, which never fails: it labels the whole frame even when there
is no face. The current code uses `enforce_detection=True` (honest), and the default detector is the
OpenCV Haar frontal-face cascade, which only finds UPRIGHT faces. A phone front-camera frame that
arrives sideways (sensor landscape vs. user portrait) is therefore rejected with
"Face could not be detected", and the row is stored as `undetected`.

Checked and ruled out:
- EXIF rotation is NOT ignored: OpenCV 4.9 `cv2.imdecode` DOES apply the EXIF orientation tag
  (measured: landscape pixels + orientation 6 decoded as 640x480 portrait).
- Colour order: DeepFace is given the BGR array from `cv2.imdecode`, which is what it expects.
- Could NOT inspect the real frames: the 11 files named in the database do not exist in
  `emotion_images` (the folder is empty) and a search of the whole user profile for
  `emotion_1_40_*.jpg` found 0 files. They were removed after the session (the folder is gitignored
  and is excluded from the backup zip). So file size / dimensions / darkness of the real frames
  could not be measured. Reported, not guessed.

### A1 Fix
`routers/sensors.py`: new `detect_emotion(frame)` helper. It runs the same DeepFace call
(`enforce_detection=True`) on the frame and, only if no face is found, retries the frame rotated
90 clockwise, 90 anticlockwise and 180. The first rotation with a face wins; the picture is saved in
that orientation so the psychologist review is not sideways. If no rotation has a face the row is
still stored as `undetected` with its image path (no fabricated emotion). A model error is still 503
and an unusable picture still 422.

### A1 Before/after evidence (real face images, project code path)
The real session frames are gone, so 12 real face photos from `ml/dataset/test` (FER test set) were
pasted on a 480x640 phone-sized frame and run through the project code: BEFORE = one upright call
(old behaviour), AFTER = `routers.sensors.detect_emotion`.

| frames | BEFORE detected | AFTER detected |
|---|---|---|
| 12 upright | 8 / 12 | 8 / 12 |
| 12 sideways 90 | 1 / 12 | 8 / 12 |
| 12 upside down | 0 / 12 | 8 / 12 |
| total 36 | 9 / 36 | 24 / 36 |

Labels on upright frames are unchanged (happy/sad/angry/neutral/fear as before). Cost: a frame with a
face found upright is as fast as before (~0.2-0.3 s); the worst case (no face in any rotation) measured
0.40 s, far below the 5 s capture interval. 4 of the 12 FER pictures are never detected in any rotation
(48x48 upscaled images are too coarse for the Haar cascade) - the detector is still the weak point.
No new package and no new model download was added: only `opencv` is available offline
(`~/.deepface/weights` has the expression model only), so the detector backend was NOT changed.

### A2 EEG/PPG regression review (git diff of the 4 files)
Reviewed line by line against a real headset. UNCHANGED by this week's edits: LSL discovery
(`resolve_streams(wait_time=5.0)`), the EEG/PPG stream matching by type and name, the frontal channel
choice (AF7/AF8 = index 1,2), 256 Hz / 64 Hz rates, the 2 s / 512-sample window, artifact rejection at
+-150 uV, the 1-40 Hz Butterworth filter, the FFT band powers and `stress_index = (beta+theta)/alpha`,
the PPG IR channel (index 1) and the 0.8-3.5 Hz peak detection, the `EEG_Snapshots` insert and the
`SensorData` `data_type='ppg'` insert. PPG is read from its OWN LSL inlet (type `PPG`), not from the
EEG stream. The session end stops the thread (`routers/sessions.py` -> `stop_eeg_stream`) and the
thread closes its own DB connection and both inlets.

Intentional (not regressions): no fabricated pulse 72 (None -> no `ppg` row), `connected` only after a
snapshot is really saved, statuses searching / waiting_signal / connected / no_device / error, a dead
thread is replaced on Retry, auth on `/eeg/*` and a `?token=` on the WebSocket.
No regression found that would stop a real Muse from recording, so nothing in the EEG code was changed.

### A2 Verified with synthetic input (no Muse was available)
NEW `tests/test_capture.py` -> `EegSyntheticStreamTests`: a fake LSL inlet feeds the real `EEGStream`
a 10 Hz + 20 Hz sine as EEG (uV) and a 1.2 Hz sine (= 72 bpm) on the PPG IR channel.
- EEG + PPG streams: status becomes `connected`, >= 2 `EEG_Snapshots` rows are written with
  alpha > 0 and a stress index > 0, >= 1 `SensorData` `ppg` row with a pulse inside 40-200 and within
  12 bpm of the 72 bpm input, 0 save failures, and the thread is dead after `stop()`.
- EEG stream only (no PPG): snapshots are written but `SensorData` stays empty and `pulse_rate` is
  None - the old fake 72 is really gone.
- The existing no-device test still proves `no_device` writes no rows at all.

### A2 Minimum-sample feasibility in a normal 5-10 minute session
| signal | minimum | insert rate | time to reach | verdict |
|---|---|---|---|---|
| EEG (`MIN_EEG_SNAPSHOTS` 5) | 5 snapshots | 1 per 2 s | ~10 s | easy (a 5 min session gives ~150) |
| pulse (`MIN_HR_READINGS` 3) | 3 ppg rows | 1 per saved snapshot when a pulse is measurable | ~6 s | easy |
| face (`MIN_FACE_SAMPLES` 3) | 3 detected frames | 1 frame per 5 s | ~15 s of detected frames | reachable, depends on detection (see A1) |
| BP (`MIN_BP_READINGS` 2) | 2 readings | none | never from the app | DEFECT, see below |

BP: `Helpers.showBPPrompt` is only an information dialog - it has no input fields and never calls
`POST /sensors/bp`, so no session can ever reach 2 BP readings and `bp` is always reported missing.
This is an old gap, not a regression from this week. Adding a BP entry form changes the user flow, so
it was NOT done here; it needs your decision.

### Checks actually run
- `venv\Scripts\python.exe -m compileall -q .` -> OK (exit 0).
- `DB_NAME=VirtualClinicDB_TEST`, `python -m unittest discover -s tests` -> Ran 106 tests, OK
  (skipped=1, the known appointment-status skip). Baseline was 104, the 2 new ones are the synthetic
  EEG/PPG tests.
- `flutter analyze` in `frontend` -> No issues found.
- Live `VirtualClinicDB` was only READ (SELECT of the latest `FacialEmotions` rows). Nothing written.
- Temporary scripts (`_face_check.py`, `_exif_check.py`) and diff/log dumps were deleted.

### Still UNVERIFIED (no Muse headset, no phone camera here) - manual steps for you
Camera (3 steps):
1. Start a session, hold the phone so your face fills the middle of the preview, in good front light.
2. After ~30 s, check the newest rows: `SELECT TOP 10 dominant_emotion, image_path, captured_at FROM
   FacialEmotions ORDER BY emotion_id DESC` - you should now see real labels, not only `undetected`.
3. Open the matching files in `Backend\emotion_images`. If the face is tiny, very dark, or cut off at
   the edge, that is phone framing, not the server: move the phone closer / add light. If the label is
   still `undetected` while the saved picture clearly shows an upright, well-lit face, the Haar
   detector is the limit - tell me and I will look at a stronger detector (needs a one-off download).
EEG/PPG:
1. Turn on the Muse, start BlueMuse, press Start streaming (both the EEG and the PPG stream).
2. Start the backend and a session; the chip should go orange "Waiting for signal" then green
   "EEG recording" within ~10 s.
3. During the session the Live Vitals pulse should show a number; "No pulse signal" means the PPG
   stream is not being sent (BlueMuse: enable PPG) - the app will never invent a value.
4. After ending the session check `SELECT COUNT(*) FROM EEG_Snapshots WHERE session_id = <id>` (expect
   many) and `SELECT COUNT(*) FROM SensorData WHERE session_id = <id> AND data_type = 'ppg'`, and that
   the result row has a non-NULL `eeg_avg`.

### Files changed in STEP A
- `routers/sensors.py` (rotation-retry detection, picture saved in the detected orientation).
- `tests/test_capture.py` (+2 synthetic EEG/PPG tests, `import time`).
- No EEG/Flutter/database/schema change. Scoring weights, thresholds and labels untouched.

### Teacher login email -> hamza@biit.edu.pk
Investigated first: nothing in the code generates or pattern-validates a BIIT email. `routers/auth.py`
`register` just inserts whatever email is posted, `models/user_models.py` only uses `EmailStr`, and the
Flutter login screen (`frontend/lib/screens/auth/login_screen.dart`) only checks that the text contains
`@`. There is no registration screen in the app at all. So NO generator was added - the single existing
teacher row in the live DB was renamed instead.

Live `VirtualClinicDB`, one parameterized UPDATE on one row:
`UPDATE Users SET email = ? WHERE user_id = ?` with (`hamza@biit.edu.pk`, 2).
- BEFORE: 2 | Hamza (2023-ARID-0168) | 2023-arid-0168@biit.edu.pk | teacher
- AFTER:  2 | Hamza (2023-ARID-0168) | hamza@biit.edu.pk | teacher
Password unchanged, name unchanged, no other user or table touched. Student emails left as they are.

Check actually run: in-process FastAPI TestClient `POST /auth/login` with the new email and the
unchanged password -> 200, user_id=2, role=teacher. The one-off script used for this was deleted.

Old email still hardcoded in DOCS only (no SQL seed or test fixture uses it): `PROJECT_DOCUMENTATION.md`
(stale demo-account table, also lists it wrongly as "Student 2") and `.agents/tasks/demo-report.md`
line 94. Neither was edited here (`database/schema.sql` and the stale docs are owned by other agents).

## Dashboard polish: next assessment due date + bottom navigation bar

- Next assessment due date: `ASSESSMENT_INTERVAL_DAYS = 14` in `routers/results.py`. `GET /results/user/{user_id}` (already called by the dashboard) now also returns `next_due_date` and `due_status` ("due now" / "due in N days"), computed as the latest COMPLETED session end_time (end_time present and a stored risk label) + 14 days. Ownership is still enforced by `require_same_user` against the token. If the user has no completed session, both fields are null and the dashboard card shows "No assessment taken yet" - no date is ever invented.
- Flutter: `UserHistory` model added in `models/result_model.dart`, `ResultsService.getUserHistory` now returns it, `ResultsProvider` exposes `nextDueDate` / `dueStatus`, and `screens/home/home_screen.dart` shows one small card with the date, the status text and a "Start assessment" button that reuses the existing `/session` navigation.
- Bottom navigation bar: `home_screen.dart` is now a Scaffold with an `IndexedStack` over the existing dashboard body and the existing `WellnessScreen` (risk taken from the latest session), plus a 2-item `BottomNavigationBar` (Home, Wellness). No new screens, no routing changes, no new packages. There is no separate history screen (history lives in the dashboard) and no profile screen, so those tabs were omitted. Psychologist and advisor dashboards untouched.

## Database and file clean-up (unused tables + stale docs)
- Dropped 2 unused tables from the LIVE `VirtualClinicDB`: `SessionBP` and `WindowAnalysis`. Both were
  left over from an earlier design; BP readings are stored in `SensorData`, per-window analysis was never
  built. Checks run before dropping: (a) no Python, test, Flutter or SQL file referenced either name,
  only their `CREATE TABLE` blocks in `database/schema.sql`; (b) live row count was 0 for both;
  (c) `sys.foreign_keys` showed only their own FK to `Sessions` - no other table pointed at them, and
  `sys.sql_expression_dependencies` listed no view/procedure using them; (d) fresh copy-only full backup
  taken first: `C:\Program Files\Microsoft SQL Server\MSSQL16.SQLEXPRESS\MSSQL\Backup\VirtualClinicDB_predrop_20261011_232329.bak`
  (confirmed in `msdb.dbo.backupset`, `RESTORE VERIFYONLY` + `RESTORE HEADERONLY` passed).
  Live DB now has 15 tables. No other table, column, row, index or view was touched.
- `database/schema.sql`: removed the two `CREATE TABLE` blocks so a fresh build matches the live DB.
- Deleted stale planning files: `.agents/tasks/design.md`, `design-review.md`, `design-review.json`,
  `plan.md` and the whole `.agents/tasks/task-demo-implementation/` folder (7 JSON files). Kept
  `demo-changes.md` and `demo-report.md`. Also cleared `__pycache__` / `.pyc` (they come back whenever
  the backend runs; they are gitignored).
- Checks actually run: `compileall` on all backend packages -> OK; `venv\Scripts\python.exe -m unittest
  discover -s tests` with `DB_NAME=VirtualClinicDB_TEST` -> 106 tests OK (the suite rebuilds a scratch DB
  from `schema.sql`, so the edit is valid SQL); `database/integrity_checks.sql` read-only on live -> all
  structure items 1, all "expect 0" rows 0.
