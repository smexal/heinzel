"""Outgoing e-mail through the tenant's SMTP settings (tenant.json → email).

Mail is sent after the transaction that caused it has committed. Failures are logged and
reported to the caller; they never roll back the change. A transactional outbox with
retries replaces this once the worker exists (concept: Jobs and events).
"""

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from heinzel_api.tenants import TenantConfig

log = logging.getLogger(__name__)


@dataclass
class Mail:
    to: str
    subject: str
    text: str


class Mailer:
    def send(self, tenant: TenantConfig, mail: Mail) -> bool:
        raise NotImplementedError


def _password(ref: str | None) -> str | None:
    """Secrets are referenced, never stored in tenant.json: `env:VARIABLE_NAME`."""
    if not ref:
        return None
    if ref.startswith("env:"):
        return os.environ.get(ref.removeprefix("env:"))
    raise ValueError(f"unsupported password_ref '{ref}'")


class SmtpMailer(Mailer):
    def send(self, tenant: TenantConfig, mail: Mail) -> bool:
        cfg = (tenant.model_extra or {}).get("email") or {}
        smtp = cfg.get("smtp") or {}
        msg = EmailMessage()
        msg["From"] = formataddr((cfg.get("from_name") or tenant.display_name, cfg["from_address"]))
        msg["To"] = mail.to
        msg["Subject"] = mail.subject
        msg["Message-ID"] = make_msgid(domain=cfg["from_address"].split("@")[-1])
        if cfg.get("reply_to"):
            msg["Reply-To"] = cfg["reply_to"]
        msg.set_content(mail.text)
        host, port = smtp.get("host", "localhost"), int(smtp.get("port", 25))
        security = smtp.get("security", "starttls")
        try:
            if security == "tls":
                client = smtplib.SMTP_SSL(
                    host, port, timeout=10, context=ssl.create_default_context()
                )
            else:
                client = smtplib.SMTP(host, port, timeout=10)
            with client:
                if security == "starttls":
                    client.starttls(context=ssl.create_default_context())
                if smtp.get("username"):
                    client.login(smtp["username"], _password(smtp.get("password_ref")) or "")
                client.send_message(msg)
            return True
        except (OSError, smtplib.SMTPException) as e:
            log.warning("mail to %s failed: %s", mail.to, e)
            return False


@dataclass
class MemoryMailer(Mailer):
    """Keeps mails in memory (tests)."""

    sent: list[Mail] = field(default_factory=list)

    def send(self, tenant: TenantConfig, mail: Mail) -> bool:
        self.sent.append(mail)
        return True


# --- Templates (de-CH; more languages with the i18n work) ---------------------------------


def invite_mail(
    tenant: TenantConfig, to: str, name: str, inviter: str, link: str, days: int
) -> Mail:
    return Mail(
        to=to,
        subject=f"Einladung zu {tenant.display_name}",
        text=(
            f"Grüezi {name}\n\n"
            f"{inviter} hat dich zum Portal von {tenant.display_name} eingeladen.\n\n"
            f"Lege hier dein Passwort fest:\n{link}\n\n"
            f"Der Link ist {days} Tage gültig und kann nur einmal verwendet werden. "
            "Danach richtest du die Zwei-Faktor-Anmeldung mit einer Authenticator-App ein.\n\n"
            "Wenn du diese Einladung nicht erwartet hast, kannst du diese E-Mail ignorieren.\n"
        ),
    )


def reset_mail(tenant: TenantConfig, to: str, name: str, link: str, minutes: int) -> Mail:
    return Mail(
        to=to,
        subject=f"Passwort zurücksetzen · {tenant.display_name}",
        text=(
            f"Grüezi {name}\n\n"
            "Du hast ein neues Passwort angefordert. Lege es hier fest:\n"
            f"{link}\n\n"
            f"Der Link ist {minutes} Minuten gültig und kann nur einmal verwendet werden.\n\n"
            "Wenn du das nicht warst, ignoriere diese E-Mail. Dein Passwort bleibt unverändert.\n"
        ),
    )
