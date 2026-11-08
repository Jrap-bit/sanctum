'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth';
import type { Capability } from '@/lib/types';
import { Icon, type IconName } from './icon';
import { Modal } from './modal';

const navigation: { href: string; label: string; icon: IconName; cap: Capability }[] = [
  { href: '/patients', label: 'Patients', icon: 'patient', cap: 'patients:read' },
  { href: '/admin/users', label: 'People', icon: 'users', cap: 'users:manage' },
  { href: '/access/grants', label: 'Access requests', icon: 'key', cap: 'grants:request' },
  { href: '/oversight/rules', label: 'Decision rules', icon: 'rules', cap: 'rules:publish' },
  { href: '/audit', label: 'Activity log', icon: 'audit', cap: 'audit:read' },
  { href: '/admin/operations', label: 'System health', icon: 'activity', cap: 'operations:manage' },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading, error, refresh, has, logout } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const menuButton = useRef<HTMLButtonElement>(null);
  const accountMenu = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    // Close only when interaction moves outside. Closing <details> during blur
    // can interrupt the browser's focus handling when its plain text is clicked.
    const closeAccountOutside = (event: Event) => {
      const menu = accountMenu.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) {
        menu.open = false;
      }
    };
    document.addEventListener('pointerdown', closeAccountOutside);
    document.addEventListener('focusin', closeAccountOutside);
    return () => {
      document.removeEventListener('pointerdown', closeAccountOutside);
      document.removeEventListener('focusin', closeAccountOutside);
    };
  }, []);

  if (loading) return <div className="center-screen"><span className="spinner"/>Opening workspace…</div>;
  if (!user) return <main className="center-screen"><div className="state" role="alert"><strong>{error ? 'Workspace unavailable' : 'Sign in to continue'}</strong>{error && <p>{error.message}</p>}<div className="row">{error && <button className="button" onClick={() => void refresh().catch(() => {})}>Retry connection</button>}<Link className="button primary" href="/login">Sign in</Link></div></div></main>;

  const links = navigation.filter(link => has(link.cap)
    || (link.href === '/access/grants' && has('grants:approve'))
    || (link.href === '/patients' && has('clinical:read')));
  const signOut = async () => {
    if (signingOut) return;
    setSigningOut(true); setLogoutError('');
    try { await logout(); }
    catch { setLogoutError('Sign-out could not be confirmed. Check your connection and try again.'); setSigningOut(false); }
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
      <details ref={accountMenu} className="workspace-account" onKeyDown={event => {
        if (event.key === 'Escape') {
          event.currentTarget.open = false;
          event.currentTarget.querySelector('summary')?.focus();
          event.stopPropagation();
        }
      }}>
        <summary aria-label={`Account: ${user.displayName}`} title={user.displayName}>
          <span className="account-avatar">{user.displayName?.charAt(0) || 'U'}</span><Icon name="chevron" size={14}/>
        </summary>
        <div className="account-popover">
          <strong>{user.displayName}</strong><span>{user.username}</span>
          <button type="button" onClick={() => { setLogoutError(''); setConfirmLogout(true); }}><Icon name="logout" size={18}/>Sign out</button>
        </div>
      </details>
    </header>
    <Modal open={confirmLogout} busy={signingOut} onClose={() => setConfirmLogout(false)} labelledBy="logout-title" describedBy="logout-description">
      <h2 id="logout-title">Sign out?</h2><p id="logout-description">Save any open work before leaving.</p>
      {logoutError && <p className="notice danger" role="alert">{logoutError}</p>}
      <div className="actions"><button type="button" autoFocus className="button ghost" disabled={signingOut} onClick={() => setConfirmLogout(false)}>Cancel</button>
      <button type="button" className="button danger" disabled={signingOut} onClick={() => void signOut()}>{signingOut ? 'Signing out…' : 'Confirm sign out'}</button></div>
    </Modal>
    <main id="workspace-content" className="main-content" tabIndex={-1}>{children}</main>
  </div>;
}

export function Require({cap,children}:{cap:Capability;children:React.ReactNode}){const {has,loading}=useAuth();if(loading)return <div className="state">Checking access…</div>;if(!has(cap))return <div className="state error" role="alert"><strong>Access denied</strong><p>Your account needs access to this area.</p></div>;return <>{children}</>;}
export function PatientTabs({id}:{id:string}){const path=usePathname();const {has}=useAuth();const tabs:{label:string;suffix:string;icon:IconName;cap?:Capability}[]=[{label:'Overview',suffix:'',icon:'home'},{label:'Sessions',suffix:'/sessions/new',icon:'notes',cap:'clinical:write'},{label:'Documents',suffix:'/documents',icon:'document',cap:'clinical:read'},{label:'AI summaries',suffix:'/summaries/new',icon:'sparkle',cap:'summaries:write'},{label:'Indicators',suffix:'/indicators',icon:'indicator',cap:'clinical:read'},{label:'Reports',suffix:'/reports/new',icon:'report',cap:'reports:write'}];return <nav className="tabs" aria-label="Patient workspace">{tabs.filter(tab=>!tab.cap||has(tab.cap)).map(({label,suffix,icon})=><Link key={label} aria-current={(suffix?path.includes(suffix.split('/')[1]):path===`/patients/${id}`)?'page':undefined} className={(suffix?path.includes(suffix.split('/')[1]):path===`/patients/${id}`)?'selected':''} href={`/patients/${encodeURIComponent(id)}${suffix}`}><Icon name={icon} size={17}/>{label}</Link>)}</nav>;}
