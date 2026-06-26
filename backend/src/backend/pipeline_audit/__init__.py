"""Pipeline Console BFF audit — optional plugin (PIPELINE_CONSOLE_ENABLED).

When Pipeline BFF splits from agents-runtime, move this package with the BFF and keep
writing to public.audit_log with pipeline.* actions and domain=pipeline.
"""

from backend.pipeline_audit.register import install_pipeline_console_audit

__all__ = ["install_pipeline_console_audit"]
