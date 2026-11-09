'use client';
import Link from 'next/link';
import {useEffect,useRef,useState} from 'react';
import type {AnyRecord} from '@/lib/types';
export function PageTitle({eyebrow,title,description,action}:{eyebrow?:string;title:string;description?:string;action?:React.ReactNode}){return <div className="page-title"><div>{eyebrow&&<div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description&&<p>{description}</p>}</div>{action}</div>}
export function Panel({title,action,children,className=''}:{title:string;action?:React.ReactNode;children:React.ReactNode;className?:string}){return <section className={`panel ${className}`}><div className="panel-head"><h2>{title}</h2>{action}</div>{children}</section>}
export function State({kind='empty',children}:{kind?:'empty'|'error'|'loading';children:React.ReactNode}){return <div className={`state ${kind}`}>{children}</div>}
export function useApi<T>(load:()=>Promise<T>,deps:unknown[]=[]){const loadRef=useRef(load);useEffect(()=>{loadRef.current=load});const key=JSON.stringify(deps);const[state,setState]=useState<{key:string;data:T|null;error:string;loading:boolean}>({key:'',data:null,error:'',loading:true});useEffect(()=>{let active=true;loadRef.current().then(data=>active&&setState({key,data,error:'',loading:false})).catch(e=>active&&setState({key,data:null,error:e.message||'Unable to load data',loading:false}));return()=>{active=false}},// eslint-disable-next-line react-hooks/exhaustive-deps
deps);const current=state.key===key;return{data:current?state.data:null,error:current?state.error:'',loading:!current||state.loading,setData:(data:T|null)=>setState({key,data,error:'',loading:false})}}
export function Badge({children,tone}:{children:React.ReactNode;tone?:string}){return <span className={`badge ${tone||String(children).toLowerCase().replaceAll('_','-')}`}>{children}</span>}
export function Table({columns,rows,empty='No records are available.'}:{columns:string[];rows:React.ReactNode[][];empty?:string}){if(!rows.length)return <State>{empty}</State>;return <div className="table-scroll"><table><thead><tr>{columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{v}</td>)}</tr>)}</tbody></table></div>}
export const text=(v:unknown)=>v==null||v===''?'—':String(v);
export function IncidentLink({item}:{item:AnyRecord}){return <Link className="row-link" href={`/incidents/${encodeURIComponent(item.incident_id)}`}>{item.summary||item.incident_id}</Link>}
export function fmtDate(value?:string){if(!value)return '—';const d=new Date(value);return Number.isNaN(d.valueOf())?'—':d.toLocaleString()}
