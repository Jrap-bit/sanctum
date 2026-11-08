from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..db.models import ExtractionJob


def page_data(doc, row):
    return decrypt(row.payload, f'document-page:{doc.patient_id}:{doc.id}:{row.page_number}')


def page_output(doc, row):
    data = page_data(doc, row)
    return {'pageNumber': row.page_number, **data, 'correctedText': data.get('correctedText', data['rawText']),
            'reviewState': data.get('reviewState', 'unreviewed'), 'version': row.version,
            'included': data.get('included', not data.get('unreadable', False))}


def completed(db, doc):
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == doc.id))
    if job is None or job.state != 'completed':
        raise HTTPException(409, 'Finish text extraction before reviewing or importing pages.')
