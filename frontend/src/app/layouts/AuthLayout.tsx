import type { ReactNode } from 'react';
import { Sparkles } from 'lucide-react';

interface AuthLayoutProps {
  children: ReactNode;
  headline: ReactNode;
  subtext: string;
}

export function AuthLayout({ children, headline, subtext }: AuthLayoutProps) {
  return (
    <div className="min-h-screen flex w-full bg-slate-950 font-sans">
      
      {/* LEFT COLUMN: BRANDING (Hidden on small screens) */}
      <div className="hidden lg:flex w-1/2 relative bg-slate-900 overflow-hidden items-center justify-center border-r border-slate-800">
        {/* Deep ambient glows */}
        <div className="absolute top-[-20%] left-[-20%] w-[80%] h-[80%] bg-indigo-600/30 blur-[150px] rounded-full pointer-events-none mix-blend-screen" />
        <div className="absolute bottom-[-10%] right-[-20%] w-[60%] h-[60%] bg-cyan-500/20 blur-[120px] rounded-full pointer-events-none mix-blend-screen" />
        
        {/* Subtle grid pattern overlay */}
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHBhdGggZD0iTTAgMGg0MHY0MEgwVjB6bTIwIDIwdjIwaDIwVjIwSDIweiIgZmlsbD0iI2ZmZiIgZmlsbC1vcGFjaXR5PSIwLjAyIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiLz48L3N2Zz4=')] opacity-20" />

        <div className="relative z-10 flex flex-col items-center max-w-lg text-center px-12">
          <div className="bg-slate-950/50 p-6 rounded-3xl border border-slate-700/50 mb-8 backdrop-blur-md shadow-2xl relative">
             <div className="absolute inset-0 rounded-3xl bg-gradient-to-tr from-indigo-500/10 to-cyan-400/10" />
             <Sparkles size={64} className="text-indigo-400 drop-shadow-[0_0_15px_rgba(99,102,241,0.5)]" />
          </div>
          
          <h1 className="text-5xl font-extrabold text-white mb-6 tracking-tight">
            {headline}
          </h1>
          <p className="text-slate-400 text-lg leading-relaxed font-light">
            {subtext}
          </p>
        </div>
      </div>

      {/* RIGHT COLUMN: CONTENT */}
      <div className="w-full lg:w-1/2 flex flex-col items-center justify-center p-8 sm:p-12 xl:p-24 bg-[#0B1120] relative">
        <div className="w-full max-w-md">
          {/* Mobile Header (Only visible on mobile) */}
          <div className="flex lg:hidden flex-col items-center mb-10">
            <div className="bg-indigo-500/10 p-3 rounded-xl mb-4 text-indigo-400 border border-indigo-500/20">
              <Sparkles size={24} />
            </div>
            <h2 className="text-2xl font-bold text-white">Aether ITSM</h2>
          </div>

          {children}
        </div>
      </div>
    </div>
  );
}
