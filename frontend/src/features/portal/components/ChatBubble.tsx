import { Bot, FileText, User } from 'lucide-react';
import { TypingIndicator } from './TypingIndicator';

// A knowledge-base passage the answer cites as [n] (validated server-side, Fase 14.5).
interface Source {
  n: number;
  filename: string;
  section: string | null;
  page: number | null;
}

interface Message {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  image_url?: string;
  isThinking?: boolean;
  sources?: Source[];
}

function SourceList({ sources }: { sources: Source[] }) {
  return (
    <div className="flex flex-wrap gap-1.5 pt-2 border-t border-slate-700/60">
      {sources.map(s => (
        <span
          key={s.n}
          title={[s.filename, s.section, s.page ? `p. ${s.page}` : null].filter(Boolean).join(' — ')}
          className="inline-flex items-center gap-1 max-w-full px-2 py-0.5 rounded-md bg-slate-900/70 border border-slate-700 text-[11px] text-slate-400"
        >
          <span className="text-indigo-400 font-medium">[{s.n}]</span>
          <FileText size={11} className="shrink-0" />
          <span className="truncate">{s.section ? `${s.filename} · ${s.section}` : s.filename}{s.page ? ` · p. ${s.page}` : ''}</span>
        </span>
      ))}
    </div>
  );
}

interface ChatBubbleProps {
  message: Message;
}

export function ChatBubble({ message }: ChatBubbleProps) {
  return (
    <div className={`flex gap-4 ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
      
      {message.sender === 'agent' && (
        <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-indigo-400 shrink-0 border border-slate-700">
          <Bot size={18} />
        </div>
      )}
      
      <div className={`px-5 py-3 rounded-2xl max-w-[80%] flex flex-col gap-2 ${
        message.sender === 'user' 
          ? 'bg-indigo-600 text-white rounded-tr-sm shadow-lg' 
          : 'bg-slate-800 text-slate-200 rounded-tl-sm border border-slate-700 shadow-lg'
      }`}>
        {message.image_url && (
          <img src={message.image_url} alt="Uploaded attachment" className="rounded-lg max-h-48 object-contain" />
        )}
        {message.isThinking ? (
          <TypingIndicator />
        ) : (
          <p className="leading-relaxed text-sm whitespace-pre-line">{message.text}</p>
        )}
        {message.sources && message.sources.length > 0 && <SourceList sources={message.sources} />}
      </div>

      {message.sender === 'user' && (
        <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-slate-300 shrink-0">
          <User size={18} />
        </div>
      )}
    </div>
  );
}

export type { Message, Source };
