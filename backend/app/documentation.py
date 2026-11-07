"""DT-05: required fields for the built-in session template, version 1."""
from datetime import date
from uuid import uuid4
from sqlalchemy import select
from .models import ClinicalNote
from .sessions import content_of
from .summaries import current_note

TEMPLATE={'id':'session-default','version':1,'name':'Session note',
          'requiredFields':['Date status','At least one Concern, Observation or Intervention entry']}
SECTIONS=('concerns','observations','interventions')


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


def documentation_results(snapshot):
    template=snapshot['template'];results=[]
    for note in snapshot['sessions']:
        missing=[];status=note.get('dateStatus');event_date=note.get('eventDate')
        if status not in {'known','approximate','unknown'}:missing.append('Date status')
        elif status in {'known','approximate'}:
            try:date.fromisoformat(event_date)
            except (ValueError,TypeError):missing.append('Valid date for the recorded date status')
        elif event_date is not None:missing.append('Date consistent with unknown status')
        if not note['hasStructuredContent']:missing.append('At least one Concern, Observation or Intervention entry')
        results.append({'id':str(uuid4()),'name':'Documentation: '+(event_date or 'Undated session')+' · '+note['id'][:8],
            'ruleId':'missing-documentation','outcome':'matched' if missing else 'not_matched','missingFields':missing,
            'explanation':('Missing required information: '+ '; '.join(missing)+'. Open the note and create an amendment to add it.') if missing else 'The required date status and structured section are recorded. This checks completeness, not clinical quality.',
            'conditions':[{'label':'Template','value':template['name']+' · version '+str(template['version'])},
                {'label':'Source','value':note['sourceType']},{'label':'Source version','value':str(note['version'])},
                {'label':'Date status','value':status or 'Not recorded'},
                {'label':'Required structured section','value':'Recorded' if note['hasStructuredContent'] else 'Missing'}],
            'evidence':[{'title':note['sourceType']+' · '+(event_date or 'Undated')+' · v'+str(note['version']),'href':note['href']}]})
    if not results:
        results.append({'id':str(uuid4()),'name':'Required documentation','ruleId':'missing-documentation','outcome':'not_evaluable',
            'missingFields':[],'explanation':'No current finalized session notes are available to check. Drafts are not evaluated.',
            'conditions':[{'label':'Template','value':template['name']+' · version '+str(template['version'])},{'label':'Eligible notes','value':'0'}],'evidence':[]})
    return results
