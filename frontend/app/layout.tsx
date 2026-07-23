import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import Script from 'next/script'
import './globals.css'

const inter     = Inter({ subsets: ['latin'], variable: '--font-sans' })
const jetbrains = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono' })

export const metadata: Metadata = {
  title      : 'WealthEasy - AI Voice Agent Dashboard',
  description: 'Real-time monitoring dashboard for WealthEasy AI voice agent system',
}

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor : '#0A0A0F',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrains.variable} dark`}>
      <body className="antialiased bg-background text-foreground overflow-hidden">
        {children}
        {process.env.NODE_ENV === 'production' && <Analytics />}

      </body>
    </html>
  )
}