"""Export and import of all data: every tenant's database rows and stored files.

An export is one .tar.gz:

    manifest.json        format, versions, migration state, key check, tables and files
                         with row counts and SHA-256 checksums
    db/<schema>.<table>  rows in PostgreSQL COPY text format, one file per table
    files/<storage key>  the stored files of all live attachments

The export runs in one read-only, repeatable-read transaction, so it is consistent while the
portal keeps running (usable as a backup). Sign-in sessions are left out: after an import
everybody signs in again.

The import replaces everything in the target database. The target must be migrated to the
same versions as the source (same code). Secrets encrypted with HEINZEL_SECRET_KEY (TOTP seeds,
SMTP password) are re-encrypted when the target uses a different key: automatically when the
source ran with the development key, otherwise with --source-key.
"""

import hashlib
import hmac
import io
import json
import os
import re
import socket
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

from heinzel_api import __version__, crypto, migrate
from heinzel_api.files import Storage

FORMAT = 1
EXCLUDED = {"core.session"}  # sign-ins do not move
DEV_KEY_PREFIX = "dev-only"
SCHEMAS_SQL = "n.nspname = 'core' or n.nspname like 'mod\\_%'"
SECRETS = (("core", "app_user", "mfa_secret", "totp"),)  # plus the SMTP password in settings


class TransferError(Exception):
    pass


def _dsn(url: str) -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


def key_check(secret_key: str) -> str:
    """Identifies the encryption key without revealing it."""
    return hmac.new(secret_key.encode(), b"heinzel-export-key-check", "sha256").hexdigest()[:24]


# --- database structure ------------------------------------------------------------------------


def _tables(conn: psycopg.Connection) -> list[dict]:
    """Tables of the core and modules in foreign-key order (referenced tables first)."""
    rows = conn.execute(
        f"""
        select n.nspname, c.relname, c.relforcerowsecurity,
               exists (select 1 from pg_attribute a where a.attrelid = c.oid
                       and a.attname = 'tenant_id' and not a.attisdropped)
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'r' and ({SCHEMAS_SQL}) and c.relname <> 'alembic_version'
        order by n.nspname, c.relname
        """
    ).fetchall()
    tables = {
        f"{s}.{t}": {"name": f"{s}.{t}", "schema": s, "table": t, "rls": rls, "tenant": ten}
        for s, t, rls, ten in rows
    }
    edges = conn.execute(
        f"""
        select cn.nspname || '.' || c.relname, fn.nspname || '.' || f.relname
        from pg_constraint k
        join pg_class c on c.oid = k.conrelid join pg_namespace cn on cn.oid = c.relnamespace
        join pg_class f on f.oid = k.confrelid join pg_namespace fn on fn.oid = f.relnamespace
        where k.contype = 'f' and ({SCHEMAS_SQL.replace("n.", "cn.")})
        """
    ).fetchall()
    deps: dict[str, set[str]] = {name: set() for name in tables}
    for child, parent in edges:
        if child in deps and parent in tables and child != parent:
            deps[child].add(parent)
    ordered: list[str] = []
    while deps:
        ready = sorted(n for n, d in deps.items() if not d - set(ordered))
        if not ready:
            raise TransferError(f"Fremdschlüssel im Kreis zwischen {sorted(deps)}")
        for n in ready:
            ordered.append(n)
            del deps[n]
    for name in ordered:
        s, t = tables[name]["schema"], tables[name]["table"]
        tables[name]["columns"] = [
            r[0]
            for r in conn.execute(
                """select attname from pg_attribute
                   where attrelid = %s::regclass and attnum > 0 and not attisdropped
                   order by attnum""",
                (f"{s}.{t}",),
            )
        ]
    return [tables[n] for n in ordered]


def _migrations(conn: psycopg.Connection, modules_dir: Path) -> dict[str, str | None]:
    parts = {"core": "core"} | {
        mid: migrate.module_schema(mid) for mid, _ in migrate.module_migration_dirs(modules_dir)
    }
    out = {}
    for name, schema in parts.items():
        exists = conn.execute("select to_regclass(%s)", (f"{schema}.alembic_version",)).fetchone()[
            0
        ]
        out[name] = (
            conn.execute(
                sql.SQL("select version_num from {}.alembic_version").format(sql.Identifier(schema))
            ).fetchone()[0]
            if exists
            else None
        )
    return out


# --- export -----------------------------------------------------------------------------------


