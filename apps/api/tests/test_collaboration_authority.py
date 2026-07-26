from __future__ import annotations

from opencanvas_api.services.collaboration_authority import (
    ACTION_PERMISSIONS,
    ROLE_PERMISSION_CEILINGS,
    CollaborationAction,
    CollaborationPermission,
    CollaborationRole,
)


def test_closed_role_permission_and_action_registries_are_exact() -> None:
    assert {role.value for role in CollaborationRole} == {
        "owner",
        "administrator",
        "editor",
        "approver",
        "member",
        "viewer",
    }
    assert {permission.value for permission in CollaborationPermission} == {
        "workspace.view",
        "workspace.settings.manage",
        "membership.view",
        "membership.manage",
        "invitation.create",
        "invitation.resend",
        "invitation.revoke",
        "role.assign",
        "ownership.transfer.request",
        "ownership.transfer.accept",
        "ownership.transfer.cancel",
        "canvas.view",
        "canvas.edit",
        "canvas.share",
        "resource.view",
        "resource.edit",
        "resource.share",
        "comment.create",
        "comment.edit_own",
        "comment.resolve",
        "comment.moderate",
        "workflow.view",
        "workflow.edit",
        "workflow.share",
        "workflow.invoke",
        "agent.view",
        "agent.edit",
        "agent.share",
        "agent.activate_request",
        "agent.invoke",
        "approval.review",
        "collaboration_activity.view",
        "trace.view",
        "source.export",
        "evidence_bundle.view",
        "evidence_bundle.export",
    }
    assert set(ROLE_PERMISSION_CEILINGS) == set(CollaborationRole)
    assert set(ACTION_PERMISSIONS) == set(CollaborationAction)
    assert all("*" not in permission.value for permission in CollaborationPermission)


def test_role_ceilings_preserve_approval_and_administration_boundaries() -> None:
    owner = ROLE_PERMISSION_CEILINGS[CollaborationRole.OWNER]
    administrator = ROLE_PERMISSION_CEILINGS[CollaborationRole.ADMINISTRATOR]
    editor = ROLE_PERMISSION_CEILINGS[CollaborationRole.EDITOR]
    approver = ROLE_PERMISSION_CEILINGS[CollaborationRole.APPROVER]
    member = ROLE_PERMISSION_CEILINGS[CollaborationRole.MEMBER]
    viewer = ROLE_PERMISSION_CEILINGS[CollaborationRole.VIEWER]

    assert CollaborationPermission.ROLE_ASSIGN in owner
    assert CollaborationPermission.ROLE_ASSIGN in administrator
    assert CollaborationPermission.ROLE_ASSIGN not in editor | approver | member | viewer
    assert CollaborationPermission.APPROVAL_REVIEW in approver
    assert CollaborationPermission.APPROVAL_REVIEW not in owner | administrator
    assert CollaborationPermission.WORKSPACE_SETTINGS_MANAGE in owner
    assert CollaborationPermission.WORKSPACE_SETTINGS_MANAGE not in administrator
    assert CollaborationPermission.COMMENT_CREATE not in viewer
    assert CollaborationPermission.WORKFLOW_INVOKE not in viewer
    assert CollaborationPermission.EVIDENCE_BUNDLE_EXPORT not in viewer


def test_registry_construction_denies_unknown_values() -> None:
    for registry in (
        CollaborationRole,
        CollaborationPermission,
        CollaborationAction,
    ):
        try:
            registry("unknown")
        except ValueError:
            pass
        else:
            raise AssertionError("closed registry accepted an unknown value")
