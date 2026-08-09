from __future__ import annotations


def exact_deleted_key_vault_purge_command(subscription_id: str) -> tuple[str, ...]:
    """Build the sole authorized target-side residue purge command."""

    if (
        not subscription_id
        or subscription_id.strip() != subscription_id
        or any(marker in subscription_id for marker in ("/", "\\", "\x00"))
    ):
        raise ValueError("cleanup-residue-subscription-invalid")
    return (
        "az",
        "keyvault",
        "purge",
        "--name",
        "kv-mobius77-11564669",
        "--location",
        "southcentralus",
        "--subscription",
        subscription_id,
        "--only-show-errors",
        "--output",
        "none",
    )