def export(url: str, secret_key: str, storage: Storage, modules_dir: Path, out: Path) -> dict:
    """Write the export to `out` (a file, or a directory for a dated file name). Returns the
    manifest."""
    if out.is_dir() or str(out).endswith(("/", os.sep)):
        out.mkdir(parents=True, exist_ok=True)
        out = out / f"heinzel-export-{datetime.now(UTC):%Y%m%d-%H%M%S}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "format": FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "heinzel_version": __version__,
        "source_host": socket.gethostname(),
        "key_check": key_check(secret_key),
        "dev_key": secret_key.startswith(DEV_KEY_PREFIX),
        "excluded": sorted(EXCLUDED),
        "tables": [],
        "files": [],
        "problems": [],
    }
    tmp = out.with_suffix(out.suffix + ".part")
    with tarfile.open(tmp, "w:gz") as tar:
        with psycopg.connect(_dsn(url)) as conn:
            conn.execute("begin isolation level repeatable read read only")
            manifest["migrations"] = _migrations(conn, modules_dir)
            tables = _tables(conn)
            tenant_ids = [r[0] for r in conn.execute("select id from core.tenant order by slug")]
            for t in tables:
                if t["name"] in EXCLUDED:
                    continue
                data = _copy_out(conn, t, tenant_ids)
                path = f"db/{t['name']}"
                _add(tar, path, data)
                manifest["tables"].append(
                    {
                        "name": t["name"],
                        "columns": t["columns"],
                        "rows": data.count(b"\n"),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "file": path,
                    }
                )
            # The files of live attachments, as listed in the same snapshot.
            keys = []
            for tid in tenant_ids:
                conn.execute("select set_config('app.tenant_id', %s, true)", (str(tid),))
                keys += conn.execute(
                    "select storage_key, sha256, size from core.attachment where deleted_at is null"
                ).fetchall()
            conn.execute("rollback")
        for key, sha, size in keys:
            data = storage.get(key) if storage.exists(key) else None
            if data is None or hashlib.sha256(data).hexdigest() != sha:
                manifest["problems"].append(
                    f"Datei {key} fehlt oder ist beschädigt, nicht exportiert"
                )
                continue
            _add(tar, f"files/{key}", data)
            manifest["files"].append({"key": key, "sha256": sha, "size": size})
        _add(tar, "manifest.json", json.dumps(manifest, indent=2).encode())
    tmp.replace(out)
    manifest["path"] = str(out)
    return manifest


def _copy_out(conn: psycopg.Connection, t: dict, tenant_ids: list) -> bytes:
    """All rows of a table. Tables under forced row level security are read tenant by tenant
    (the owner role is subject to the policies, too)."""
    ident = sql.Identifier(t["schema"], t["table"])
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in t["columns"])
    query = sql.SQL("copy (select {} from {}) to stdout").format(cols, ident)
    data = bytearray()
    for tid in tenant_ids if (t["rls"] and t["tenant"]) else [None]:
        if tid is not None:
            conn.execute("select set_config('app.tenant_id', %s, true)", (str(tid),))
        with conn.cursor().copy(query) as copy:
            for chunk in copy:
                data += chunk
    return bytes(data)


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(datetime.now(UTC).timestamp())
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


# --- import -----------------------------------------------------------------------------------


def read_manifest(path: Path) -> dict:
    with tarfile.open(path, "r:gz") as tar:
        try:
            return json.loads(tar.extractfile("manifest.json").read())
        except KeyError as e:
            raise TransferError("keine manifest.json: kein Heinzel-Export") from e


