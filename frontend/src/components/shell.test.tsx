import {afterEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {api} from '@/lib/api';
import {Shell} from './shell';
vi.mock('next/navigation',()=>({usePathname:()=>'/'}));
afterEach(()=>{cleanup();vi.restoreAllMocks()});
describe('authenticated Command Center shell',()=>{
 it('shows login and navigates into the app after a successful sign-in',async()=>{
  vi.spyOn(api,'me').mockRejectedValue(new Error('Sign in to access this resource.'));
  vi.spyOn(api,'login').mockResolvedValue({user:{username:'operator',role:'responder'}});
  render(<Shell><div>Overview content</div></Shell>);
  fireEvent.change(await screen.findByLabelText('Username'),{target:{value:'operator'}});
  fireEvent.change(screen.getByLabelText('Password'),{target:{value:'example secret'}});
  fireEvent.click(screen.getByRole('button',{name:'Sign in'}));
  expect(await screen.findByText('Overview content')).toBeInTheDocument();
  expect(screen.getByText('operator · responder')).toBeInTheDocument();
 });
});
