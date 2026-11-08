from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..db.models import ClinicalNote
from ..db.models import ConfirmedMedication
from .summaries import current_note


def rows(db,pid):return db.scalars(select(ConfirmedMedication).where(ConfirmedMedication.patient_id==pid).order_by(ConfirmedMedication.created_at,ConfirmedMedication.id)).all()


def medication_output(db,row):
    payload=decrypt(row.payload,f'medication:{row.patient_id}:{row.id}')
    note=db.get(ClinicalNote,payload['sourceId'])
    current=bool(note and note.patient_id==row.patient_id and current_note(db,note) and note.version==payload['sourceVersion'])
    return {'id':row.id,'version':row.version,'state':row.state,'freshness':'current' if current else 'stale',**payload,'confirmedAt':row.created_at.isoformat(),'withdrawalReason':decrypt(row.withdrawal,f'medication-withdrawal:{row.patient_id}:{row.id}')['reason'] if row.withdrawal else None}
