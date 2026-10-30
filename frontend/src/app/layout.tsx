import type { Metadata } from 'next';
import { Plus_Jakarta_Sans } from 'next/font/google';
import { AuthProvider } from '@/lib/auth';
import { SurfaceEffects } from '@/components/surface-effects';
import './globals.css';
import './effects.css';

const jakarta = Plus_Jakarta_Sans({ subsets: ['latin'], display: 'swap', variable: '--font-jakarta' });

export const metadata: Metadata = {
  title: 'Sanctum | Clinical workspace',
  description: 'Clinic controlled therapy records',
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={jakarta.variable}>
      <body>
        <SurfaceEffects/>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
