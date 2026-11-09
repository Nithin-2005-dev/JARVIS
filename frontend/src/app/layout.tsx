import './globals.css';
import {Shell} from '@/components/shell';
export const metadata={title:'J.A.R.V.I.S. Command Center',description:'Evidence-led incident investigation workspace'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body><Shell>{children}</Shell></body></html>}
