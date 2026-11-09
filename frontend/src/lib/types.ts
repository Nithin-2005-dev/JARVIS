// Stage-specific JSON payloads retain their existing wire schema without unsafe recasting at call sites.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyRecord = Record<string, any>;
export type Page<T> = {items:T[]; total:number; page?:number; page_size?:number};
export type IncidentBundle = {incident:AnyRecord;events:AnyRecord[];correlation_evidence:AnyRecord[];history:AnyRecord[];rca_history:AnyRecord[];rca:AnyRecord|null;blast_radius:AnyRecord[];intelligence:AnyRecord[];recommendations:AnyRecord[]};
