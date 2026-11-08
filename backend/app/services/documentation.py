"""DT-05: required fields for the built-in session template, version 1."""
from sqlalchemy import select

from ..db.models import ClinicalNote
from ..domain.rules.dt05_required_documentation import SECTIONS
from ..domain.rules.dt05_required_documentation import TEMPLATE
from .sessions import content_of
from .summaries import current_note


def documentation_snapshot(db,patient_id):
    notes=db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id==patient_id,ClinicalNote.state=='finalized').order_by(ClinicalNote.id)).all()
    items=[]
    for note in notes:
        if not current_note(db,note):continue
        content=content_of(note)
        # Match the source API's legacy date-status interpretation. Explicit unknown is valid.
        status=content.get('dateStatus','known' if note.event_date else 'unknown')
        items.append({'id':note.id,'version':note.version,'eventDate':note.event_date.isoformat() if note.event_date else None,
            'dateStatus':status,'hasStructuredContent':any(isinstance(entry,dict) and bool(str(entry.get('text') or '').strip())
                for name in SECTIONS for entry in (content.get(name) or [])),
            'href':f'/patients/{patient_id}/sessions/{note.id}',
            'sourceType':'Imported historical session' if content.get('source') else 'Session note'})
    return {'template':TEMPLATE.copy(),'sessions':items}
