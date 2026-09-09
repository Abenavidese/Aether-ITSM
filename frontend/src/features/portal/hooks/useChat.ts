import { useState, useRef, useEffect } from 'react';
import type { Message } from '../components/ChatBubble';

export function useChat() {
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

  return {
    input,
    setInput,
    messages,
    messagesEndRef,
    handleSubmit,
  };
}
