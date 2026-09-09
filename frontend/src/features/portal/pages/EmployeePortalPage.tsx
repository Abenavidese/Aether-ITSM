import { Sparkles } from 'lucide-react';
import { ChatBubble } from '../components/ChatBubble';
import { ChatInput } from '../components/ChatInput';
import { useChat } from '../hooks/useChat';

export function EmployeePortalPage() {
  const { input, setInput, messages, messagesEndRef, handleSubmit } = useChat();

  return (
    <div className="max-w-3xl mx-auto h-[85vh] flex flex-col bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl overflow-hidden relative">
      
      {/* Decorative Header */}
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400" />
      
      <header className="p-6 border-b border-slate-800 flex items-center gap-4 bg-slate-800/20">
        <div className="bg-indigo-500/20 p-3 rounded-xl text-indigo-400">
          <Sparkles size={24} />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Aether Concierge</h1>
          <p className="text-sm text-slate-400">AI-Powered IT Support</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.map(msg => (
          <ChatBubble key={msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      <ChatInput value={input} onChange={setInput} onSubmit={handleSubmit} />
    </div>
  );
}
