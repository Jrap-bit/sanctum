import type { Document, DocumentPage, FollowUp, Indicator, Patient, ReportManifest, Rule, Session, Source, Summary, TimelineEvent, User } from './types';

// Ephemeral, synthetic records for local UI review only. No clinical data belongs here.
const clinicianCaps = ['patients:read','patients:create','clinical:read','clinical:write','documents:write','summaries:write','indicators:write','reports:write','grants:request','audit:read'] as User['capabilities'];
const adminCaps = ['patients:read','patients:create','users:manage','assignments:manage','grants:request','audit:read','operations:manage'] as User['capabilities'];
const oversightCaps = ['patients:read','clinical:read','reports:write','grants:approve','rules:publish','audit:read','patients:delete'] as User['capabilities'];
const DEMO_USERS: User[] = [
  { id:'demo-clinician', username:'clinician', displayName:'Dr Maya Sen', capabilities:clinicianCaps, clinicTimezone:'Asia/Kolkata' },
  { id:'demo-admin', username:'admin', displayName:'Alex Morgan', capabilities:adminCaps, clinicTimezone:'Asia/Kolkata' },
  { id:'demo-oversight', username:'oversight', displayName:'Dr Noor Shah', capabilities:oversightCaps, clinicTimezone:'Asia/Kolkata' }
];
interface DemoDocument extends Document { pages: DocumentPage[]; bytes?: Uint8Array; mime?: string }
interface DemoStore {
  users: (User & {active:boolean})[];
  patients: Patient[]; sessions: Record<string,Session[]>; timeline: Record<string,TimelineEvent[]>; historicalSources: Record<string,Source[]>;
  followUps: Record<string,FollowUp[]>; documents: Record<string,DemoDocument[]>;
  summaries: Record<string,Summary[]>; indicators: Record<string,Indicator[]>;
  assignments: {id:string;patientId:string;practitionerId:string;kind:string;version:number;updatedAt:string}[];
  grants: {id:string;patientId:string;subjectId:string;capability:string;requesterId:string;approverId?:string;reason:string;state:string;createdAt:string}[];
  rules: Rule[]; manifests: Record<string,ReportManifest>; jobs: Record<string,{id:string;state:string;resultId?:string;progress?:number}>;
  backups: {id:string;createdAt:string;scope:string;verified:boolean;manifest:string}[];
  audit: {id:string;action:string;actorId:string;targetId:string;result:string;requestId:string;at:string}[];
}
function seedDemo(): DemoStore {
  const patient:Patient = { id:'demo-patient-001', displayName:'Avery Reed (synthetic)', dateOfBirth:'1994-05-16', status:'active', assignment:'Dr Maya Sen', assignedPractitionerIds:['demo-clinician'], version:1, allowedActions:[] };
  const second:Patient = { id:'demo-patient-002', displayName:'Jordan Ellis (synthetic)', dateOfBirth:'1989-02-03', status:'archived', assignment:'Dr Maya Sen', assignedPractitionerIds:['demo-clinician'], version:1, allowedActions:[] };
  const note:Session = { id:'demo-session-001',patientId:patient.id,eventDate:'2026-10-09',state:'finalized',version:1,text:'Patient reported difficulty sleeping during a busy work period. Discussed a short evening wind-down routine and agreed to revisit sleep at the next session.',concerns:[{text:'Difficulty sleeping',assertion:'present',temporality:'current'}],observations:[],interventions:[{text:'Discussed evening routine',assertion:'present',temporality:'current'}],medicationReported:[],author:'Dr Maya Sen',updatedAt:'2026-10-09T10:40:00Z',allowedActions:['amend'] };
  const doc:DemoDocument = { id:'demo-document-001',filename:'synthetic-history.pdf',uploadedAt:'2026-10-14T11:00:00Z',uploader:'Dr Maya Sen',pageCount:2,reviewState:'pending',jobState:'completed',progress:100,version:1,allowedActions:['withdraw'],pages:[1,2].map(pageNumber => ({pageNumber,rawText:pageNumber===1?'Synthetic handwritten note: reported work stress.':'Synthetic handwritten note: follow up discussed.',correctedText:'',reviewState:'pending',included:true,version:1})) };
  const summary:Summary = { id:'demo-summary-001',kind:'single_session',text:'The patient described difficulty sleeping during a busy work period. An evening routine was discussed.',originalText:'The patient described difficulty sleeping during a busy work period. An evening routine was discussed.',reviewState:'pending',freshness:'current',generatedAt:'2026-10-15T09:15:00Z',model:'Synthetic demo response',sources:[{id:note.id,type:'session',title:'Session · 9 Oct 2026',eventDate:note.eventDate,version:1,wordCount:note.text.split(' ').length,href:`/patients/${patient.id}/sessions/${note.id}`}],evidence:[{title:'Finalized session v1',href:`/patients/${patient.id}/sessions/${note.id}`,passage:'Patient reported difficulty sleeping'}],facts:[{id:'demo-fact-001',label:'SLEEP_CONCERN',text:'Difficulty sleeping was reported.',assertion:'present',temporality:'current',state:'pending',subject:'Patient',evidence:[{title:'Session v1',href:`/patients/${patient.id}/sessions/${note.id}`}]}],reviewHistory:[],allowedActions:['review'] };
  const indicator:Indicator = { id:'demo-indicator-001',name:'Repeated documented concern',outcome:'not_evaluable',enabled:true,freshness:'current',ruleVersion:1,explanation:'Three dated sessions are required; only one eligible session is available.',conditions:[{label:'Eligible dated sessions',value:'1'},{label:'Required',value:'3'}],evaluatedAt:'2026-10-15T09:20:00Z',reviewState:'unreviewed',evidence:[{title:'Session v1',href:`/patients/${patient.id}/sessions/${note.id}`}],allowedActions:['review'] };
  const rules:Rule[] = [
    {id:'repeated-concern',name:'Repeated documented concern',enabled:true,version:1,parameters:{W:3,K:3},bounds:{W:{min:2,max:10},K:{min:2,max:10}},description:'Documented concern in K of W dated sessions.',history:[]},
    {id:'difficulty-scale',name:'Difficulty scale increase',enabled:true,version:1,parameters:{D:2},bounds:{D:{min:1,max:10}},description:'Latest comparable pair on the same named 0–10 scale.',history:[]},
    {id:'overdue-followup',name:'Overdue follow-up',enabled:true,version:1,parameters:{},bounds:{},description:'Open task due before the evaluation date.',history:[]},
    {id:'medication-change',name:'Documented medication change',enabled:true,version:1,parameters:{L:30},bounds:{L:{min:1,max:90}},description:'Change documented within the inclusive lookback window.',history:[]},
    {id:'missing-documentation',name:'Missing required documentation',enabled:true,version:1,parameters:{},bounds:{},description:'Required fields missing from eligible notes.',history:[]}
  ];
  return { users:DEMO_USERS.map(u=>({...u,active:true})),patients:[patient,second],sessions:{[patient.id]:[note],[second.id]:[]},historicalSources:{[patient.id]:[],[second.id]:[]},timeline:{[patient.id]:[{id:note.id,type:'session',title:'Session note · 9 Oct',eventDate:note.eventDate,createdAt:note.updatedAt!,author:note.author,status:'finalized',href:`/patients/${patient.id}/sessions/${note.id}`,version:1}],[second.id]:[]},followUps:{[patient.id]:[{id:'demo-task-001',title:'Review sleep routine',details:'Discuss changes at the next session.',dueDate:null,state:'open',source:'Session v1'}],[second.id]:[]},documents:{[patient.id]:[doc],[second.id]:[]},summaries:{[patient.id]:[summary],[second.id]:[]},indicators:{[patient.id]:[indicator],[second.id]:[]},assignments:[{id:'demo-assignment-001',patientId:patient.id,practitionerId:'demo-clinician',kind:'primary',version:1,updatedAt:'2026-10-09T08:00:00Z'}],grants:[],rules,manifests:{},jobs:{},backups:[],audit:[] };
}
declare global { var sanctumDemoStore: DemoStore | undefined }
export function demoStore():DemoStore { return globalThis.sanctumDemoStore ??= seedDemo(); }
export function demoSource(session:Session):Source { return {id:session.id,type:'session',title:`Session · ${session.eventDate || 'Undated'}`,eventDate:session.eventDate,version:session.version,wordCount:session.text.split(/\s+/).length,href:`/patients/${session.patientId}/sessions/${session.id}`}; }
