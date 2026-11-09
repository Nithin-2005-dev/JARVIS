import type {AnyRecord, IncidentBundle, Page} from './types';
const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000').replace(/\/$/,'');
export async function request<T>(path:string, init?:RequestInit):Promise<T>{
  let response:Response;
  try { response = await fetch(`${BASE}/api/v1${path}`,{...init,headers:{'Content-Type':'application/json',...init?.headers},cache:'no-store'}); }
  catch { throw new Error('The J.A.R.V.I.S. API is unavailable. Check that the backend is running.'); }
  if(!response.ok){ const body=await response.json().catch(()=>null); throw new Error(body?.detail?.message || body?.error?.message || `Request failed (${response.status})`); }
  return response.json() as Promise<T>;
}
export const api={
  overview:()=>request<AnyRecord>('/overview'), incidents:(q='')=>request<Page<AnyRecord>>(`/incidents${q}`),
  incident:(id:string)=>request<IncidentBundle>(`/incidents/${encodeURIComponent(id)}`),
  services:()=>request<Page<AnyRecord>>('/services'), service:(id:string)=>request<AnyRecord>(`/services/${encodeURIComponent(id)}`),
  findings:()=>request<Page<AnyRecord>>('/intelligence/findings'), recommendations:(q='')=>request<Page<AnyRecord>>(`/recommendations${q}`),
  recommendation:(id:string)=>request<AnyRecord>(`/recommendations/${encodeURIComponent(id)}`),
  update:(id:string,status:string,reason='')=>request<AnyRecord>(`/recommendations/${encodeURIComponent(id)}/status`,{method:'PATCH',body:JSON.stringify({status,reason})}),
  history:()=>request<AnyRecord>('/history')
};
