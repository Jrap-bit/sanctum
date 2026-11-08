"""The single authority model: every account capability set comes from these presets."""

# What the administration API may assign. No preset mixes administrative and clinical authority,
# so an administrator cannot mint an account with clinical oversight (IT-06).
ACCOUNT_PRESETS = {
    "clinician": {"patients:read", "patients:create", "clinical:read", "clinical:write", "documents:write",
                  "summaries:write", "indicators:write", "reports:write", "grants:request"},
    "admin": {"patients:read", "patients:create", "users:manage", "audit:read", "operations:manage",
              "assignments:manage", "grants:request"},
    "oversight": {"patients:read", "clinical:read", "grants:approve", "rules:publish", "reports:write", "audit:read"},
}

# FR-15: deletion needs both authorities together. Only the host operator can create this
# role, through `python -m app.manage create-user`; the API cannot assign it.
OPERATOR_ROLES = {"clinical_admin": ACCOUNT_PRESETS["admin"] | ACCOUNT_PRESETS["oversight"] | {"patients:delete"}}

ROLE_CAPABILITIES = {role: sorted(capabilities) for role, capabilities in (ACCOUNT_PRESETS | OPERATOR_ROLES).items()}
