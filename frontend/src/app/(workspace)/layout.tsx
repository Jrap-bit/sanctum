import { Shell } from '@/components/shell';
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) { return <><Shell>{children}</Shell>{process.env.NEXT_PUBLIC_DEMO_MODE === '1' && <div className="demo-banner" role="status">SYNTHETIC DEMO · In-memory records · Not connected to FastAPI</div>}</>; }
