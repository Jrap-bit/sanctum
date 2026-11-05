'use client';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Require } from '@/components/shell';
import { Message, Panel, SectionHeader, State, Badge } from '@/components/ui';
import { patientPath, protectedDownload } from '@/lib/api';
import { useResource, useAction } from '@/lib/hooks';
type Page = {pageNumber: number; rawText: string; method: string; unreadable: boolean};
export default function ExtractionPage() {
  const {patientId, documentId} = useParams<{patientId:string;documentId:string}>();
  const base = `${patientPath(patientId)}/documents/${encodeURIComponent(documentId)}`;
  const {data, loading, error} = useResource<{filename:string; pages:Page[]}>(`${base}/pages`);
  const action = useAction(); const [index, setIndex] = useState(0); const page = data?.pages[index];
  return <Require cap="clinical:read"><SectionHeader title="Extracted document text" description="Draft transcription for checking against the original."/>
    <Panel title={data?.filename || 'Document'} icon="document">
      <div className="notice warning">This text has not been reviewed. OCR can misread names, dates, doses and handwriting. Correction and confirmation of historical sessions will be added next.</div>
      <State loading={loading} error={error}>{page && <div className="stack">
        <div className="row between"><button className="button" disabled={index === 0} onClick={() => setIndex(index - 1)}>Previous page</button><strong>Page {page.pageNumber} of {data?.pages.length}</strong><button className="button" disabled={index >= (data?.pages.length || 0) - 1} onClick={() => setIndex(index + 1)}>Next page</button></div>
        <div className="row"><Badge>Unreviewed</Badge><Badge>{page.method === 'embedded_text' ? 'PDF text' : 'OCR'}</Badge></div>
        {page.unreadable && <p className="notice warning">No readable text was found. The page may be blank or need manual transcription.</p>}
        <label className="field"><span>Extracted text</span><textarea readOnly value={page.rawText} style={{minHeight:400}}/></label>
        <button className="button" disabled={action.pending} onClick={() => void action.run(() => protectedDownload(`${base}/original`, data?.filename || 'document'))}>Download original for comparison</button>
      </div>}</State><Message error={action.error}/>
    </Panel></Require>;
}
