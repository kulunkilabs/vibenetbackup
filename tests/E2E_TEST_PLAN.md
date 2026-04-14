# VIBENetBackup — E2E Test Plan

## Scope

Full HTTP request → business logic → SQLite DB → response.
No mocking of the DB layer. Mock only actual network calls to devices
(SSH / Netmiko / pfSense API) since CI has no real routers.

---

## Shared Test Infrastructure

### New fixtures (additions to `tests/conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `app_client` | function | TestClient backed by a real temp SQLite file (not `:memory:`) so state persists across multiple requests within one test |
| `auth_headers` | session | `{"Authorization": "Basic ..."}` derived from `settings.AUTH_USERNAME` / `AUTH_PASSWORD` |
| `mock_backup_engine` | function | Patches `app.modules.backup_service.get_engine` to return a fake engine that returns a config string without touching the network |
| `tmp_backup_dir` | function | `tmp_path`-based local directory injected as the destination path |

### Conventions

- Each test creates its own data — no shared state between tests.
- DB is a real file in `tmp_path`; deleted after each test.
- All assertions check both the HTTP response **and** the DB row directly.

---

## Test Files

### 1. `tests/test_e2e_credentials.py`

| # | Test name | Flow | Assert |
|---|-----------|------|--------|
| 1 | `test_create_credential` | `POST /api/v1/credentials` with name + password | 201; row exists in DB |
| 2 | `test_password_encrypted_at_rest` | Create credential → query DB directly | `password_encrypted != plaintext` |
| 3 | `test_update_credential` | Create → `PUT /api/v1/credentials/{id}` with new name | 200; DB row updated |
| 4 | `test_delete_credential_unlinks_device` | Create cred + device → `DELETE /api/v1/credentials/{id}` | 204; `devices.credential_id IS NULL` |
| 5 | `test_password_only_credential` | Create with `username=null` | 201; accepted (v1.6.1 nullable username fix) |
| 6 | `test_duplicate_name_rejected` | Create same name twice | 409 or 422 on second request |

---

### 2. `tests/test_e2e_devices.py`

| # | Test name | Flow | Assert |
|---|-----------|------|--------|
| 1 | `test_create_device` | `POST /api/v1/devices` | 201; persisted in DB |
| 2 | `test_device_with_credential` | Create cred + device with `credential_id` → `GET /api/v1/devices/{id}` | `credential_id` present in response |
| 3 | `test_delete_device_cascades_backups` | Create device + insert backup row → `POST /devices/{id}/delete` | Device gone; backup row gone |
| 4 | `test_list_devices` | Create 3 devices → `GET /api/v1/devices` | Response contains all 3 |
| 5 | `test_update_device` | Create → `PUT /api/v1/devices/{id}` with new hostname | DB row reflects new hostname |
| 6 | `test_device_group_assigned` | Create device with `group="core"` → list devices | Group field returned correctly |

---

### 3. `tests/test_e2e_backup_trigger.py` ⭐ Priority

| # | Test name | Flow | Assert |
|---|-----------|------|--------|
| 1 | `test_backup_no_credential_fails` | Create device (no cred) → `POST /backups/{id}/now` | Backup row `status=failed`; `error_message` set |
| 2 | `test_backup_success` | Create cred + device → mock engine returns config → `POST /backups/{id}/now` | Backup row `status=success`; `config_hash` set |
| 3 | `test_backup_engine_exception_fails` | Mock engine raises exception → trigger | Backup row `status=failed`; error captured |
| 4 | `test_backup_unchanged_on_same_config` | Trigger twice with identical config → second backup | Second row `status=unchanged`; same `config_hash` |
| 5 | `test_backup_creates_file_local_dest` | Add local destination → trigger → mock engine | File exists on disk at destination path |
| 6 | `test_api_trigger_multiple_devices` | Create 3 devices → `POST /api/v1/backups/trigger` with device IDs | 3 backup rows created, one per device |
| 7 | `test_backup_detail_accessible` | Trigger backup → `GET /backups/{backup_id}` | 200; backup detail page renders |
| 8 | `test_backup_diff_on_second_run` | Two backups with different configs → `GET /backups/{id}` | Diff section present in response |

---

### 4. `tests/test_e2e_schedules.py`

| # | Test name | Flow | Assert |
|---|-----------|------|--------|
| 1 | `test_create_schedule` | `POST /api/v1/schedules` with cron expression | 201; row in DB; APScheduler job registered |
| 2 | `test_manual_run_schedule` | Create schedule + devices → `POST /jobs/{id}/run` | `job_runs` row created; backup rows present |
| 3 | `test_delete_schedule_removes_job` | Create → `POST /jobs/{id}/delete` | Row gone; APScheduler has no job for that ID |
| 4 | `test_invalid_cron_rejected` | `POST /jobs/add` with `cron="not-valid"` | Form re-rendered with error; no row created |
| 5 | `test_job_history_lists_runs` | Run schedule twice → `GET /jobs/history` | Both `job_run` rows visible |

---

### 5. `tests/test_e2e_destinations.py`

| # | Test name | Flow | Assert |
|---|-----------|------|--------|
| 1 | `test_create_local_destination` | `POST /api/v1/destinations` type=local | 201; row in DB |
| 2 | `test_backup_writes_to_local_path` | Local dest + device → mock engine → trigger | File written to `tmp_backup_dir` |
| 3 | `test_retention_sweep_prunes_daily` | Insert 20 daily backup records (with files) → `POST /api/v1/retention/sweep` | Only 14 kept (default daily=14); older rows pruned |
| 4 | `test_delete_destination` | Create → `POST /destinations/{id}/delete` | Row gone |
| 5 | `test_update_destination_preserves_secret` | Create with token → update name only | Token still decryptable after update |

---

### 6. `tests/test_e2e_groups.py`

| # | Test name | Flow | Assert |
|---|-----------|------|--------|
| 1 | `test_create_group` | `POST /groups/add` with name + destination | Row in DB |
| 2 | `test_group_backup_trigger` | Create group with 2 devices → trigger via group | Both devices get backup rows |
| 3 | `test_delete_group` | Create → `POST /groups/{id}/delete` | Row gone; devices still exist (group field nulled or unchanged) |

---

### 7. `tests/test_e2e_dashboard.py`

| # | Test name | Flow | Assert |
|---|-----------|------|--------|
| 1 | `test_dashboard_returns_200` | `GET /` with auth | 200; HTML response |
| 2 | `test_dashboard_unauthenticated_redirects` | `GET /` without auth | 401 or redirect to login |
| 3 | `test_dashboard_reflects_db_state` | Create 3 devices + 2 backups → `GET /` | Response body contains correct counts |

---

## Priority Order

1. **`test_e2e_backup_trigger.py`** — core feature; area where runtime bugs just surfaced
2. **`test_e2e_credentials.py`** — foundational; every backup depends on credentials
3. **`test_e2e_devices.py`** — core data model
4. **`test_e2e_destinations.py`** — covers retention logic
5. **`test_e2e_schedules.py`** — covers APScheduler integration
6. **`test_e2e_groups.py`** — covers group profile feature
7. **`test_e2e_dashboard.py`** — smoke tests

---

## Out of Scope

- Real device connectivity (Netmiko, SSH, pfSense API, SMB, Git push) — mocked at engine layer
- Browser rendering / JavaScript behaviour — no Playwright/Selenium
- Performance / load testing
