"""Optional registration bridge for Hermes versions whose desktop path skips hooks.

Uses Hermes' normal profile-aware loader and idempotent webhook registration.
No credentials, fixed installation paths, monkey patches or custom transport.
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    from hermes_cli.config import load_config
    from agent.outbound_webhooks import register_from_config

    targets = register_from_config(load_config())
    logger.debug('qq-notify: %d outbound target(s) registered', len(targets))
