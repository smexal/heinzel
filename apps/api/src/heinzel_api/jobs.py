"""Scheduled jobs of modules (reminders, retention), run inside the API process.

Every API process runs a small scheduler (off in tests). A job runs at most once at a time
across all processes: it takes a Postgres advisory lock and skips the round when another
process holds it. `heinzel run-jobs` runs them once from the command line (e.g. for cron or
to try a job). Jobs must be idempotent: a round can repeat after a crash.
"""

import asyncio
import logging
import time
import zlib

from sqlalchemy import text

from heinzel_api.db import get_engine
from heinzel_api.modules import Job, JobContext, ModuleHost

log = logging.getLogger(__name__)
TICK_SECONDS = 30


def all_jobs(hosts: dict[str, ModuleHost]) -> list[Job]:
    return [job for host in hosts.values() for job in host.jobs]


def run_once(job: Job, ctx: JobContext, url: str) -> bool:
    """Run the job unless another process is running it. True when it ran."""
    key = zlib.crc32(job.name.encode())
    with get_engine(url).connect() as conn:
        if not conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": key}).scalar():
            return False
        try:
            job.run(ctx)
            return True
        except Exception:
            log.exception("job %s failed", job.name)
            return False
        finally:
            conn.execute(text("select pg_advisory_unlock(:k)"), {"k": key})
            conn.commit()


async def scheduler(app) -> None:
    """Background task started by the API lifespan."""
    jobs = all_jobs(app.state.modules)
    last: dict[str, float] = {}
    while True:
        now = time.monotonic()
        for job in jobs:
            if now - last.get(job.name, -1e12) < job.every_seconds:
                continue
            last[job.name] = now
            ctx = job_context(app.state)
            await asyncio.to_thread(run_once, job, ctx, app.state.settings.database_url)
        await asyncio.sleep(TICK_SECONDS)


def job_context(state) -> JobContext:
    return JobContext(
        db=state.db,
        tenants=state.registry.all(),
        manifests=state.manifests,
        mailer=state.mailer,
        storage=state.storage,
        settings=state.settings,
    )
