"""Shared helpers for email_bundle."""

from __future__ import annotations

import re
from email import policy
from email.message import EmailMessage, Message
from email.utils import formataddr, getaddresses, parsedate_to_datetime
from typing import Any

from email_validator import EmailNotValidError, validate_email

from runtime_common.secrets import SecretResolver


def resolve_credential(
    block: dict,
    secrets: SecretResolver,
    *,
    value_key: str = "password",
    ref_key: str = "password_ref",
) -> str | None:
    ref = block.get(ref_key)
    if ref:
        return secrets.resolve(str(ref))
    value = block.get(value_key)
    return str(value) if value is not None else None


def validate_recipients(addresses: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in addresses:
        try:
            validated = validate_email(raw, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError(f"invalid email address: {raw!r}") from exc
        normalized.append(validated.normalized)
    return normalized


def normalize_recipients(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        return validate_recipients([value])
    return validate_recipients(list(value))


def truncate_text(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_addresses(header_value: str | None) -> list[str]:
    if not header_value:
        return []
    return [addr for _, addr in getaddresses([header_value]) if addr]


def format_message_date(msg: Message) -> str:
    raw = msg.get("Date")
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError, OverflowError):
        return str(raw)


def extract_bodies(msg: Message, *, prefer: str, max_bytes: int) -> tuple[str | None, str | None]:
    text_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            try:
                payload = part.get_content()
            except Exception:
                continue
            if not isinstance(payload, str):
                continue
            if content_type == "text/plain":
                text_parts.append(payload)
            elif content_type == "text/html":
                html_parts.append(payload)
    else:
        content_type = msg.get_content_type()
        try:
            payload = msg.get_content()
        except Exception:
            payload = None
        if isinstance(payload, str):
            if content_type == "text/html":
                html_parts.append(payload)
            else:
                text_parts.append(payload)

    body_text = truncate_text("\n".join(text_parts), max_bytes) if text_parts else None
    body_html = truncate_text("\n".join(html_parts), max_bytes) if html_parts else None

    if prefer == "text" and not body_text and body_html:
        body_text = truncate_text(strip_html(body_html), max_bytes)
    elif prefer == "html" and not body_html and body_text:
        body_html = None

    return body_text, body_html


def extract_attachment_meta(msg: Message) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for part in msg.walk():
        if part.get_content_disposition() != "attachment":
            continue
        filename = part.get_filename() or "attachment"
        size = len(part.get_payload(decode=True) or b"")
        attachments.append(
            {
                "name": filename,
                "size": size,
                "content_type": part.get_content_type(),
            }
        )
    return attachments


def build_plain_email(
    *,
    from_address: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(body, subtype="plain")
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    return message


def encode_address_list(addresses: list[str]) -> str:
    return ", ".join(formataddr(("", addr)) for addr in addresses)


def parse_rfc822_message(raw: bytes) -> Message:
    return policy.default.message_factory(raw)  # type: ignore[arg-type, return-value]


def send_via_smtp(
    *,
    smtp_cfg: dict,
    imap_cfg: dict,
    secrets: SecretResolver,
    from_address: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> None:
    import smtplib

    host = smtp_cfg.get("host")
    username = smtp_cfg.get("username") or imap_cfg.get("username")
    if not host or not username:
        raise RuntimeError("smtp.host and smtp.username are required")

    password = resolve_credential(smtp_cfg, secrets)
    if not password:
        password = resolve_credential(imap_cfg, secrets)
    if not password:
        raise RuntimeError("smtp credentials missing: set smtp.password or imap.password in config")

    port = int(smtp_cfg.get("port", 587))
    use_starttls = bool(smtp_cfg.get("use_starttls", True))
    message = build_plain_email(
        from_address=from_address,
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
    )
    recipients = to + (cc or []) + (bcc or [])
    with smtplib.SMTP(str(host), port, timeout=30) as smtp:
        if use_starttls:
            smtp.starttls()
        smtp.login(str(username), password)
        smtp.send_message(message, to_addrs=recipients)
