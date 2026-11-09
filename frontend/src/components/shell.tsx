'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {FormEvent, useEffect, useState} from 'react';
import {Activity, Lightbulb, Network, Radio, ShieldAlert} from 'lucide-react';
import {api} from '@/lib/api';
const links=[['/','Command Center',Activity],['/incidents','Incidents',ShieldAlert],['/services','Services',Network],['/intelligence','Intelligence',Radio],['/recommendations','Recommendations',Lightbulb]] as const;
type User={username:string;role:string};
export function Shell({children}:{children:React.ReactNode}){
 const path=usePathname();const[user,setUser]=useState<User|null>(null);const[checking,setChecking]=useState(true);const[error,setError]=useState('');const[busy,setBusy]=useState(false);
 useEffect(()=>{const expired=()=>setUser(null);window.addEventListener('jarvis:unauthorized',expired);api.me().then(x=>setUser(x.user)).catch(e=>{if((e as Error).message.includes('API is unavailable'))setError((e as Error).message)}).finally(()=>setChecking(false));return()=>window.removeEventListener('jarvis:unauthorized',expired)},[]);
 async function login(event:FormEvent<HTMLFormElement>){event.preventDefault();setBusy(true);setError('');const fields=new FormData(event.currentTarget);try{const result=await api.login(String(fields.get('username')),String(fields.get('password')));setUser(result.user)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 async function logout(){try{await api.logout()}finally{setUser(null)}}
 if(checking)return <div className="auth-screen" role="status">Checking Command Center session…</div>;
 if(error&&!user)return <main className="auth-screen"><div className="auth-card"><span className="eyebrow">Command Center unavailable</span><p role="alert">{error}</p><button onClick={()=>location.reload()}>Retry</button></div></main>;
 if(!user)return <main className="auth-screen"><form className="auth-card" onSubmit={login}><span className="eyebrow">J.A.R.V.I.S. · Incident Command</span><h1>Sign in</h1><p className="muted">Use an account provisioned by your administrator.</p><label>Username<input className="input" name="username" autoComplete="username" required maxLength={80}/></label><label>Password<input className="input" name="password" type="password" autoComplete="current-password" required maxLength={1024}/></label>{error&&<div className="error-box" role="alert">{error}</div>}<button disabled={busy}>{busy?'Signing in…':'Sign in'}</button></form></main>;
 return <div className="min-h-screen bg-ink text-slate-100"><aside className="sidebar"><Link href="/" className="brand"><span className="brand-mark">J</span><span>J.A.R.V.I.S.<small>INCIDENT COMMAND</small></span></Link><nav>{links.map(([href,label,Icon])=><Link key={href} href={href} className={`nav-link ${path===href||href!=='/'&&path.startsWith(href)?'selected':''}`}><Icon size={17}/>{label}</Link>)}</nav><div className="sidebar-foot"><span className="status-dot"/>SQLite-backed workspace</div></aside><main className="main-content"><header className="topbar"><div className="crumb">Operations <span>/</span> {links.find(([href])=>path===href||href!=='/'&&path.startsWith(href))?.[1]||'Investigation'}</div><div className="toolbar"><span className="api-state">{user.username} · {user.role}</span><button type="button" onClick={logout}>Sign out</button></div></header><div className="page-wrap">{children}</div></main></div>
}
