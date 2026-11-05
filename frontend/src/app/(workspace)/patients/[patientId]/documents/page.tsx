'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Require } from '@/components/shell';
import { Icon } from '@/components/icon';
import { Badge, Message, Panel, State, TimeText, WorkflowSteps, SectionHeader } from '@/components/ui';
import { API_BASE, ApiError, api, post, patientPath, protectedDownload } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useAction, useResource } from '@/lib/hooks';
import type { Document } from '@/lib/types';

export default function DocumentsPage() {
  const id = useParams<{patientId: string}>().patientId;
  const base = `${patientPath(id)}/documents`;
  const {has} = useAuth();
  const {data, loading, error, reload, setData} = useResource<{items: Document[]}>(base);
  const action = useAction();
  const [pollError,setPollError]=useState<Error|null>(null);
  const hasPending = data?.items.some(d => ['queued', 'running'].includes(d.jobState)) || false;
  useEffect(() => {
    if (!hasPending) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<{items: Document[]}>(base, {signal: controller.signal});
        if (!controller.signal.aborted) {setData(result); setPollError(null); timer = setTimeout(poll, 3000);}
      } catch (failure) {if (!controller.signal.aborted) setPollError(failure as Error);}
    };
    timer = setTimeout(poll, 3000);
    return () => {controller.abort(); clearTimeout(timer);};
  }, [base, hasPending, setData]);
  const process = async (documentId: string, operation: string) => {
    const result = await action.run(() => post(`${base}/${encodeURIComponent(documentId)}/${operation}`, {}));
    if (result) await reload();
  };
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<Error | null>(null);
  const [notice, setNotice] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const activeUpload = useRef<XMLHttpRequest | null>(null);
  useEffect(() => () => {
    const xhr = activeUpload.current;
    if (xhr) { xhr.onload = xhr.onerror = xhr.onabort = xhr.ontimeout = xhr.onloadend = null; xhr.abort(); }
    activeUpload.current = null;
  }, [id]);
  const upload = () => {
    if (!file || activeUpload.current) return;
    if (!file.size || file.size > 25 * 1024 * 1024 || !/\.(pdf|jpe?g|png)$/i.test(file.name)) {
      setUploadError(new Error('Choose a non-empty PDF, JPEG or PNG up to 25 MB.')); return;
    }
    setUploadError(null); setNotice(''); setProgress(0); setUploading(true);
    const xhr = new XMLHttpRequest(); activeUpload.current = xhr;
    const body = new FormData(); body.append('file', file);
    xhr.open('POST', `${API_BASE}${base}`); xhr.withCredentials = true; xhr.timeout = 120000;
    xhr.upload.onprogress = e => { if (e.lengthComputable) setProgress(Math.round(e.loaded * 100 / e.total)); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        setFile(null); if (input.current) input.current.value = '';
        setNotice('Document stored securely. Select Start extraction to read its text.'); void reload();
      } else {
        let details: {message?: string; code?: string; requestId?: string} = {};
        try { details = JSON.parse(xhr.responseText); } catch { /* Proxy may return a non-JSON error. */ }
        setUploadError(new ApiError(xhr.status, details.code || 'UPLOAD_FAILED', details.message || `Upload failed (${xhr.status}). Please try again.`, undefined, details.requestId));
        if (xhr.status === 401) window.dispatchEvent(new Event('sanctum:expired'));
        if ([403,404].includes(xhr.status)) window.dispatchEvent(new CustomEvent('sanctum:denied',{detail:{path:base,status:xhr.status}}));
      }
    };
    xhr.onerror = () => setUploadError(new Error('Upload could not be confirmed. Check your connection, then refresh the file list before retrying.'));
    xhr.ontimeout = () => setUploadError(new Error('Upload timed out. Refresh the file list before retrying; it may already have been stored.'));
    xhr.onabort = () => setUploadError(new Error('Upload cancelled. Refresh the file list before retrying.'));
    xhr.onloadend = () => { activeUpload.current = null; setUploading(false); setProgress(0); };
    xhr.send(body);
  };
  return <Require cap="clinical:read"><SectionHeader title="Documents" description="Store original records securely against this patient."/>
    <WorkflowSteps steps={['Upload', 'Review pages', 'Confirm history']} current={0}/>
    {has('documents:write') && <Panel title="Upload a file" icon="upload">
      <div className="inline-note">PDF, JPEG or PNG · up to 25 MB. PDFs: up to 500 pages. Images: up to 20 megapixels. Start extraction after uploading. Extracted text remains an unreviewed draft.</div>
      <div className="upload-row"><label className="dropzone"><Icon name="upload" size={24}/><strong>{file ? file.name : 'Choose a file'}</strong><span>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB selected` : 'PDF, JPEG or PNG'}</span>
        <input ref={input} disabled={uploading} aria-label="Select historical document" type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={e => {setFile(e.target.files?.[0] || null); setUploadError(null); setNotice('');}}/>
      </label><button className="button primary" disabled={!file || uploading} onClick={upload}>{uploading ? 'Uploading…' : 'Upload file'} <Icon name="arrow" size={16}/></button></div>
      {uploading && <div role="status" style={{marginTop: 10}}><div className="progress" role="progressbar" aria-label="Document upload" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{transform: `scaleX(${progress / 100})`}}/></div><small>{progress < 100 ? `${progress}% sent` : 'File sent. Validating and saving…'}</small></div>}
      <Message error={uploadError} success={notice}/>
    </Panel>}
    <Message error={action.error || pollError}/>
    <Panel title="Your files" icon="document" action={<button className="button small-button" disabled={loading} onClick={() => {setPollError(null); void reload();}}>Refresh files</button>}>
      <State loading={loading} error={error} retry={()=>void reload()} empty={!data?.items.length}>{data?.items.map(d => <div key={d.id} className="list-item row between"><div>
        <strong>{d.filename}</strong><p>Uploaded <TimeText date={d.uploadedAt}/> · {d.pageCount} page(s) · {d.uploader || 'Unknown uploader'}</p>
        <div className="row"><Badge>{d.reviewState}</Badge><Badge>{d.jobState === 'not_started' ? 'Ready for extraction' : d.jobState}</Badge>{d.jobState === 'running' && <span>{d.progress || 0}% processed</span>}</div>{d.processingMessage && <p role="status">{d.processingMessage}</p>}
      </div><div className="row"><button className="button small-button" disabled={action.pending} onClick={() => void action.run(() => protectedDownload(`${base}/${encodeURIComponent(d.id)}/original`, d.filename))}>Download original</button>
        {has('documents:write') && d.jobState === 'not_started' && <button className="button small-button" disabled={action.pending} onClick={() => void process(d.id, 'process')}>Start extraction</button>}
        {has('documents:write') && ['failed', 'cancelled'].includes(d.jobState) && <button className="button small-button" disabled={action.pending} onClick={() => void process(d.id, 'retry')}>Retry extraction</button>}
        {has('documents:write') && ['queued', 'running'].includes(d.jobState) && <button className="button small-button" disabled={action.pending} onClick={() => void process(d.id, 'cancel')}>Cancel extraction</button>}
        {d.allowedActions?.includes('extraction') && <Link className="button small-button" href={`${base}/${encodeURIComponent(d.id)}/extraction`}>View extracted text</Link>}
        {d.allowedActions?.includes('review') && <Link className="button small-button" href={`${base}/${encodeURIComponent(d.id)}/review`}>Review pages</Link>}
      </div></div>)}</State>
    </Panel>
  </Require>;
}
