import Link from 'next/link';
export default function NotFound() { return <div className="center-screen"><div><h1>Page unavailable</h1><p>The page could not be found.</p><Link href="/patients">Return to patients</Link></div></div>; }
