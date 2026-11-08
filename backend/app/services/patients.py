from datetime import datetime
from zoneinfo import ZoneInfo

from ..adapters.crypto import decrypt
from ..core.config import get_settings
from ..db.models import PatientEvent


def clinic_today():
    return datetime.now(ZoneInfo(get_settings().clinic_timezone)).date()


def event(db, user, patient, title, kind="patient"):
    db.add(PatientEvent(patient_id=patient.id, actor_id=user.id, kind=kind,
                        title=title, event_date=clinic_today(), version=patient.version))


def task_output(task):
    payload = decrypt(task.payload, f"follow-up:{task.patient_id}:{task.id}")
    return {"id": task.id, **payload, "state": task.state, "source": "Manual"}
