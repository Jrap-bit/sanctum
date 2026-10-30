'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useRef, useState } from 'react';
import { useAuth } from '@/lib/auth';
import type { Capability } from '@/lib/types';
import { Icon, type IconName } from './icon';

const navigation: { href: string; label: string; icon: IconName; cap: Capability }[] = [
  { href: '/patients', label: 'Patients', icon: 'patient', cap: 'patients:read' },
  { href: '/admin/users', label: 'People', icon: 'users', cap: 'users:manage' },
  { href: '/admin/assignments', label: 'Assignments', icon: 'handover', cap: 'assignments:manage' },
  { href: '/access/grants', label: 'Access requests', icon: 'key', cap: 'grants:request' },
  { href: '/oversight/rules', label: 'Decision rules', icon: 'rules', cap: 'rules:publish' },
  { href: '/audit', label: 'Activity log', icon: 'audit', cap: 'audit:read' },
  { href: '/admin/operations', label: 'System health', icon: 'activity', cap: 'operations:manage' },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading, has, logout } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  if (loading) return <div className="center-screen"><span className="spinner"/>Opening workspace…</div>;
  if (!user) return <div className="center-screen">Sign in to continue.</div>;

  const links = navigation.filter(link => has(link.cap)
    || (link.href === '/access/grants' && has('grants:approve'))
    || (link.href === '/patients' && has('clinical:read')));
  const signOut = async () => {
    if (window.confirm('Sign out? Save any open work before leaving.')) await logout();
  };
  const closeMenu = () => {
    setMenuOpen(false);
    menuButton.current?.focus();
  };

  return <div className="app-layout">
    <a className="skip-link" href="#workspace-content">Skip to content</a>
    {menuOpen && <button className="navigation-backdrop" aria-label="Close navigation" onClick={closeMenu}/>}
    <header className="workspace-header" onKeyDown={event => {
      if (event.key === 'Escape') closeMenu();
    }}>
      <Link href="/patients" className="workspace-brand" aria-label="Sanctum home" onClick={() => setMenuOpen(false)}>
        <span className="brand-mark"><Icon name="sparkle" size={23}/></span>
        <span>sanctum</span>
      </Link>
      <button ref={menuButton} className="navigation-toggle" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={menuOpen} aria-controls="workspace-navigation" onClick={() => setMenuOpen(!menuOpen)}>
        <Icon name={menuOpen ? 'close' : 'menu'} size={21}/><span>Menu</span>
      </button>
      <nav id="workspace-navigation" aria-label="Main navigation" className={`primary-navigation ${menuOpen ? 'is-open' : ''}`}>
        {links.map(link => {
          const active = pathname === link.href || (link.href === '/patients' && pathname.startsWith('/patients/'));
          return <Link key={link.href} href={link.href} aria-current={active ? 'page' : undefined} onClick={() => setMenuOpen(false)}>
            <Icon name={link.icon} size={18}/><span>{link.label}</span>
          </Link>;
        })}
      </nav>
      <details className="workspace-account" onKeyDown={event => {
        if (event.key === 'Escape') {
          event.currentTarget.open = false;
          event.currentTarget.querySelector('summary')?.focus();
          event.stopPropagation();
        }
      }} onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) event.currentTarget.open = false;
      }}>
        <summary aria-label={`Account: ${user.displayName}`} title={user.displayName}>
          <span className="account-avatar">{user.displayName?.charAt(0) || 'U'}</span><Icon name="chevron" size={14}/>
        </summary>
        <div className="account-popover">
          <strong>{user.displayName}</strong><span>{user.username}</span>
          <button type="button" onClick={signOut}><Icon name="logout" size={18}/>Sign out</button>
        </div>
      </details>
    </header>
    <main id="workspace-content" className="main-content" tabIndex={-1}>{children}</main>
  </div>;
}

export function Require({cap,children}:{cap:Capability;children:React.ReactNode}){const {has,loading}=useAuth();if(loading)return <div className="state">Checking access…</div>;if(!has(cap))return <div className="state error"><strong>Access denied</strong><p>Your account needs access to this area.</p></div>;return <>{children}</>;}
export function PatientTabs({id}:{id:string}){const path=usePathname();const {has}=useAuth();const tabs:{label:string;suffix:string;icon:IconName;cap?:Capability}[]=[{label:'Overview',suffix:'',icon:'home'},{label:'Sessions',suffix:'/sessions/new',icon:'notes',cap:'clinical:write'},{label:'Documents',suffix:'/documents',icon:'document',cap:'documents:write'},{label:'AI summaries',suffix:'/summaries/new',icon:'sparkle',cap:'summaries:write'},{label:'Indicators',suffix:'/indicators',icon:'indicator',cap:'clinical:read'},{label:'Reports',suffix:'/reports/new',icon:'report',cap:'reports:write'}];return <nav className="tabs" aria-label="Patient workspace">{tabs.filter(tab=>!tab.cap||has(tab.cap)).map(({label,suffix,icon})=><Link key={label} className={(suffix?path.includes(suffix.split('/')[1]):path===`/patients/${id}`)?'selected':''} href={`/patients/${encodeURIComponent(id)}${suffix}`}><Icon name={icon} size={17}/>{label}</Link>)}</nav>;}
