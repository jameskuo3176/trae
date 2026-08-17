# Weekly review configuration and database recovery

## Review hierarchy

`config/review_hierarchy.yaml` is the source of truth for:

- project owner
- group owner
- modules contained by each group
- module release owner
- relative risk thresholds

The versioned schema is:

```yaml
version: "2"                 # required non-empty string, max 64 characters
timezone: Asia/Shanghai      # optional; no other value is supported
risk_thresholds:             # optional global overlay on built-in defaults
  tns_setup:
    medium_percent: 10
    high_percent: 25
  area_total:
    medium_percent: 5
    high_percent: 10
  utilization:
    medium_percent: 3
    high_percent: 8
projects:
  chip:
    owner: project-owner
    risk_thresholds:         # optional project overlay on global thresholds
      area_total:
        high_percent: 15
    groups:
      compute:
        owner: group-owner
        description: Optional text
        modules:
          cpu:
            release_owner: release-owner
```

Only `tns_setup`, `area_total`, and `utilization` metrics and
`medium_percent`/`high_percent` boundaries are accepted. Values must be finite,
nonnegative numbers and the effective medium boundary must not exceed the high
boundary. Effective thresholds are built-in defaults, then global YAML values,
then the project's values. An omitted or empty `risk_thresholds` remains valid
for compatibility.

Validate before applying:

```bash
python manage.py migrate_global_modules --execute
python manage.py sync_review_hierarchy --check
python manage.py sync_review_hierarchy --apply
```

`--check` validates the complete file and prints the deterministic database diff
without writing. `--apply` validates first and then reconciles in a transaction.
Exactly one mode is required. Invalid YAML/configuration exits nonzero.

For every project named in YAML, apply reconciles its single project owner,
review groups, group owners/descriptions, group-module assignments, and module
release owners. Groups and group links omitted from YAML are removed for those
projects. Projects omitted from YAML, non-owner project memberships, and module
collaborators are preserved. Repeating an unchanged apply produces zero changes
and does not advance the last-applied timestamp.

The sync refuses bad schema types, unsupported threshold names, invalid threshold
ordering, unknown users/projects/modules, duplicate normalized module assignments,
and modules that have not been bridged to `GlobalModule`.

Admins can inspect the read-only status under **管理后台 → 评审层级状态**. It
shows the config path/version/checksum, validation errors, last-applied state,
current database diff, configured ownership, module grouping, and effective
thresholds. The browser cannot edit or apply YAML.

## Weekly review rules

- Timezone: `Asia/Shanghai`
- Window: Monday 00:00 inclusive through the next Monday 00:00 exclusive.
- Every run with `recorded_at` in the window is a weekly candidate, regardless
  of release status.
- When that set is empty, the exact latest upload is exposed as the sole,
  clearly marked `carried_forward_latest_upload` candidate. It is not treated
  as a formal weekly release.
- A release owner (or admin) may explicitly star one uploaded run per
  project/module/week. Historical, out-of-week, wrong-module, and non-latest
  fallback records are rejected.
- Without an explicit selection, the latest uploaded run is used and the UI shows
  a gray implicit star. An explicit selection replaces it with a gold star.
- Risk compares the star with the previous weekly star, falling back to the latest
  earlier release. Missing baselines are `unrated`.
- Project owners freeze the week into an immutable `ReviewSnapshot`. Later uploads
  do not change the frozen review input.
- Once frozen, official star changes for that project/week are rejected. An admin
  or project owner may request a clearly labeled live preview, but it never
  replaces or mutates the authoritative frozen input.

### Storage and API contract

`WeeklyRunSelection` remains in the main database by design. Project, global
module, and user are central identities, while the selected project-local QoR
record is stored as an opaque string ID. The unique
`(project, module, week_start)` key and project-specific legacy-module mapping
prevent collisions between project databases. This avoids unsupported
cross-database foreign keys and preserves existing selections.

`ReviewSnapshot` is project-local and has no foreign key to central identities.
There is one `weekly_review` snapshot per `(project_id, week_start)`. Creation is
idempotent: the first request returns `201` with `created=true`; later requests
return the existing verified snapshot with `200` and `created=false`. There is no
replacement endpoint.

- `GET /api/reviews/weekly?project_id=<id>&week_start=YYYY-MM-DD` returns the
  frozen input when it exists, including `is_frozen`, full checksum, snapshot ID,
  creator, creation time, and schema version.
- `GET ...&live_preview=true` returns `input_mode=live_preview` only for a project
  owner or admin.
- `POST /api/reviews/weekly/star` selects an eligible official candidate and
  returns its source.
- `POST /api/reviews/snapshots` freezes the canonical weekly input.

Frozen JSON includes hierarchy version/checksum, effective thresholds, candidate
and star metric copies, baselines, risk details/reasons, timezone, and week. Its
SHA-256 is computed over canonical compact JSON and verified on every frozen
read. A failed checksum returns `snapshot_integrity_failed` rather than silently
serving data.

### Group and Project review workflow

Review creation uses an explicit-freeze contract. The client must first call
`POST /api/reviews/snapshots`, then include the returned `week_start` when it
creates a Group or Project review. Creation never freezes implicitly. If the
authoritative project/week snapshot is absent, the API returns HTTP `409` with
`code=review_snapshot_required`; a checksum failure returns
`snapshot_integrity_failed`.

