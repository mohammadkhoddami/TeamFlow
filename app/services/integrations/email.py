"""Email sending: console (dev mock) or SMTP (aiosmtplib).

Templates are tiny string builders — enough for transactional email without
adding a template engine. Used by Celery tasks; never called inline from
request handlers (email I/O must not block the API).
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

TEMPLATES: dict[str, tuple[str, str]] = {
    # kind -> (subject, body template with {placeholders})
    "password_reset": (
        "Reset your TeamFlow password",
        "Use the link below to reset your password (valid for 30 minutes):\n\n{reset_link}\n\n"
        "If you did not request this, ignore this email.",
    ),
    "otp_code": (
        "Your TeamFlow sign-in code",
        "Your sign-in code is: {code}\n\n"
        "It expires in {expires_minutes} minutes. If you did not request this, ignore this email.",
    ),
    "organization_invite": (
        "You have been invited to a TeamFlow organization",
        "You have been invited to join '{organization}' as {role}.\n\n"
        "Log in to TeamFlow and open Invitations to accept or decline.",
    ),
    "task_assigned": (
        "A task was assigned to you",
        "Task '{task_key} {task_title}' was assigned to you in project "
        "'{project_name}'.\nOpen it at {task_url}\n\n"
        "Stop these emails: {unsubscribe_url}",
    ),
    "task_completed": (
        "A task you follow was completed",
        "Task '{task_key} {task_title}' in project '{project_name}' is done.\n"
        "Open it at {task_url}\n\n"
        "Stop these emails: {unsubscribe_url}",
    ),
    "mention": (
        "You were mentioned in TeamFlow",
        "{author_name} mentioned you on '{task_key} {task_title}':\n\n"
        "{comment_excerpt}\n\nOpen it at {task_url}\n\n"
        "Stop these emails: {unsubscribe_url}",
    ),
    "comment_created": (
        "New comment on a task you follow",
        "{author_name} commented on '{task_key} {task_title}':\n\n"
        "{comment_excerpt}\n\nOpen it at {task_url}\n\n"
        "Stop these emails: {unsubscribe_url}",
    ),
    "notification_digest": (
        "Your TeamFlow digest",
        "You have {count} unread TeamFlow notifications.\n\n"
        "{lines}\n\nOpen TeamFlow: {frontend_url}\n\n"
        "Stop these emails: {unsubscribe_url}",
    ),
}


def render(kind: str, ctx: dict[str, str]) -> tuple[str, str]:
    subject, body = TEMPLATES[kind]
    return subject, body.format(**ctx)


def send_sync(to: str, subject: str, body: str) -> None:
    """Runs inside a Celery worker thread. Retries are the task's concern."""
    if settings.email_backend == "smtp":
        logger.info(
            "SMTP send to=%s subject=%r via %s:%s",
            to, subject, settings.smtp_hostname, settings.smtp_port,
        )
        _send_smtp(to, subject, body)
        logger.info("SMTP accepted to=%s subject=%r", to, subject)
        return
    # Console backend: development/mock provider. The body is logged verbatim
    # (including OTP codes) so local flows are testable without a mail server.
    logger.info(
        "EMAIL(to=%s subject=%r)\n%s", to, subject, body,
    )


def _send_smtp(to: str, subject: str, body: str) -> None:
    import asyncio

    async def _send() -> None:
        from email.message import EmailMessage

        import aiosmtplib

        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        # Port 465 speaks implicit TLS; 587 (and anything with SMTP_USE_TLS)
        # upgrades via STARTTLS. aiosmtplib rejects both flags at once.
        implicit_tls = settings.smtp_port == 465
        start_tls = not implicit_tls and (
            settings.smtp_use_tls or settings.smtp_port == 587
        )
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_hostname,
            port=settings.smtp_port,
            # Most providers authenticate with the full sender address.
            username=settings.smtp_username or settings.email_from or None,
            password=settings.smtp_password or None,
            use_tls=implicit_tls,
            start_tls=start_tls,
        )

    asyncio.run(_send())
