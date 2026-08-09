# PTA Backend — Academic Year / Term / Class Level / Student / Promotion Subsystem

FastAPI backend for a Ghana PTA SaaS (Parents–Teachers Association dues, meetings,
announcements, SMS, reports). This README focuses on the **academic calendar +
class ladder + student enrollment + end-of-term promotion** part of the system.

- [Repo layout](#repo-layout)
- [Quick start](#quick-start)
- [Environment](#environment)
- [Data model](#data-model)
  - [Entities overview](#entities-overview)
  - [AcademicYear — `academic_years`](#academicyear--academic_years)
  - [AcademicTerm — `academic_terms`](#academicterm--academic_terms)
  - [ClassLevel — `class_levels`](#classlevel--class_levels)
  - [Student — `students`](#student--students)
  - [ParentStudentLink — `parent_student_links`](#parentstudentlink--parent_student_links)
- [Class-level ladder & naming](#class-level-ladder--naming)
  - [Canonical name normalization](#canonical-name-normalization)
- [Academic calendar CRUD & lifecycle](#academic-calendar-crud--lifecycle)
  - [Academic years](#academic-years)
  - [Terms](#terms)
  - [Selecting the "current" term / year](#selecting-the-current-term--year)
  - [Closing a term + promotion trigger](#closing-a-term--promotion-trigger)
- [Promotion engine](#promotion-engine)
  - [How the promotion ladder is built](#how-the-promotion-ladder-is-built)
  - [Per-student processing](#per-student-processing)
  - [Promotion return schema](#promotion-return-schema)
- [JHS → SHS transition](#jhs--shs-transition)
  - [Form 1–3 ⇄ JHS 1–3 one-time migration script](#form-13--jhs-13-one-time-migration-script)
- [Student validation rules](#student-validation-rules)
- [Migrations](#migrations)
- [Testing locally](#testing-locally)
- [Celery worker (SMS + scheduled locks)](#celery-worker-sms--scheduled-locks)
- [Design notes / known quirks for reviewers](#design-notes--known-quirks-for-reviewers)

---

## Repo layout

```text
app/
├── main.py                          # FastAPI app, startup DB probe
├── core/
│   ├── config.py                    # Settings; DATABASE_URL ⇄ _SYNC auto-derive
│   ├── database.py                  # Sync SQLAlchemy engine (Neon pooler aware)
│   ├── security.py                  # JWT, bcrypt, require_permission(...)
│   ├── middleware.py
│   └── redis_url.py
├── models/
│   ├── academic.py                  # AcademicYear, AcademicTerm, TermStatus enum
│   ├── class_level.py               # ClassLevel
│   ├── student.py                   # Student
│   ├── parent_student_link.py       # ParentStudentLink
│   └── ...
├── services/
│   ├── promotion.py                 # promote_students_for_year(...)
│   ├── class_level_names.py         # normalize_class_level_name, find_class_level
│   ├── student_validation.py        # validate_student_fields
│   ├── dues_balance.py              # get_current_academic_term helper
│   └── ...
├── api/
│   ├── v1/routers/
│   │   ├── academic.py              # /admin/academic (years + terms + close/promote)
│   │   ├── class_levels.py          # /admin/class-levels CRUD
│   │   ├── students.py              # student create/update/import
│   │   └── ...
│   └── scripts/
│       ├── migrate_form_to_jhs.py   # one-time Form x → JHS x renamer
│       ├── seed_demo_data.py        # canonical KG→Form3 ladder + demo students
│       └── seed_admin.py
└── workers/
    ├── celery_app.py
    └── sms_tasks.py
alembic/versions/                    # Alembic migration chain
requirements.txt
pyproject.toml
runtime.txt                          # python-3.12.10
Procfile                             # web + worker
.env.example                         # copy → .env and fill in
```

---

## Quick start

```bash
# 1. Virtualenv
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# 2. Dependencies
pip install -r requirements.txt

# 3. Env + DB (Neon or local Postgres)
copy .env.example .env
# Edit DATABASE_URL and / or DATABASE_URL_SYNC. Setting EITHER one is enough —
# the Settings model auto-derives the other from it.

# 4. Schema (Alembic — always)
alembic upgrade head

# 5a. Optional: bootstrap the KG→SHS ladder + a demo 2024/2025 year/term + ~50 students
python app/api/scripts/seed_demo_data.py

# 5b. Optional: create the admin user (admin@gmail.com / 123)
python -c "from app.core.database import SessionLocal;\
from app.models.user import User, UserRole;\
from app.core.security import hash_password;\
db=SessionLocal();\
u=db.query(User).filter(User.email=='admin@gmail.com').first();\
pw=hash_password('123');\
print('exists' if u else 'new');\
"
# (or use app/api/scripts/seed_admin.py if you want the built-in seeder)

# 6. Run
uvicorn app.main:app --reload
```

Then open:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc:    http://127.0.0.1:8000/redoc

Health endpoint: `GET /` should return
`{"message":"Welcome to PTA SaaS","version":"1.0.0"}`.

---

## Environment

Copy `.env.example` → `.env`. For database connection **only one of the two URLs
below needs to be set**; the other is derived automatically.

```env
# Async driver — used by endpoints that need async DB sessions
DATABASE_URL=postgresql+asyncpg://user:pw@host-pooler.aws.neon.tech/db?sslmode=require&channel_binding=require

# Sync driver — used by Alembic, Celery, startup probe
DATABASE_URL_SYNC=postgresql://user:pw@host-pooler.aws.neon.tech/db?sslmode=require&channel_binding=require
```

Other important variables for this subsystem:

```env
# Seed target (used only by seed_demo_data.py)
CURRENT_ACADEMIC_YEAR=2024/2025
```

---

## Data model

### Entities overview

There is **no dedicated `schools`, `grades`, or `enrollments` table**.
A student's "current enrollment" is recorded as denormalized text columns on the
`students` row itself (overwritten on promotion). Historical dues/payment/meeting
rows carry their own snapshot `academic_year VARCHAR` so they don't mutate when a
student is promoted or the year label is edited.

```text
academic_years
  id        PK uuid-string(36)
  label     UK VARCHAR(20)         e.g. "2024/2025"
  track     ENUM classleveltrack   NOT NULL default BASIC  {BASIC, SHS}
  is_active BOOLEAN

academic_terms
  id                PK uuid-string(36)
  academic_year_id  FK -> academic_years.id   NOT NULL
  academic_year     VARCHAR(20)  NOT NULL     *denormalized label copy*
  name              VARCHAR(20)  NOT NULL     e.g. "Term 1"
  sequence          INTEGER      NOT NULL     1..3 within year
  start_date, end_date  DATETIME  NOT NULL
  status            ENUM termstatus           PLANNED / ACTIVE / CLOSED
  is_current        BOOLEAN                    *global app-enforced single truth*
  auto_promote_on_close  BOOLEAN default true
  UNIQUE(academic_year_id, name)

class_levels
  id                    PK uuid-string(36)
  name                  UK VARCHAR(100)        "JHS 3", "Form 2" …
  track                 ENUM classleveltrack   NOT NULL default BASIC  {BASIC, SHS}
  sequence              UK INTEGER             1..13 determines promotion order
  is_terminal           BOOLEAN                promote() → graduate/inactive
  requires_index_number BOOLEAN                BECE index required?
  requires_stream       BOOLEAN                programme (General Science etc.)?
  is_active             BOOLEAN

students
  id              PK uuid-string(36)
  index_number    UK VARCHAR(50) NULLABLE      10-digit BECE index
  full_name       VARCHAR(255) NOT NULL
  gender          CHAR(1) NULLABLE             M / F
  form            VARCHAR(50) NULLABLE         *class level name, overwritten on promote*
  stream          VARCHAR(100) NULLABLE        programme/track for SHS
  parent_phone_1, parent_phone_2  VARCHAR(20)
  is_active       BOOLEAN default true
  academic_year   VARCHAR(20) NULLABLE         *denormalized year label*
  graduated_basic_at  DATETIME NULL            *write-once permanent, set on JHS3 graduation*
  graduated_shs_at    DATETIME NULL            *write-once permanent, set on Form3 graduation*
  created_at, updated_at

parent_student_links
  id, parent_id, student_id    (no DB FK)
  relationship, confidence_score, created_at
```

### AcademicYear — `academic_years`

Source: [app/models/academic.py:14–21](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/models/academic.py#L14-L21)

Minimal entity. Just a unique label, soft `is_active`, creation timestamp. No
DB-level "only one active year" constraint.

### AcademicTerm — `academic_terms`

Source: [app/models/academic.py:23–37](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/models/academic.py#L23-L37)

- Belongs to one year via real FK on `academic_year_id`.
- Also carries a denormalized copy of the year's **label** in `academic_year` —
  this is the field that dues, payments, meetings, expenditures all filter on
  (no joins needed in reporting queries).
- `UNIQUE(academic_year_id, name)` — you can't have two "Term 1" records
  inside the same year.
- `is_current` is a single global boolean. At most one term should be `True` at
  any time. The enforce is app-layer (bulk `UPDATE … SET is_current=False` then
  set the target to `True` inside each endpoint that changes it).

### ClassLevel — `class_levels`

Source: [app/models/class_level.py](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/models/class_level.py)

The promotion ladder is fully driven by the `sequence` column. Sequence is
globally UNIQUE, so `ORDER BY sequence` produces the full progression. Key
fields plus per-level booleans control behavior:

| Field | Type | Description |
|---|---|---|
| `track` | ENUM `classleveltrack` (BASIC/SHS) NOT NULL default BASIC | Ladder segment. BASIC=KG→JHS3, SHS=Form1→Form3. |

| Flag | Meaning |
|---|---|
| `is_terminal` | `promote()` graduates and inactivates the student (unconditional on both JHS 3 / BASIC and Form 3 / SHS). Form/year/stream are preserved as a historical snapshot. |
| `requires_index_number` | Student import/create fails unless 10-digit BECE index provided |
| `requires_stream` | Student import/create fails unless programme/stream provided |
| `is_active` | Soft delete; DELETE API sets this to `False` |

### Student — `students`

Source: [app/models/student.py](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/models/student.py)

Think of this table as "students currently enrolled / recently graduated."

- `form` + `academic_year` are denormalized text. Promotion only modifies `form`
  (and `is_active` for graduates). The `academic_year` column is used as a
  **filter** when selecting which cohort to promote — so if you close a term
  for year `2024/2025`, only students matching that literal string in
  `students.academic_year` will be moved.
- `index_number` is unique at the DB but nullable (JHS 3 / Forms need it;
  KG / Primary don't).
- `gender` is a free-form `VARCHAR(1)`; validation normalizes Male/Female/Boys/Girls
  into `M` or `F`.
- `graduated_basic_at` DATETIME NULL — write-once permanent timestamp set on
  JHS 3 (BASIC) graduation.
- `graduated_shs_at` DATETIME NULL — write-once permanent timestamp set on
  Form 3 (SHS) graduation.
- **No FK** from `students.form` → `class_levels.name`. Text equality is used in
  app code. Typo'd `form` strings cause the student to be skipped by promotion
  (reported as `unchanged`).

`graduated_basic_at` / `graduated_shs_at` are write-once permanent timestamps
set by promotion. JHS 3 graduation NEVER sets form to a magic 'Graduated'
string; it preserves the JHS 3 form/year values for history. Same for Form 3
graduation. Re-activation into SHS (Form 1) happens only via the explicit
`/students/{id}/enroll-shs` endpoint.

### ParentStudentLink — `parent_student_links`

Source: [app/models/parent_student_link.py](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/models/parent_student_link.py)

Many-to-many bridge. `confidence_score` is populated by the automated parent–
student matching pipeline (pending matches → confirmed links). No DB-level FK
or uniqueness; duplicate links are prevented app-side in the registration flow.

---

## Class-level ladder & naming

The canonical Ghana PTA ladder seeded by
[app/api/scripts/seed_demo_data.py:16–30](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/api/scripts/seed_demo_data.py#L16-L30)
is:

| Track | Seq | Name | Terminal? | BECE index? | Programme? |
|---|---|---|---|---|---|
| BASIC |  1 | KG        |   |   |   |
| BASIC |  2 | Primary 1 |   |   |   |
| BASIC |  3 | Primary 2 |   |   |   |
| BASIC |  4 | Primary 3 |   |   |   |
| BASIC |  5 | Primary 4 |   |   |   |
| BASIC |  6 | Primary 5 |   |   |   |
| BASIC |  7 | Primary 6 |   |   |   |
| BASIC |  8 | JHS 1     |   |   |   |
| BASIC |  9 | JHS 2     |   |   |   |
| BASIC | 10 | JHS 3     | ✔︎ | ✔︎ |   |
| SHS   | 11 | Form 1    |   | ✔︎ | ✔︎ |
| SHS   | 12 | Form 2    |   | ✔︎ | ✔︎ |
| SHS   | 13 | Form 3    | ✔︎ | ✔︎ | ✔︎ |

### Canonical name normalization

All user-provided level names pass through
[`normalize_class_level_name()`](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/class_level_names.py#L21-L65)
before being stored or matched:

| Input | Normalized to |
|---|---|
| `kg 1`, `kg2`, `kg`, `Kindergarten` | `KG` |
| `primary 4`, `Primary-4` | `Primary 4` (1–6 enforced) |
| `jhs 1`, `JHS-2` | `JHS 1`, `JHS 2` (1–3 enforced) |
| `form 3`, `Form 1` | `Form 1`…`Form 3` (1–3 enforced) |
| `shs 2`, `SHS1` | `Form 2`, `Form 1` (SHS n aliases to Form n) |

Fuzzy lookup helper
[`find_class_level(db, form)`](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/class_level_names.py#L87-L107)
first tries a direct `name == canonical` match, then falls back to scanning
active levels and comparing normalized names. This lets existing messy data
still match even if it was inserted before the normalizer existed.

---

## Academic calendar CRUD & lifecycle

All endpoints live in [app/api/v1/routers/academic.py](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/api/v1/routers/academic.py)
and are gated by `require_permission("academic")`.

### Academic years

| Method | Path | Description |
|---|---|---|
| POST | `/admin/academic/years` | Body `{label}` (e.g. `2025/2026`). 409 if label exists. Returns created year. |
| GET  | `/admin/academic/years` | List ordered by label DESC. |

Creating a year does **not** create terms or auto-set it as "current".

### Terms

| Method | Path | Description |
|---|---|---|
| POST | `/admin/academic/years/{year_id}/terms` | Body `{name, sequence, start_date, end_date, auto_promote_on_close?}`. Requires all 4 required fields. Inserts as `PLANNED + not_current`; if **no term anywhere is `is_current` yet**, this term also auto-becomes current + ACTIVE (so the very first term you create is immediately usable). 409 on same name within the year. |
| GET  | `/admin/academic/years/{year_id}/terms` | Terms for one year ordered by `sequence`. |
| GET  | `/admin/academic/terms?academic_year=…` | All terms (ADMIN / FINANCIAL_STAFF only), optionally filtered by the denormalized `academic_year` label. Good for reporting filters. |

### Selecting the "current" term / year

**DB-level truth for "current term"**: `AcademicTerm.is_current = True`.

- Public endpoint: `GET /admin/academic/current` → serialized term or `null`.
- Service helper (used by dues, reporting):
  [`get_current_academic_term(db)`](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/dues_balance.py#L83-L84).
- **"Current academic year"** is not a standalone concept. Code that needs it
  reads: `current_term.academic_year` (the denormalized VARCHAR label).

Make a different term current with:

| Method | Path | Description |
|---|---|---|
| POST | `/admin/academic/terms/{term_id}/activate` | Sets all other terms `is_current=False`, then marks target as `is_current=True` + `status=ACTIVE`. Refuses to activate a `CLOSED` term. |

### Closing a term + promotion trigger

| Method | Path | Description |
|---|---|---|
| POST | `/admin/academic/terms/{term_id}/close` | Body optional `{promote_students: bool}`. If body omitted, uses the term's stored `auto_promote_on_close`. Sets `status=CLOSED`; if it was current, also clears `is_current`. If promote=true, calls `promote_students_for_year(db, term.academic_year)` inline; returns both updated term + promotion summary. |

⚠️ Closing a term does **NOT** auto-activate the next one. After closing, the
"current" slot is empty. Either activate the next term manually, or simply
create it (first-term-in-empty-state auto-activates).

---

## Promotion engine

All promotion logic is in
[app/services/promotion.py](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/promotion.py).
Entry point is
[`promote_students_for_year(db, academic_year: str)`](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/promotion.py#L46-L111).

### How the promotion ladder is built

[`_promotion_map(db)`](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/promotion.py#L10-L38)
returns a `{canonical_name → next_canonical_name | 'graduate_basic' | 'graduate_shs'}` dict.
`_promotion_map` splits between BASIC and SHS tracks. Cross-track edges
(BASIC terminal JHS3 followed by SHS's Form1) are intentionally **SKIPPED**.
Promotion only moves students within the same track. Terminal levels map to
`'graduate_basic'` for BASIC track, and `'graduate_shs'` for SHS track.

Build steps:

- Query all active `ClassLevel`, ordered by `track, sequence ASC`.
- Group by `track` (BASIC bucket, SHS bucket).
- Within each track group, for each consecutive pair:
  `levels[i] → levels[i+1]` normalized name (intra-track only).
- Last row per track (if marked `is_terminal=True`) maps to a sentinel string
  (`'graduate_basic'` or `'graduate_shs'`) instead of `None`.
- Non-terminal tail with no successor within same track: omitted from dict →
  student stays unchanged.

With the full KG→Form3 seed ladder, the resulting two independent ladders are:

```
BASIC: KG → Primary 1 → … → Primary 6 → JHS 1 → JHS 2 → JHS 3 → 'graduate_basic'
SHS:   Form 1 → Form 2 → Form 3 → 'graduate_shs'
```

Cross-track edge `JHS 3 → Form 1` is **never** produced.

### Per-student processing

Only students matching both of these are touched:

```sql
WHERE students.is_active = TRUE
  AND students.academic_year = :academic_year_label   -- from the closing term
```

Then per-student:

1. `form` NULL/empty → unchanged.
2. `find_class_level(db, form)` can't match an configured active level → unchanged.
3. Resolved level maps to a next level → update `student.form` to next level's canonical name. If destination `requires_index_number=True` and student index is empty → collect into `needs_index` report list.
4. Terminal BASIC (JHS 3): set `graduated_basic_at = utcnow()` (if NULL), `is_active = False`. **DO NOT** touch `form`, `academic_year`, or `stream` — historical snapshot left intact.
5. Terminal SHS  (Form 3): set `graduated_shs_at = utcnow()` (if NULL), `is_active = False`. `form`/year/stream left intact for history.

### Promotion return schema

```jsonc
{
  "promoted": 42,
  "graduated_basic": 5,
  "graduated_shs": 3,
  "unchanged": 3,
  "total_processed": 53,
  "needs_index": [
    {"student_id": "…", "full_name": "Efua Darko", "form": "Form 1"}
  ],
  "message": "…"    // only present if no class levels configured at all
}
```

`total_processed = promoted + graduated_basic + graduated_shs + unchanged`.

Closing a term returns this under the `promotion` key along with the serialized
term.

---

## JHS → SHS transition

BASIC and SHS are two separate, non-contiguous promotion ladders. JHS 3 is
ALWAYS an unconditional graduation (`graduated_basic_at` timestamp set). SHS is
NEVER entered automatically — schools that run both tracks must move completed
JHS3 graduates via the explicit admin-only endpoint described below, one record
at a time (or in a batch import).

### Explicit SHS enrollment endpoint

**POST** `/admin/students/{id}/enroll-shs`

Request body:
```json
{
  "academic_year_id": "<uuid of SHS-track year>",
  "class_level_id": "<uuid of Form 1 class level (track=SHS)>",
  "stream": "General Science"
}
```

Eligibility — all must be true or the call returns 422/409:
- `student.graduated_basic_at IS NOT NULL` — student has completed BASIC track.
- `student.graduated_shs_at IS NULL` — not already an SHS graduate.
- `student.is_active = False` — currently inactive (BASIC-graduated state).
- `academic_year_id` must resolve to an `AcademicYear` with `track = SHS`.
- `class_level_id` must resolve to a `ClassLevel` with `track = SHS` and
  canonical name `"Form 1"`.

Effect on success (200):
- Re-activates the student: `is_active = True`.
- Sets `form = "Form 1"` (the resolved class level's canonical name).
- Sets `academic_year = year.label` (denormalized copy of target year label).
- Sets `stream = <body.stream>`.
- `graduated_basic_at` is **left untouched** (write-once permanent record of
  BASIC completion).
- `graduated_shs_at` remains `NULL` until eventual Form 3 promotion.

### Form 1–3 ⇄ JHS 1–3 one-time migration script

Use
[app/api/scripts/migrate_form_to_jhs.py](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/api/scripts/migrate_form_to_jhs.py)
if you imported historical data where "Form 1/2/3" was used for the JHS levels
and you now want to reserve the "Form" names for SHS 1–3:

```bash
python app/api/scripts/migrate_form_to_jhs.py
```

It does, in order:

1. Ensures the canonical KG→JHS 3 levels exist in `class_levels` (correct flags per level).
2. For each active class level matching regex `^Form [123]$`:
   - If a twin `JHS x` already exists → deactivate the `Form x` duplicate.
   - Else → rename the row in place to `JHS x`, fix flags, set `JHS 3 = terminal`.
3. Post-pass: re-apply `requires_stream=False, JHS 3 requires_index=True + is_terminal=True` on any stray JHS rows so they match policy.
4. Iterate every student. If `form` is not canonical, rewrite using `normalize_student_form_name`. If original form matched the `Form [123]` regex, counts under *Students Form to JHS*; everything else under *Students normalized*. Also blanks out `stream` for students whose level doesn't `require_stream`.
5. Prints a migration summary (levels created/renamed/deactivated, students renamed/normalized, streams cleared, total DB students).

This is **idempotent-ish**: running it a second time rewrites nothing, just reports 0 counts (but it still re-enforces the JHS level flags, so it's safe to re-run after any manual edits that messed flags up).

---

## Student validation rules

All create/import/update paths should route through
[`validate_student_fields(...)` in services/student_validation.py](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L36-L80).

It takes a form name + optional index/stream/gender, looks up the configured
ClassLevel, and applies:

| Rule | Source |
|---|---|
| BECE index format (if provided): exactly 10 digits `^\d{10}$` | [L10](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L10) + [L60–68](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L60-L68) |
| If level `requires_index_number=True` → index is MANDATORY | [L57](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L57) |
| If level `requires_stream=True` → programme MANDATORY (free text) | [L58](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L58) + [L70–77](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L70-L77) |
| If level `requires_stream=False` → stream is FORCED to `NULL` to prevent leakage | [L77](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L77) |
| Gender normalizer | [L13–21](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L13-L21) — "Male"/"Boy" → "M", "Female"/"Girl" → "F", else 400 |
| `require_index=False` override allowed for JHS 3 in parent self-reg flows (index may not be in parent's head) | [L52–53](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/services/student_validation.py#L52-L53) |

---

## Migrations

Always use Alembic.

```bash
alembic current            # see where your DB is
alembic heads              # latest revision
alembic upgrade head       # run everything
alembic downgrade -1       # undo last migration
```

Relevant migration revisions for this subsystem:

| Rev | File | What it does to the academic/student/class chain |
|---|---|---|
| `ae791ce8d898` | `alembic/versions/ae791ce8d898_create_tables_from_models.py` | Creates `students`, `parent_student_links`, `class_levels`, `academic_years`, `academic_terms` + `termstatus` enum (PLANNED/ACTIVE/CLOSED). |
| `b2c3d4e5f6a7` | `alembic/versions/b2c3d4e5f6a7_student_gender_and_level_flags.py` | Adds `students.gender VARCHAR(1) NULL`; relaxes `students.index_number` and `students.stream` to NULLABLE; adds `class_levels.requires_index_number` + `requires_stream` booleans. |

Later revisions cover staff permissions, entity soft-delete flags, OTP sessions,
and meeting categories — they don't touch the five tables above.

---

## Testing locally

```bash
# Unit/integration tests
pytest

# Smoke test the full import/promote pipeline with a tiny transient cohort
# (hand-written if desired against a throwaway DB using get_settings override)

# Manual smoke via Swagger UI
uvicorn app.main:app --reload
# 1. POST /admin/auth/login with admin@gmail.com / 123 → grab bearer token
# 2. POST /admin/academic/years { "label": "2025/2026" }                  → copy year_id
# 3. POST /admin/academic/years/{year_id}/terms { "name": "Term 1", … }
# 4. GET  /admin/academic/current                                            → should be that term
# 5. Create some students via POST /admin/students/import or individual POST
# 6. POST /admin/academic/terms/{term_id}/close { "promote_students": true } → inspect promotion summary
```

---

## Celery worker (SMS + scheduled locks)

Procfile declares two dynos. Locally:

```bash
# Terminal 1 — FastAPI
uvicorn app.main:app --reload

# Terminal 2 — Celery (scheduled SMS, meeting reminders, manual-payment lock tasks)
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

Tasks live under [app/workers/](file:///c:/Users/HP/Documents/All%20Repo/PTA-Backend/app/workers/).

---

## Design notes / known quirks for reviewers

Keep these in mind when doing a design review; they're intentional but worth
deliberate approval:

1. **No enrollment history.** `students.form`/`academic_year` are overwritten in place on promotion. If you need per-year enrollment rows, add an `enrollments` table (student_id, year_label, form, stream, promoted_to, graduated_at) and populate it as part of `promote_students_for_year`.
2. **Denormalized `academic_year` VARCHAR everywhere.** Makes reporting trivial but means editing `AcademicYear.label` requires a manual UPDATE across 8+ dependent tables. A DB trigger or an admin endpoint that rewrites references would improve safety.
3. **"Current term" is app-enforced, not DB-enforced.** A partial unique index `CREATE UNIQUE INDEX one_current_term ON academic_terms (is_current) WHERE is_current = TRUE;` (Postgres) would make concurrent `/activate` calls safe and preserve the "at most one current" invariant at the DB layer.
4. **Re-enrollment of Basic graduates into SHS is explicit and requires the `/enroll-shs` endpoint.** There is no automatic transition.
5. **SHS programme/stream is a free text VARCHAR.** Allowed list is hard-coded only in `seed_demo_data.SHS_PROGRAMMES`. Add an enum or a `programmes` table if reporting must strictly bin by programme.
6. **BECE index is only regex-validated app-side.** DB permits NULL or *any* VARCHAR(50). A DB `CHECK (index_number ~ '^\d{10}$')` (plus allow-null) would close that gap for offline writes.
7. **No FK on ParentStudentLink.** Orphans and duplicates are possible today; adding FKs + `UNIQUE(parent_id, student_id)` + `ON DELETE CASCADE` is a recommended hardening pass.
