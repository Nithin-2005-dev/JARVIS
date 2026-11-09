import type {AnyRecord, IncidentBundle, Page} from './types';
const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000').replace(/\/$/,'');
export async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const method=(init?.method||'GET').toUpperCase();
  const csrf=method==='GET'?undefined:readCookie('jarvis_csrf');
  let response:Response;
  try { response = await fetch(`${BASE}/api/v1${path}`,{...init,credentials:'include',headers:{'Content-Type':'application/json',...(csrf?{'X-CSRF-Token':csrf}:{}),...init?.headers},cache:'no-store'}); }
  catch { throw new Error('The J.A.R.V.I.S. API is unavailable. Check that the backend is running.'); }
  if(!response.ok){ if(response.status===401&&typeof window!=='undefined')window.dispatchEvent(new Event('jarvis:unauthorized'));const body=await response.json().catch(()=>null); throw new Error(body?.detail?.message || body?.error?.message || `Request failed (${response.status})`); }
  return response.json() as Promise<T>;
}
export const api={
  me:()=>request<AnyRecord>('/auth/me'),
  csrf:()=>request<{csrf_token:string}>('/auth/csrf'),
  async login(username:string,password:string){await this.csrf();return request<AnyRecord>('/auth/login',{method:'POST',body:JSON.stringify({username,password})})},
  logout:()=>request<AnyRecord>('/auth/logout',{method:'POST'}),
  overview:()=>request<AnyRecord>('/overview'), incidents:(q='')=>request<Page<AnyRecord>>(`/incidents${q}`),
  incident:(id:string)=>request<IncidentBundle>(`/incidents/${encodeURIComponent(id)}`),
  services:()=>request<Page<AnyRecord>>('/services'), service:(id:string)=>request<AnyRecord>(`/services/${encodeURIComponent(id)}`),
  findings:()=>request<Page<AnyRecord>>('/intelligence/findings'), recommendations:(q='')=>request<Page<AnyRecord>>(`/recommendations${q}`),
  recommendation:(id:string)=>request<AnyRecord>(`/recommendations/${encodeURIComponent(id)}`),
  update:(id:string,status:string,reason='')=>request<AnyRecord>(`/recommendations/${encodeURIComponent(id)}/status`,{method:'PATCH',body:JSON.stringify({status,reason})}),
  feedback:(id:string,payload:AnyRecord)=>request<AnyRecord>(`/recommendations/${encodeURIComponent(id)}/feedback`,{method:'POST',body:JSON.stringify(payload)}),
  history:()=>request<AnyRecord>('/history')
};

function readCookie(name:string):string|undefined{
  if(typeof document==='undefined')return undefined;
  const prefix=`${name}=`;
  return document.cookie.split('; ').find(x=>x.startsWith(prefix))?.slice(prefix.length);
}
