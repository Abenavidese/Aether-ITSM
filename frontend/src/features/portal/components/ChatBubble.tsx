import { Bot, User } from 'lucide-react';
import { TypingIndicator } from './TypingIndicator';

interface Message {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  isThinking?: boolean;
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
      
      <div className={`px-5 py-3 rounded-2xl max-w-[80%] ${
        message.sender === 'user' 
          ? 'bg-indigo-600 text-white rounded-tr-sm shadow-lg' 
          : 'bg-slate-800 text-slate-200 rounded-tl-sm border border-slate-700 shadow-lg'
      }`}>
        {message.isThinking ? (
          <TypingIndicator />
        ) : (
          <p className="leading-relaxed text-sm">{message.text}</p>
        )}
      </div>

      {message.sender === 'user' && (
        <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-slate-300 shrink-0">
          <User size={18} />
        </div>
      )}
    </div>
  );
}

export type { Message };
