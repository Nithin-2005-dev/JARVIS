import {afterEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {api} from '@/lib/api';
import Home from './page';
import Incidents from './incidents/page';
import IncidentDetail from './incidents/[incidentId]/page';
import Services from './services/page';
import ServiceDetail from './services/[serviceId]/page';
import Intelligence from './intelligence/page';
import Recommendations from './recommendations/page';

vi.mock('next/navigation',()=>({usePathname:()=> '/',useParams:()=>({incidentId:'inc-1',serviceId:'db-service'})}));
afterEach(()=>{cleanup();vi.restoreAllMocks()});

describe('Command Center routes backed by API responses',()=>{
 it('shows persisted overview counts and unavailable health state',async()=>{
  vi.spyOn(api,'overview').mockResolvedValue({incident_count:1,active_incident_count:1,critical_high_count:0,open_recommendation_count:0,incidents:[{incident_id:'inc-1',summary:'Checkout delay',severity:'medium',event_ids:['evt-1'],updated_at:'2026-01-01T00:00:00Z',status:'active'}],recent_findings:[],severity_distribution:{medium:1},incident_trend:[],services:[],service_health_available:false});
  render(<Home/>);expect(await screen.findByText('Checkout delay')).toBeInTheDocument();expect(screen.getByText(/Service health telemetry is not available/)).toBeInTheDocument();
 });
 it('renders an incident list and accepts search input',async()=>{
  vi.spyOn(api,'incidents').mockImplementation(async q=>String(q||'').includes('search=')?{items:[],total:0,page:1,page_size:25}:{items:[{incident_id:'inc-1',summary:'Database pool exhausted',severity:'critical',event_ids:['evt'],status:'active',first_observed_at:'2026-01-01T00:00:00Z',last_observed_at:'2026-01-01T00:01:00Z'}],total:1,page:1,page_size:25});
  vi.spyOn(api,'services').mockResolvedValue({items:[],total:0});
  render(<Incidents/>);expect(await screen.findByText('Database pool exhausted')).toBeInTheDocument();fireEvent.change(screen.getByLabelText('Search incidents'),{target:{value:'nothing'}});expect(await screen.findByText('No incidents match these filters.')).toBeInTheDocument();
 });
 it('keeps an inconclusive RCA explicit in the investigation view',async()=>{
  vi.spyOn(api,'incident').mockResolvedValue({incident:{incident_id:'inc-1',summary:'Checkout issue',severity:'high',status:'active',first_observed_at:null,last_observed_at:null},events:[],correlation_evidence:[],history:[],rca_history:[],rca:{assessment_status:'inconclusive',hypotheses:[]},blast_radius:[],intelligence:[],recommendations:[]} as any);
  render(<IncidentDetail/>);expect(await screen.findByText(/Assessment: inconclusive/)).toBeInTheDocument();expect(screen.getByText('No incident events are stored.')).toBeInTheDocument();
 });
 it('renders configured services and health uncertainty',async()=>{
  vi.spyOn(api,'services').mockResolvedValue({items:[{service_id:'db-service',service_name:'Database Service',service_type:'storage',criticality:'critical',business_capability:'payments',related_incidents:[]}],total:1});
  render(<Services/>);expect(await screen.findByText('Database Service')).toBeInTheDocument();expect(screen.getByText(/Health is not inferred/)).toBeInTheDocument();
 });
 it('renders service detail from stored metadata',async()=>{
  vi.spyOn(api,'service').mockResolvedValue({service_id:'db-service',service_name:'Database Service',criticality:'critical',service_type:'storage',graph_services:[],graph_dependencies:[],incoming_dependencies:[],outgoing_dependencies:[],related_incidents:[],findings:[],recommendations:[],analyses:[]});
  render(<ServiceDetail/>);expect(await screen.findByText('Database Service')).toBeInTheDocument();expect(screen.getByText('Health status unavailable')).toBeInTheDocument();
 });
 it('shows detector findings with score interpretation',async()=>{
  vi.spyOn(api,'findings').mockResolvedValue({items:[{finding_id:'f-1',finding_type:'statistical_anomaly',affected_service_ids:['pay-service'],detector:'robust_zscore',score_interpretation:'Heuristic deviation, not probability',window_start:'2026-01-01T00:00:00Z',window_end:'2026-01-01T01:00:00Z'}],total:1});
  render(<Intelligence/>);expect(await screen.findByText('statistical_anomaly')).toBeInTheDocument();expect(screen.getByText('Heuristic deviation, not probability')).toBeInTheDocument();
 });
 it('delegates recommendation lifecycle updates to the API',async()=>{
  vi.spyOn(api,'recommendations').mockResolvedValue({items:[{recommendation_id:'rec-1',title:'Inspect connection metrics',description:'Review current pool usage',supporting_evidence:[{event_id:'evt-1'}],status_history:[],contradictory_evidence:[],recommendation_type:'investigation',priority:'high',confidence_label:'moderate_evidence',risk_level:'low',status:'proposed',verification_steps:['Compare active connections']}],total:1});
  const update=vi.spyOn(api,'update').mockResolvedValue({status:'acknowledged'});
  render(<Recommendations/>);fireEvent.click(await screen.findByRole('button',{name:'Acknowledge'}));expect(await screen.findByText('Status saved.')).toBeInTheDocument();expect(update).toHaveBeenCalledWith('rec-1','acknowledged','');
 });
});