def import_(
    path: Path,
    url: str,
    secret_key: str,
    storage: Storage,
    modules_dir: Path,
    *,
    replace: bool = False,
    source_key: str | None = None,
) -> dict:
    """Replace all data in the target with the export. Returns a summary."""
    with tarfile.open(path, "r:gz") as tar:
        try:
            manifest = json.loads(tar.extractfile("manifest.json").read())
        except KeyError as e:
            raise TransferError("keine manifest.json: kein Heinzel-Export") from e
        if manifest.get("format") != FORMAT:
            raise TransferError(f"Exportformat {manifest.get('format')} wird nicht unterstützt")

        # Which key decrypts the secrets in the export?
        if key_check(secret_key) == manifest["key_check"]:
            old_key = None
        elif source_key:
            if key_check(source_key) != manifest["key_check"]:
                raise TransferError(
                    "--source-key ist nicht der Schlüssel, mit dem exportiert wurde"
                )
            old_key = source_key
        elif manifest.get("dev_key"):
            from heinzel_api.config import Settings

            old_key = Settings.model_fields["secret_key"].default
        else:
            raise TransferError(
                "der Export stammt von einer Installation mit anderem HEINZEL_SECRET_KEY: "
                "diesen mit --source-key angeben, damit 2FA und SMTP-Passwort lesbar bleiben"
            )

        # Check every file before touching the database.
        members = {m.name: m for m in tar.getmembers()}
        blobs: dict[str, bytes] = {}
        for t in manifest["tables"]:
            data = tar.extractfile(members[t["file"]]).read()
            if hashlib.sha256(data).hexdigest() != t["sha256"]:
                raise TransferError(f"{t['file']} ist beschädigt (Prüfsumme)")
            blobs[t["name"]] = data
        for f in manifest["files"]:
            m = members.get(f"files/{f['key']}")
            if m is None or m.size != f["size"]:
                raise TransferError(f"Datei {f['key']} fehlt oder ist beschädigt")

        with psycopg.connect(_dsn(url)) as conn:
            target = _migrations(conn, modules_dir)
            if target != manifest["migrations"]:
                raise TransferError(
                    f"Datenbankstand passt nicht: Export {manifest['migrations']}, hier "
                    f"{target}. Dieselbe Heinzel-Version verwenden und zuerst `heinzel migrate`."
                )
            tables = _tables(conn)
            names = {t["name"] for t in tables}
            unknown = [t["name"] for t in manifest["tables"] if t["name"] not in names]
            if unknown:
                raise TransferError(f"Tabellen fehlen hier: {unknown}")
            with conn.transaction():
                for t in tables:
                    ident = sql.Identifier(t["schema"], t["table"])
                    conn.execute(
                        sql.SQL("alter table {} no force row level security").format(ident)
                    )
                    conn.execute(sql.SQL("alter table {} disable trigger user").format(ident))
                users = conn.execute("select count(*) from core.app_user").fetchone()[0]
                if users and not replace:
                    raise TransferError(
                        f"hier gibt es schon {users} Benutzer: mit --replace überschreiben"
                    )
                conn.execute(
                    sql.SQL("truncate {} cascade").format(
                        sql.SQL(", ").join(sql.Identifier(t["schema"], t["table"]) for t in tables)
                    )
                )
                counts = {}
                for t in manifest["tables"]:
                    schema, table = t["name"].split(".", 1)
                    cols = sql.SQL(", ").join(sql.Identifier(c) for c in t["columns"])
                    query = sql.SQL("copy {} ({}) from stdin").format(
                        sql.Identifier(schema, table), cols
                    )
                    with conn.cursor().copy(query) as copy:
                        copy.write(blobs[t["name"]])
                    counts[t["name"]] = t["rows"]
                _reset_sequences(conn, tables)
                if old_key is not None:
                    _rekey(conn, old_key, secret_key)
                for t in tables:
                    ident = sql.Identifier(t["schema"], t["table"])
                    conn.execute(sql.SQL("alter table {} enable trigger user").format(ident))
                    if t["rls"]:
                        conn.execute(
                            sql.SQL("alter table {} force row level security").format(ident)
                        )

        # Files last: the database already points at them; put() is idempotent.
        for f in manifest["files"]:
            data = tar.extractfile(members[f"files/{f['key']}"]).read()
            if hashlib.sha256(data).hexdigest() != f["sha256"]:
                raise TransferError(f"Datei {f['key']} ist beschädigt (Prüfsumme)")
            storage.put(f["key"], data)
    return {
        "tables": len(counts),
        "rows": sum(counts.values()),
        "files": len(manifest["files"]),
        "rekeyed": old_key is not None,
        "created_at": manifest["created_at"],
    }


def _reset_sequences(conn: psycopg.Connection, tables: list[dict]) -> None:
    for t in tables:
        for col in t["columns"]:
            seq = conn.execute(
                "select pg_get_serial_sequence(%s, %s)", (f"{t['schema']}.{t['table']}", col)
            ).fetchone()[0]
            if seq:
                conn.execute(
                    sql.SQL(
                        "select setval(%s, coalesce((select max({}) from {}), 0) + 1, false)"
                    ).format(sql.Identifier(col), sql.Identifier(t["schema"], t["table"])),
                    (seq,),
                )


def _rekey(conn: psycopg.Connection, old: str, new: str) -> None:
    """Re-encrypt secrets from the export's key to this installation's key."""
    for schema, table, column, purpose in SECRETS:
        rows = conn.execute(
            sql.SQL("select id, {} from {} where {} is not null").format(
                sql.Identifier(column), sql.Identifier(schema, table), sql.Identifier(column)
            )
        ).fetchall()
        for row_id, value in rows:
            plain = crypto.decrypt(old, purpose, value)
            conn.execute(
                sql.SQL("update {} set {} = %s where id = %s").format(
                    sql.Identifier(schema, table), sql.Identifier(column)
                ),
                (crypto.encrypt(new, purpose, plain), row_id),
            )
    for tenant_id, config in conn.execute(
        "select tenant_id, config from core.tenant_settings"
    ).fetchall():
        smtp = ((config or {}).get("email") or {}).get("smtp") or {}
        if smtp.get("password_enc"):
            plain = crypto.decrypt(old, "smtp", smtp["password_enc"])
            smtp["password_enc"] = crypto.encrypt(new, "smtp", plain)
            conn.execute(
                "update core.tenant_settings set config = %s where tenant_id = %s",
                (psycopg.types.json.Jsonb(config), tenant_id),
            )
