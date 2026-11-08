from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..db.models import AISummary
from ..db.models import ClinicalNote
from ..db.models import SummaryJob
from ..db.models import now
from .audit import record_audit
from .authorization import has_access
from .authorization import require
from .authorization import scoped_patient
from .sessions import content_of


def current_note(db,note):
    return note is not None and note.state=='finalized' and not db.scalar(select(ClinicalNote.id).where(ClinicalNote.parent_id==note.id,ClinicalNote.state=='finalized'))


def snapshot(note):
    content=content_of(note)
    text=content['text']
    for section in ('concerns','observations','interventions','medicationReported'):
        for item in content[section]:
            text+=f"\n{section}: {item['text']} [assertion={item['assertion']}; temporality={item['temporality']}]"
    return {'id':note.id,'version':note.version,'type':'session','title':'Reviewed historical session' if content.get('source') else 'Finalized session',
            'eventDate':note.event_date.isoformat() if note.event_date else None,
            'dateStatus':content.get('dateStatus','known' if note.event_date else 'unknown'),
            'href':f'/patients/{note.patient_id}/sessions/{note.id}','text':text,'wordCount':len(text.split()),'byteCount':len(text.encode())}


def sources_current(db,patient_id,sources):
    for source in sources:
        note=db.get(ClinicalNote,source['id'])
        if not current_note(db,note) or note.patient_id!=patient_id or note.version!=source['version']:return False
    return True


def job_output(job):
    return {'id':job.id,'state':job.state,'progress':100 if job.state=='completed' else 0,'resultId':job.summary_id,'message':job.message,'kind':'summary'}


def summary_output(db,user,patient,row):
    payload=decrypt(row.payload,f'summary:{patient.id}:{row.id}')
    current=sources_current(db,patient.id,payload['sources'])
    actions=[]
    if patient.status=='active' and has_access(db,user,patient.id,write=True) and current and 'summaries:write' in user.capabilities:
        if payload['reviewState']=='pending':actions.append('review')
        if payload['reviewState']!='rejected':actions.append('review_facts')
    return {'id':row.id,'kind':row.kind,'version':row.version,**payload,'freshness':'current' if current else 'stale',
            'sources':[{k:v for k,v in s.items() if k!='text'} for s in payload['sources']],
            'generatedAt':row.created_at,'allowedActions':actions}


def read_summary(db,user,patient_id,summary_id,write=False):
    if write:require(user,'summaries:write')
    patient=scoped_patient(db,user,patient_id,clinical=True,lock=write)
    if write and patient.status!='active':raise HTTPException(409,'Reactivate the patient before reviewing summaries.')
    row=db.scalar(select(AISummary).where(AISummary.id==str(summary_id),AISummary.patient_id==patient.id))
    if row is None:raise HTTPException(404,'Summary unavailable.')
    return patient,row


def review_payload(db,patient,row,expected):
    if row.version!=expected:raise HTTPException(409,'This review changed. Reload the latest version before deciding.')
    payload=decrypt(row.payload,f'summary:{patient.id}:{row.id}')
    if not sources_current(db,patient.id,payload['sources']):raise HTTPException(409,'A source was superseded. Generate a new draft from current records.')
    return payload


def save_review(db,request,user,patient,row,payload,action):
    payload['reviewHistory'].append({'action':action,'actor':user.display_name,'actorId':user.id,'at':now().isoformat()})
    row.version+=1;row.payload=encrypt(payload,f'summary:{patient.id}:{row.id}')
    record_audit(db,request,user,action,row.id);db.flush();result=summary_output(db,user,patient,row);db.commit();return result


def scoped_job(db,user,jid,write=False):
    job=db.get(SummaryJob,str(jid))
    if job is None:raise HTTPException(404,'Job unavailable.')
    scoped_patient(db,user,job.patient_id,clinical=True,lock=write)
    if write:
        require(user,'summaries:write')
        if job.requested_by!=user.id:raise HTTPException(403,'Only the requester can change this generation job.')
        job=db.scalar(select(SummaryJob).where(SummaryJob.id==job.id).with_for_update().execution_options(populate_existing=True))
    return job
