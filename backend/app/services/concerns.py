from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..db.models import ClinicalNote
from ..db.models import ConfirmedConcern
from .sessions import content_of
from .summaries import current_note


def rows(db,pid):return db.scalars(select(ConfirmedConcern).where(ConfirmedConcern.patient_id==pid).order_by(ConfirmedConcern.created_at,ConfirmedConcern.id)).all()


def concern_output(db,row):
    payload=decrypt(row.payload,f'concern:{row.patient_id}:{row.id}')
    note=db.get(ClinicalNote,payload['sourceId'])
    current=bool(note and note.patient_id==row.patient_id and current_note(db,note) and note.version==payload['sourceVersion'])
    return {'id':row.id,'version':row.version,'state':row.state,'freshness':'current' if current else 'stale',**payload,'confirmedAt':row.created_at.isoformat(),'withdrawalReason':decrypt(row.withdrawal,f'concern-withdrawal:{row.patient_id}:{row.id}')['reason'] if row.withdrawal else None}


def session_snapshot(db,patient_id):
    notes=db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id==patient_id,ClinicalNote.state=='finalized').order_by(ClinicalNote.id)).all()
    return [{'id':n.id,'version':n.version,'eventDate':n.event_date.isoformat() if n.event_date else None,
        'dateStatus':content_of(n).get('dateStatus','known' if n.event_date else 'unknown'),
        'href':f'/patients/{patient_id}/sessions/{n.id}'} for n in notes if current_note(db,n)]
