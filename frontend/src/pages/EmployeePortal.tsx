import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Sparkles } from 'lucide-react';

interface Message {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  isThinking?: boolean;
}

export function EmployeePortal() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'agent', text: "Hello! I'm Aether, your IT Concierge. How can I help you today?" }
  ]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage: Message = { id: Date.now().toString(), sender: 'user', text: input };
    setMessages(prev => [...prev, userMessage]);
    setInput("");

    // Simulate Agent Thinking
    const thinkingId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: thinkingId, sender: 'agent', text: "Analyzing request...", isThinking: true }]);

    // Simulated Agent Logic based on input keywords
    await new Promise(r => setTimeout(r, 2000));
    
    setMessages(prev => prev.filter(m => m.id !== thinkingId));

    let responseText = "I've logged a ticket for this issue and an engineer will look into it shortly.";
    
    if (userMessage.text.toLowerCase().includes("vpn")) {
      responseText = "Done! I've cleared your active VPN sessions. Please try reconnecting now. If you still have issues, let me know.";
    } else if (userMessage.text.toLowerCase().includes("aws") || userMessage.text.toLowerCase().includes("admin")) {
      responseText = "I've drafted a plan to grant you AWS Admin access. Because this is a High Risk (L3) request, it requires security approval. I've sent it to the IT queue and will notify you once approved.";
    }

    setMessages(prev => [...prev, { id: Date.now().toString(), sender: 'agent', text: responseText }]);
  };

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
          <div key={msg.id} className={`flex gap-4 ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            
            {msg.sender === 'agent' && (
              <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-indigo-400 shrink-0 border border-slate-700">
                <Bot size={18} />
              </div>
            )}
            
            <div className={`px-5 py-3 rounded-2xl max-w-[80%] ${
              msg.sender === 'user' 
                ? 'bg-indigo-600 text-white rounded-tr-sm shadow-lg' 
                : 'bg-slate-800 text-slate-200 rounded-tl-sm border border-slate-700 shadow-lg'
            }`}>
              {msg.isThinking ? (
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" />
                  <div className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                  <div className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
                </div>
              ) : (
                <p className="leading-relaxed text-sm">{msg.text}</p>
              )}
            </div>

            {msg.sender === 'user' && (
              <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-slate-300 shrink-0">
                <User size={18} />
              </div>
            )}

          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-6 bg-slate-800/30 border-t border-slate-800">
        <form onSubmit={handleSubmit} className="relative flex items-center">
          <input 
            type="text" 
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Type your issue in plain English (e.g. 'My VPN dropped')"
            className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-4 pr-12 py-4 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all shadow-inner"
          />
          <button 
            type="submit" 
            disabled={!input.trim()}
            className="absolute right-2 p-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:hover:bg-indigo-600 text-white rounded-lg transition-colors"
          >
            <Send size={18} />
          </button>
        </form>
      </div>

    </div>
  );
}
