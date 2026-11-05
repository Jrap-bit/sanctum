'use client';
import Link from 'next/link';
import { Children, cloneElement, isValidElement, useId, useRef, useState, type ReactElement, type ReactNode } from 'react';
import { Modal } from './modal';
import { ApiError } from '@/lib/api';
import type { Evidence } from '@/lib/types';
import { Icon, type IconName } from './icon';
export function Badge({ children, tone }: { children: React.ReactNode; tone?: string }) { return <span className={`badge ${tone || String(children).toLowerCase().replaceAll('_', ' ').replaceAll(' ', '-')}`}>{typeof children === 'string' ? children.replaceAll('_', ' ') : children}</span>; }
export function PageHeader({ meta, title, description, action }: { meta?: string; title: string; description?: string; action?: React.ReactNode }) { return <div className="page-header"><div className="page-header-copy">{meta && <div className="page-header-meta">{meta}</div>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="header-action">{action}</div>}</div>; }
export function SectionHeader({title,description,action}:{title:string;description?:string;action?:React.ReactNode}){return <div className="section-heading"><div><h2>{title}</h2>{description&&<p>{description}</p>}</div>{action}</div>;}
export function Panel({ title, children, action, className = '', icon }: { title?: string; children: React.ReactNode; action?: React.ReactNode; className?: string; icon?: IconName }) { return <section className={`panel ${className}`}>{title && <div className="panel-head"><h2>{icon&&<span className="panel-icon"><Icon name={icon} size={18}/></span>}{title}</h2>{action}</div>}{children}</section>; }
export function State({ loading, error, empty, emptyTitle, emptyMessage, children, retry }: { retry?: () => void; loading: boolean; error?: Error | null; empty?: boolean; emptyTitle?:string; emptyMessage?:string; children: React.ReactNode }) { if (loading) return <div className="state" role="status"><span className="spinner"/>Loading…</div>; if (error) return <div className="state error" role="alert"><span className="state-icon"><Icon name="alert"/></span><strong>{error instanceof ApiError && error.code === 'FEATURE_UNAVAILABLE' ? 'Feature unavailable' : error instanceof ApiError && error.status === 403 ? 'Access denied' : error instanceof ApiError && error.status === 404 ? 'Record unavailable' : 'Could not load this view'}</strong><p>{error.message}</p>{retry && !(error instanceof ApiError && error.code === 'FEATURE_UNAVAILABLE') && <button type="button" className="button" onClick={retry}>Try again</button>}</div>; if (empty) return <div className="state"><span className="state-icon"><Icon name="document"/></span><strong>{emptyTitle||'Nothing here yet'}</strong><p>{emptyMessage||'New items will appear here when they are added.'}</p></div>; return <>{children}</>; }
export function Message({ error, success }: { error?: Error | null; success?: string | null }) { return <>{error && <div className="notice danger" role="alert">{error.message}{error instanceof ApiError && error.fieldErrors && Object.keys(error.fieldErrors).length > 0 && <ul>{Object.entries(error.fieldErrors).map(([field, reason]) => <li key={field}>{field.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ')}: {reason.replace(/^Value error, /, '')}</li>)}</ul>}{error instanceof ApiError && error.requestId && <small> Request ID: {error.requestId}</small>}</div>}{success && <div className="notice success" role="status">{success}</div>}</>; }
type FieldControl = {id?: string; required?: boolean; children?: ReactNode; 'aria-describedby'?: string; 'aria-invalid'?: boolean};
export function Field({label, children, hint, error}: {label: string; children: ReactNode; hint?: string; error?: string}) {
  const generated = useId();
  let controlId = generated;
  let linked = false;
  let required = false;
  const attach = (nodes: ReactNode): ReactNode => Children.map(nodes, node => {
    if (!isValidElement(node)) return node;
    const child = node as ReactElement<FieldControl>;
    if (!linked && typeof child.type === 'string' && ['input', 'select', 'textarea'].includes(child.type)) {
      linked = true; required = Boolean(child.props.required); controlId = child.props.id || generated;
      const description = [child.props['aria-describedby'], hint && `${generated}-hint`, error && `${generated}-error`].filter(Boolean).join(' ');
      return cloneElement(child, {id: controlId, 'aria-describedby': description || undefined, 'aria-invalid': error ? true : child.props['aria-invalid']});
    }
    return child.props.children ? cloneElement(child, {}, attach(child.props.children)) : child;
  });
  const controls = attach(children);
  return <div className="field"><label htmlFor={controlId}>{label}{required && <span className="required-mark" aria-hidden="true"> *</span>}{required && <span className="sr-only"> (required)</span>}</label>{controls}{hint && <small id={`${generated}-hint`}>{hint}</small>}{error && <small className="field-error" id={`${generated}-error`}>{error}</small>}</div>;
}
export function DateText({ date, unknown = 'Undated' }: { date?: string | null; unknown?: string }) { return <time dateTime={date || undefined}>{date ? new Date(`${date}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : unknown}</time>; }
export function TimeText({ date }: { date?: string | null }) { return <time dateTime={date || undefined}>{date ? new Date(date).toLocaleString('en-GB') : 'Unknown'}</time>; }
export function EvidenceLinks({ items }: { items?: Evidence[] }) { return items?.length ? <div className="evidence"><span>Sources</span>{items.map((item, i) => item.href.startsWith('/') && !item.href.startsWith('//') ? <Link key={i} href={item.href} title={item.passage}>{item.title} ↗</Link> : <span key={i}>{item.title} (link unavailable)</span>)}</div> : <p className="muted small">No source reference supplied.</p>; }
export function ConfirmAction({label, consequence, onConfirm, busy = false, requireReason = false}: {
  label: string; consequence: string; onConfirm: (reason: string) => void | boolean | Promise<void | boolean>; busy?: boolean; requireReason?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState<Error | null>(null);
  const active = useRef(false);
  const id = useId();
  const pending = busy || working;
  const confirm = async () => {
    if (active.current || pending || (requireReason && !reason.trim())) return;
    active.current = true; setWorking(true); setFailure(null);
    try {
      if (await onConfirm(reason.trim()) === false) throw new Error('The action was not completed. Close this dialog to review the error, then try again.');
      setOpen(false); setReason('');
    } catch (error) { setFailure(error as Error); }
    finally { active.current = false; setWorking(false); }
  };
  return <><button type="button" className="button danger-outline" disabled={busy} onClick={() => {setFailure(null); setOpen(true);}}>{label}</button>
    <Modal open={open} busy={pending} onClose={() => setOpen(false)} labelledBy={`${id}-title`} describedBy={`${id}-description`}>
      <h2 id={`${id}-title`}>Confirm {label.toLowerCase()}</h2><p id={`${id}-description`}>{consequence}</p>
      {requireReason && <Field label="Reason"><textarea value={reason} onChange={event => setReason(event.target.value)} required disabled={pending}/></Field>}
      <Message error={failure}/><div className="actions"><button type="button" className="button ghost" onClick={() => setOpen(false)} disabled={pending} autoFocus>Cancel</button>
        <button type="button" className="button danger" disabled={pending || (requireReason && !reason.trim())} onClick={() => void confirm()}>{pending ? 'Working…' : label}</button></div>
    </Modal></>;
}
export function WorkflowSteps({steps,current}:{steps:string[];current:number}){return <ol className="workflow-steps" aria-label="Workflow progress">{steps.map((step,i)=><li key={step} aria-current={i===current?'step':undefined} className={i<current?'done':i===current?'current':''}><span className="step-index">{i<current?<Icon name="check" size={14}/>:i+1}</span><span>{step}</span></li>)}</ol>;}
