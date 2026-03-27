# REST API Reference

All API endpoints are under `/api/v1/` and require HTTP Basic Auth.

## Authentication

```bash
AUTH="admin:your-password"
```

---

## Devices

```bash
# List all devices
curl -u "$AUTH" http://localhost:5005/api/v1/devices

# Create device
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/devices \
  -H "Content-Type: application/json" \
  -d '{
    "hostname": "switch01",
    "ip_address": "192.0.2.1",
    "device_type": "cisco_ios",
    "credential_id": 1
  }'

# Get device
curl -u "$AUTH" http://localhost:5005/api/v1/devices/1

# Update device
curl -u "$AUTH" -X PUT http://localhost:5005/api/v1/devices/1 \
  -H "Content-Type: application/json" \
  -d '{"hostname": "switch01-updated"}'

# Delete device
curl -u "$AUTH" -X DELETE http://localhost:5005/api/v1/devices/1
```

---

## Backups

```bash
# List all backups
curl -u "$AUTH" http://localhost:5005/api/v1/backups

# Trigger backup for specific devices
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/backups/trigger \
  -H "Content-Type: application/json" \
  -d '{"device_ids": [1, 2, 3]}'

# Get backup details
curl -u "$AUTH" http://localhost:5005/api/v1/backups/1
```

---

## Credentials

```bash
# List credentials
curl -u "$AUTH" http://localhost:5005/api/v1/credentials

# Create credential
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ssh-admin",
    "username": "admin",
    "password": "secret"
  }'
```

---

## Schedules

```bash
# List schedules
curl -u "$AUTH" http://localhost:5005/api/v1/schedules

# Create schedule (cron-based)
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Nightly-2AM",
    "cron_expression": "0 2 * * *",
    "device_ids": [1, 2, 3],
    "destination_ids": [1]
  }'
```

---

## Destinations

```bash
# List destinations
curl -u "$AUTH" http://localhost:5005/api/v1/destinations

# Create destination
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/destinations \
  -H "Content-Type: application/json" \
  -d '{
    "name": "local-backups",
    "dest_type": "local",
    "config_json": {"path": "./backups"}
  }'
```

---

## Retention

```bash
# Run retention sweep (applies GFS policies)
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/retention/sweep
```

---

## Maintenance

```bash
# Run full DB maintenance (retention sweep, stale cleanup, history purge, VACUUM)
curl -u "$AUTH" -X POST http://localhost:5005/api/v1/maintenance/run
```

This runs automatically daily at 3:30 AM. Use this endpoint to trigger it manually.

---

## Job History

```bash
# List job runs
curl -u "$AUTH" http://localhost:5005/api/v1/jobs/history

# Get specific run details
curl -u "$AUTH" http://localhost:5005/api/v1/jobs/runs/1
```
