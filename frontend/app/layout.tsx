import type { Metadata } from 'next';
import './globals.css';
import Navbar from '@/components/Layout/Navbar';
import SimulationBanner from '@/components/Layout/SimulationBanner';

export const metadata: Metadata = {
  title: 'AI Trading Platform',
  description: 'AI-powered automated trading platform — Simulation Mode',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <SimulationBanner />
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
