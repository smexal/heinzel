# Heinzel in production

One server, everything in Docker (`compose.prod.yml`): Postgres, Valkey, ClamAV, the API,
the web server, Caddy for HTTPS and a backup container. You operate it with `deploy/heinzel.sh`.

## 1. Server

- Linux with Docker Engine and the Compose plugin (e.g. Ubuntu 24.04, `apt install docker.io docker-compose-v2`)
- 2 vCPU, **4 GB RAM** (ClamAV alone needs 1.5 to 2 GB), 40 GB disk
- Firewall: 22, 80 and 443 (TCP, plus 443/UDP for HTTP/3)
- DNS: an A (and AAAA) record for the portal's name, e.g. `heinzel.schmelzi.ch`, pointing to the server.
  The name must also be in `tenants/<slug>/tenant.json` under `domains` (Schmelzi: already there).

## 2. Install

```sh
git clone https://github.com/smexal/heinzel.git /opt/heinzel   # private repo: deploy key or token
cd /opt/heinzel
cp deploy/.env.example deploy/.env
nano deploy/.env        # domain, e-mail for Let's Encrypt, three secrets (see the file)
deploy/heinzel.sh up
deploy/heinzel.sh logs proxy    # wait for "certificate obtained", then open https://<domain>
```

The first start builds the images, runs the migrations and registers the tenants from
`tenants/`. ClamAV needs a few minutes to load its signatures; until then uploads are refused.

## 3. Move the data from your PC

On the PC, with `pnpm dev` running (the database must be up):

```powershell
pnpm heinzel export          # writes var\exports\heinzel-export-<date>.tar.gz
scp var\exports\heinzel-export-<date>.tar.gz root@<server>:/opt/heinzel/
```

On the server:

```sh
deploy/heinzel.sh import heinzel-export-<date>.tar.gz
```

The import replaces all data: users and their 2FA, roles, settings, logos, modules, tasks,
Mein Eingang, the audit log and all files. Everybody signs in again with their usual password
and authenticator. Secrets are re-encrypted with the server's `HEINZEL_SECRET_KEY` (automatic
for an export made with the development key; otherwise add `--source-key <old key>`).

After the import, in Einstellungen › E-Mail: set the real SMTP server. Dev used Mailpit
(`localhost:1025`), which does not exist on the server.

Both sides must run the same Heinzel version (same commit): the import checks that the database
versions match. Importing into a portal that already has users needs `--replace`.

Without data to import, create the first administrator instead:

```sh
deploy/heinzel.sh cli create-admin --tenant schmelzi --email you@schmelzi.ch --name "Your Name"
```

## 4. Backups

The `backup` container writes a full export every day into `/opt/heinzel/backups` and keeps the
newest `BACKUP_KEEP` (default 14). `deploy/heinzel.sh export` makes one right away. Copy them off
the server regularly (e.g. `rsync` to a NAS); an export is also the way back: `import` it.

Keep `deploy/.env` (above all `HEINZEL_SECRET_KEY`) in a password manager. Without the key the
2FA seeds and the SMTP password in a backup cannot be read.

## 5. Updates

```sh
deploy/heinzel.sh export     # to be safe
deploy/heinzel.sh update     # git pull, rebuild, migrations run before the API starts
```

## Commands

| Command | |
| --- | --- |
| `deploy/heinzel.sh up` | build and start, or apply changes to `deploy/.env` |
| `deploy/heinzel.sh update` | `git pull`, then `up` |
| `deploy/heinzel.sh ps` / `logs [service]` | state, logs |
| `deploy/heinzel.sh export` | full export into `backups/` now |
| `deploy/heinzel.sh import FILE [--replace] [--source-key KEY]` | replace all data with an export |
| `deploy/heinzel.sh cli ...` | any `heinzel` command (`verify-audit`, `files verify`, `run-jobs`, ...) |
| `deploy/heinzel.sh down` | stop; the data stays in the Docker volumes |
