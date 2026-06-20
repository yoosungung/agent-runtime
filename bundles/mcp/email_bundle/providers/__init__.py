"""Provider factory for email_bundle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import EmailSettings

from runtime_common.secrets import SecretResolver

if TYPE_CHECKING:
    from providers.base import EmailProvider


def get_provider(cfg: dict, secrets: SecretResolver) -> EmailProvider:
    settings = EmailSettings.from_cfg(cfg)
    provider = settings.provider
    if not provider:
        raise ValueError("email.provider is required in source_meta.config")

    if provider == "imap":
        from providers.imap_smtp import ImapSmtpProvider

        return ImapSmtpProvider(cfg, secrets)
    if provider == "pop3":
        from providers.pop3_smtp import Pop3SmtpProvider

        return Pop3SmtpProvider(cfg, secrets)
    if provider == "outlook":
        from providers.outlook import OutlookGraphProvider

        return OutlookGraphProvider(cfg, secrets)
    if provider == "gmail":
        from providers.gmail import GmailApiProvider

        return GmailApiProvider(cfg, secrets)

    raise ValueError(f"unsupported email.provider: {provider!r}")