Each new review stores the project-local snapshot ID as an opaque integer plus
its checksum, Shanghai week, snapshot schema version, hierarchy config version,
and an immutable copy of the canonical frozen JSON. There is deliberately no
cross-database foreign key. Detail/history responses expose
`snapshot_provenance` and verify both the stored copy and the authoritative
snapshot. Later uploads and star changes cannot alter that historical input.
Rows created before this contract remain readable and are labeled
`Legacy / live-unbound`.

The public API consistently calls `SubsystemReview` a **Project Review**:

- `GET/POST /api/reviews/group` and `/api/reviews/project`
- `GET/PUT/DELETE /api/reviews/<type>/<id>?project_id=<id>`
- `POST /api/reviews/<type>/<id>/submit`
- `POST /api/reviews/<type>/<id>/review`

Local review IDs can collide across project databases, so every detail and
workflow request requires `project_id`. Backend capability fields are the UI's
sole authority: `can_edit`, `can_delete`, `can_submit`, and `can_review`, plus
weekly `can_freeze`, `can_create_project_review`, per-group
`can_create_review`, and per-module `can_select_star`.

Permissions follow release owner → group owner → project owner/admin:

- release owner/admin selects the official module star before freeze;
- project owner/admin freezes the project week;
- group owner/admin creates a Group review;
- project owner/admin creates a Project review;
- project owner/admin decides submitted reviews.

A non-admin cannot approve their own Group review. Global admins retain the
explicitly requested Group self-approval exception. A Project review is final
project-owner signoff, so a project owner or admin may approve their own
Project review; this avoids a dead end for projects with one owner.

Draft and rejected reviews may be edited, deleted, and submitted. A rejected
review's next submission records `resubmitted_at` and increments
`submission_count`; prior reviewer identity, timestamp, and comment are
preserved as rework evidence. Submitted and approved content is immutable.

Migration `0008_review_snapshot_binding` adds nullable provenance fields so
legacy rows remain valid. Apply it through the normal deployment migration
step; no production migration is run as part of source delivery.

`ReviewSnapshot` means frozen review input. `DataSnapshot` remains an operational
rollback artifact. `/api/reviews/snapshot/<id>/upload` manages review attachments
and does not alter the frozen JSON or its checksum.

## Client-side gvim protocol

On each Windows review workstation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/register_gvim_protocol.ps1
```

Source paths in record detail, violations, Review module detail, and annotation
evidence use `SourceFileLink` → `gvim://open?path=...&line=...`. The registered
Python handler (`scripts/gvim_protocol_handler.py`) decodes the URL and launches
gvim with an argument array and `shell=False` (no shell concatenation).

If the protocol is not installed, use the inline **复制** control next to the
path. The legacy `POST /api/tools/source-files/gvim` endpoint returns HTTP 410
and is deprecated; do not rely on server-launched desktop editors.

## Backup and restore

Create and verify backups from the Admin Snapshot & Backup panel or CLI. Each
current-format archive contains `manifest.json` with:

- file sizes and SHA-256 checksums
- database inventory (main + project `*_syn_qor.db` / legacy `qor_p_<id>.db`)
- schema metadata: `backup_format_version`, applied Django migration names per app

Recurring startup backups and automatic backups before `/dbadmin` writes are
disabled by default to avoid uncontrolled storage growth. Set
`AUTO_BACKUP_ENABLED=1` only when this behavior is required. Manual backups and
the safety backups attached to explicit migrate/restore commands remain
available.

Always validate first:

```bash
python manage.py restore_backup "data/backups/qor_recorder_....zip" --dry-run
python manage.py restore_backup "data/backups/qor_recorder_....zip" --verify
```

Apply only during a maintenance window with all writers stopped:

```bash
python manage.py restore_backup "data/backups/qor_recorder_....zip" --verify --apply
```

The apply path:

1. refuses Mongo/hybrid archives and non-`orm` persistence modes
2. creates a pre-restore backup
3. acquires an exclusive maintenance lock (`backups/qor_restore.lock`)
4. closes Django database connections
5. stages, integrity-checks, and atomically replaces SQLite files (including
   `*_syn_qor.db`)
6. rolls back all touched databases if any replace fails

Restart all application workers after completion. The Admin UI shows restore
commands, verification status, and manifest schema fields; it never overwrites
databases inside a web request.

## Project database names and raw-data administration

Project SQLite files use `<project>_syn_qor.db`. Preview and apply a legacy
`qor_p_<id>.db` migration with:

```bash
python manage.py migrate_project_db_names
python manage.py migrate_project_db_names --apply
```

The apply command checkpoints SQLite WAL files, creates a verified backup, renames
the files, and updates `Project.db_path`. Databases without a matching `Project`
row are intentionally left unchanged.

Set `ENABLE_DB_ADMIN=1`, restart Django, then open `/dbadmin`. Only application
users with the `admin` role can access it. The page can switch between the main
database and each project database, browse schemas and rows, run read-only
`SELECT` queries, and edit or delete rows by primary key. Raw edits bypass domain
validation, so create a backup before changing production data.
