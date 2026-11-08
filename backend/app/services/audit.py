from ..db.models import AuditEvent


def record_audit(db, request, user, action, target):
    db.add(AuditEvent(actor_id=user.id, action=action, target_id=target,
                      outcome="success", request_id=request.state.request_id))
