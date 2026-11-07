'use client';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useUnsavedChanges } from '@/lib/use-unsaved-changes';
import { Modal } from '@/components/modal';
import { Require } from '@/components/shell';
import { Badge, Field, Message, Panel, State, WorkflowSteps, SectionHeader } from '@/components/ui';
import { API_BASE, api, ApiError, patch, patientPath, post, protectedDownload } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useAction, useResource } from '@/lib/hooks';
import type { DocumentPage } from '@/lib/types';
type Group = {pageNumbers:number[];dateStatus:'known'|'unknown'|'approximate';eventDate:string|null};
type Imported = {documentId:string;version:number;sessions:{id:string;href:string;pageNumbers:number[]}[]};
type Review = {pages:DocumentPage[];filename:string;version:number;imported:Imported|null;allowedActions:string[]};
export default function ReviewDocument() {
  const {patientId,documentId}=useParams<{patientId:string;documentId:string}>();
  const base=`${patientPath(patientId)}/documents/${encodeURIComponent(documentId)}`;
  const {data,loading,error,setData,reload}=useResource<Review>(`${base}/pages`);
  const {has}=useAuth();const action=useAction();
  const [index,setIndex]=useState(0);const [text,setText]=useState('');
  const [included,setIncluded]=useState(true);const [unreadable,setUnreadable]=useState(false);
  const [groups,setGroups]=useState<Group[]>([{pageNumbers:[],dateStatus:'unknown',eventDate:null}]);
  const [notice,setNotice]=useState('');const [confirm,setConfirm]=useState(false);
  const [latest,setLatest]=useState<Review|null>(null);const [previewFailed,setPreviewFailed]=useState(false);
  const page=data?.pages[Math.min(index,Math.max(0,data.pages.length-1))];
  const dirty=Boolean(page&&(text!==(page.reviewState==='reviewed'?page.correctedText:page.correctedText||page.rawText||'')||included!==(page.included!==false)||unreadable!==Boolean(page.unreadable)));
  const editable=Boolean(data?.allowedActions.includes('review'))&&!data?.imported;
  useEffect(()=>{setText(page?.reviewState==='reviewed'?page.correctedText:page?.correctedText||page?.rawText||'');setIncluded(page?.included!==false&&!page?.unreadable);setUnreadable(Boolean(page?.unreadable));setPreviewFailed(false);},[page?.pageNumber,page?.version]);
  useUnsavedChanges(dirty);
  const save=async()=>{
    if(!page)return;setNotice('');setLatest(null);
    const result=await action.run(()=>patch<DocumentPage&{documentVersion:number}>(`${base}/pages/${page.pageNumber}`,{correctedText:text,included,unreadable,expectedVersion:page.version}));
    if(result){setData(current=>current?{...current,version:result.documentVersion,pages:current.pages.map(p=>p.pageNumber===result.pageNumber?result:p)}:current);setNotice('Page reviewed and saved.');
      if(!result.included)setGroups(current=>current.map(g=>({...g,pageNumbers:g.pageNumbers.filter(n=>n!==result.pageNumber)})));
    }
  };
  const loadLatest=async()=>{const result=await action.run(()=>api<Review>(`${base}/pages`));if(result)setLatest(result);};
  const commit=async()=>{
    if(!data||dirty)return;setNotice('');
    const result=await action.run(()=>post<Imported>(`${base}/confirm`,{expectedVersion:data.version,groups}));
    if(result){setData(current=>current?{...current,version:result.version,imported:result,allowedActions:[]}:current);setNotice('Reviewed history imported. Open the notes below.');setConfirm(false);}
  };
  const allReviewed=Boolean(data?.pages.length&&data.pages.every(p=>p.reviewState==='reviewed'));
  const includedNumbers=data?.pages.filter(p=>p.included!==false).map(p=>p.pageNumber)||[];
  const assigned=groups.flatMap(g=>g.pageNumbers);
  const validGroups=groups.every(g=>g.pageNumbers.length>0&&(g.dateStatus==='unknown'?!g.eventDate:Boolean(g.eventDate)))&&assigned.length===new Set(assigned).size&&assigned.length===includedNumbers.length&&includedNumbers.every(n=>assigned.includes(n));
  const canImport=editable&&has('clinical:write')&&allReviewed&&validGroups&&!dirty&&!action.pending;
  const visibleError=action.error instanceof ApiError&&Object.keys(action.error.fieldErrors||{}).length?new Error(Object.values(action.error.fieldErrors||{}).join(' ')):action.error;
  return <Require cap="clinical:read"><SectionHeader title="Review transcription" description="Compare every page with the original, then confirm the corrected history."/>
    <WorkflowSteps steps={['Upload','Correct pages','Group & confirm']} current={data?.imported?2:1}/>
    <Message error={visibleError} success={notice}/>
    {action.error instanceof ApiError&&action.error.status===409&&<Panel title="Review conflict"><p>Your unsaved text is still here. Compare the saved version before replacing it.</p><button className="button" disabled={action.pending} onClick={()=>void loadLatest()}>Compare latest version</button>{latest&&<div className="stack"><pre className="json-details">{latest.pages.find(p=>p.pageNumber===page?.pageNumber)?.correctedText}</pre><button className="button" onClick={()=>{setData(latest);setText(latest.pages[index]?.correctedText||'');setIncluded(latest.pages[index]?.included!==false);setUnreadable(Boolean(latest.pages[index]?.unreadable));setLatest(null);action.setError(null);}}>Replace my edits with latest saved version</button></div>}</Panel>}
    {data?.imported&&<Panel title="Imported historical sessions"><p>This document is confirmed and its page reviews are read-only. Make later corrections through a session amendment.</p>{data.imported.sessions.map(s=><p key={s.id}><Link href={s.href}>Open historical session · pages {s.pageNumbers.join(', ')}</Link></p>)}</Panel>}
    <Panel title={`Review pages · ${data?.filename||documentId}`} icon="document"><State loading={loading} error={error} retry={()=>void reload()}>{page&&<>
      <div className="row between"><button className="button" disabled={index===0||dirty||action.pending} onClick={()=>setIndex(index-1)}>Previous page</button><strong>Page {page.pageNumber} of {data?.pages.length}</strong><button className="button" disabled={index>=(data?.pages.length||0)-1||dirty||action.pending} onClick={()=>setIndex(index+1)}>Next page</button></div>
      {dirty&&<p role="status">Unsaved changes. Save this page before changing pages or importing.</p>}
      <div className="source-layout"><div><h3>Original page</h3>{previewFailed?<p className="notice warning">Preview unavailable. Download the original to compare it.</p>:<img alt={`Original document page ${page.pageNumber}`} src={`${API_BASE}${base}/pages/${page.pageNumber}/original`} style={{maxWidth:'100%',height:'auto'}} onError={()=>setPreviewFailed(true)}/>}
        <button className="button" disabled={action.pending} onClick={()=>void action.run(()=>protectedDownload(`${base}/original`,data?.filename||'document'))}>Download original</button>
      </div><div><h3>Transcription <Badge>{page.reviewState}</Badge></h3>
        <Field label="Corrected text"><textarea style={{minHeight:320}} maxLength={100000} value={text} readOnly={!editable} disabled={action.pending} onChange={e=>setText(e.target.value)}/></Field>
        <details><summary>Original extracted text</summary><pre className="json-details">{page.rawText||'No text was extracted.'}</pre></details>
        <div className="row"><label className="checkbox"><input type="checkbox" checked={included} disabled={!editable||action.pending||unreadable} onChange={e=>setIncluded(e.target.checked)}/>Include page</label><label className="checkbox"><input type="checkbox" checked={unreadable} disabled={!editable||action.pending} onChange={e=>{setUnreadable(e.target.checked);if(e.target.checked)setIncluded(false);}}/>Mark unreadable</label></div>
        <p className="small muted">Unreadable pages must be excluded. If you transcribe a page manually, clear “Mark unreadable” before including it.</p>
        {editable&&<button className="button primary" disabled={action.pending||(included&&(!text.trim()||unreadable))} onClick={()=>void save()}>Save reviewed page</button>}
      </div></div></>}</State></Panel>
    {editable&&<Panel title="Group pages into historical sessions" icon="calendar"><p>Save a review decision for every page, including excluded pages. Assign every included page once. Leave dates unknown when the source does not establish them.</p>
      {groups.map((g,i)=><div className="muted-box" key={i} style={{marginBottom:12}}><strong>Session group {i+1}</strong><div className="row">{data?.pages.map(p=><label className="checkbox" key={p.pageNumber}><input type="checkbox" checked={g.pageNumbers.includes(p.pageNumber)} disabled={action.pending||dirty||p.reviewState!=='reviewed'||p.included===false||groups.some((other,j)=>j!==i&&other.pageNumbers.includes(p.pageNumber))} onChange={e=>setGroups(groups.map((group,j)=>j===i?{...group,pageNumbers:e.target.checked?[...group.pageNumbers,p.pageNumber]:group.pageNumbers.filter(n=>n!==p.pageNumber)}:group))}/>Page {p.pageNumber}</label>)}</div>
        <div className="fields"><Field label={`Date status for group ${i+1}`}><select disabled={action.pending} value={g.dateStatus} onChange={e=>setGroups(groups.map((group,j)=>j===i?{...group,dateStatus:e.target.value as Group['dateStatus'],eventDate:null}:group))}><option value="unknown">Unknown</option><option value="known">Known</option><option value="approximate">Approximate</option></select></Field>{g.dateStatus!=='unknown'&&<Field label={`Session date for group ${i+1}`}><input type="date" disabled={action.pending} value={g.eventDate||''} onChange={e=>setGroups(groups.map((group,j)=>j===i?{...group,eventDate:e.target.value||null}:group))}/></Field>}</div>
        {groups.length>1&&<button className="button ghost" disabled={action.pending} onClick={()=>setGroups(groups.filter((_,j)=>j!==i))}>Remove group {i+1}</button>}
      </div>)}
      <div className="row"><button className="button" disabled={action.pending||groups.length>=(data?.pages.length||1)} onClick={()=>setGroups([...groups,{pageNumbers:[],dateStatus:'unknown',eventDate:null}])}>Add session group</button><button className="button primary" disabled={!canImport} onClick={()=>setConfirm(true)}>Confirm reviewed history</button></div>
      {!allReviewed&&<p className="small muted">Some pages still need a saved review decision.</p>}
      {!has('clinical:write')&&<p>A clinician with permission to write notes must confirm the import.</p>}
    </Panel>}
    <Modal open={confirm} busy={action.pending} onClose={()=>setConfirm(false)} labelledBy="import-title"><h2 id="import-title">Import reviewed history?</h2><p>This creates {groups.length} read-only historical session note(s) from {includedNumbers.length} reviewed page(s). Page reviews will be locked. Later corrections require an amendment.</p><Message error={visibleError}/><div className="actions"><button autoFocus className="button ghost" disabled={action.pending} onClick={()=>setConfirm(false)}>Cancel</button><button className="button primary" disabled={!canImport} onClick={()=>void commit()}>{action.pending?'Importing…':'Import history'}</button></div></Modal>
  </Require>;
}
