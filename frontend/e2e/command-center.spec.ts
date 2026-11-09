import {expect,test} from '@playwright/test';

const apiBase=process.env.E2E_API_BASE_URL||'http://127.0.0.1:8000';
const username=process.env.E2E_USERNAME||'';
const password=process.env.E2E_PASSWORD||'';
async function signIn(page:any){
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button',{name:'Sign in'}).click();
  await expect(page.getByRole('heading',{name:'Command Center'})).toBeVisible();
}

test('responder investigates an incident and updates an evidence-backed recommendation',async({page,context})=>{
  test.skip(!username||!password,'E2E_USERNAME and E2E_PASSWORD must refer to a seeded responder/admin.');
  await signIn(page);
  await page.getByRole('link',{name:'Incidents'}).click();
  const incidentLink=page.locator('a[href^="/incidents/"]').first();
  await expect(incidentLink).toBeVisible();
  await incidentLink.click();
  await expect(page.getByText('Incident timeline')).toBeVisible();
  await expect(page.getByText('Root cause analysis')).toBeVisible();
  await expect(page.getByText(/Hypothetical structural impact/)).toBeVisible();
  const response=await context.request.get(`${apiBase}/api/v1/incidents?limit=1`);
  expect(response.ok()).toBeTruthy();
  await page.getByRole('link',{name:'Intelligence'}).click();
  await expect(page.getByRole('heading',{name:'Findings'})).toBeVisible();
  await page.getByRole('link',{name:'Recommendations'}).click();
  await expect(page.getByRole('heading',{name:'Recommendations'})).toBeVisible();
  const recommendationResponse=await context.request.get(`${apiBase}/api/v1/recommendations?limit=500`);
  const recommendations=(await recommendationResponse.json()).items;
  expect(recommendations.length).toBeGreaterThan(0);
  const recommendationId=recommendations[0].recommendation_id;
  const row=page.locator('tr').filter({hasText:recommendations[0].title}).first();
  await expect(row).toBeVisible();
  await row.getByRole('button',{name:'Acknowledge'}).click();
  await expect(row.getByText('acknowledged')).toBeVisible();
  await row.getByRole('button',{name:'Start'}).click();
  await expect(row.getByText('in_progress')).toBeVisible();
  const details=page.locator('details').filter({hasText:recommendations[0].title}).first();
  await details.locator('summary').click();
  await details.getByLabel('Responder notes').fill('Checked the verification metric in the demo environment.');
  await details.getByRole('button',{name:'Submit feedback'}).click();
  await expect(details.getByText('Feedback saved.')).toBeVisible();
  const history=await context.request.get(`${apiBase}/api/v1/recommendations/${recommendationId}`);
  expect(history.ok()).toBeTruthy();
  const result=await history.json();
  expect(result.recommendation.status).toBe('in_progress');
  expect(result.history.feedback.length).toBeGreaterThan(0);
  await page.getByRole('button',{name:'Sign out'}).click();
  await expect(page.getByRole('heading',{name:'Sign in'})).toBeVisible();
  expect((await context.request.get(`${apiBase}/api/v1/incidents`)).status()).toBe(401);
});

test('competing blast-radius hypotheses remain independently selectable when present',async({page})=>{
  test.skip(!username||!password,'E2E credentials are required.');
  await signIn(page);
  const response=await page.request.get(`${apiBase}/api/v1/incidents?page=1&page_size=100`);
  const incidents=(await response.json()).items;
  let candidate:string|undefined;
  for(const incident of incidents){
    const detail=await page.request.get(`${apiBase}/api/v1/incidents/${encodeURIComponent(incident.incident_id)}`);
    if(!detail.ok())continue;
    const data=await detail.json();
    if((data.rca?.hypotheses?.length||0)>1&&(data.blast_radius?.length||0)>1){candidate=incident.incident_id;break;}
  }
  test.skip(!candidate,'The current real dataset does not contain multiple persisted blast-radius hypotheses.');
  await page.goto(`/incidents/${encodeURIComponent(candidate!)}`);
  const scenarios=page.getByLabel('Blast radius scenario');
  await expect(scenarios).toBeVisible();
  const before=await scenarios.inputValue();
  await scenarios.selectOption({index:1});
  expect(await scenarios.inputValue()).not.toBe(before);
});

test('small viewport navigation remains usable',async({page})=>{
  test.skip(!username||!password,'E2E credentials are required.');
  await page.setViewportSize({width:390,height:844});
  await signIn(page);
  await expect(page.getByRole('link',{name:'Incidents'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
});

test('API failure is rendered instead of hidden behind demo data',async({page})=>{
  test.skip(!username||!password,'E2E credentials are required.');
  await signIn(page);
  await page.route(`${apiBase}/api/v1/overview`,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'test API unavailable'}})}));
  await page.reload();
  await expect(page.getByText('test API unavailable')).toBeVisible();
});
