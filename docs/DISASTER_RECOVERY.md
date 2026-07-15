# Disaster recovery

MySQL backups and restore drills are the authoritative recovery mechanism. IT owns schedules, encryption, retention,
off-site copies, access, monitoring, and restore approval. Record recovery point and recovery time objectives before
staging or production approval.

The desktop API cache is disposable and must be rebuilt; it is not a database backup. Source control is not an
operational-data archive. Preserve real migration/rehearsal evidence outside the repository in access-controlled
storage.

Test restore into an isolated environment, migrate to the expected Alembic head, verify constraints and release
registration, then run API/UI smoke checks. Never test downgrade or destructive restore against the live development or
production database.
