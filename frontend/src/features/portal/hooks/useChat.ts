import { useState, useRef, useEffect, useCallback } from 'react';
import type { Message, Source } from '../components/ChatBubble';
import type { AppNotification } from './useNotifications';
import { config } from '../../../config';
import { apiErrorMessage } from '../../../utils/apiError';

export function useChat() {
  const [input, setInput] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'agent', text: "Hello! I'm Aether, your IT Concierge. How can I help you today?" }
  ]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Tickets this conversation opened: their notifications are posted here too.
  const openedTickets = useRef<Set<string>>(new Set());

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const appendAgentMessage = (text: string, sources?: Source[]) => {
    setMessages(prev => [...prev, { id: `${Date.now()}-${Math.random()}`, sender: 'agent', text, sources }]);
  };

  // Fase 16: ticket progress arrives as notifications (the same ones the bell
  // shows), instead of polling the ticket itself — which also exposed the
  // engineering repo's issue URL to employees.
  const onNotification = useCallback((n: AppNotification) => {
    if (n.kind === 'ticket_opened') return;  // the chat reply already said so
    if (n.ticket_external_id && openedTickets.current.has(n.ticket_external_id)) {
      setMessages(prev => [...prev, { id: `n-${n.id}`, sender: 'agent', text: `🔔 ${n.title}\n\n${n.body}` }]);
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() && !image) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      sender: 'user',
      text: input || "Sent an attachment.",
      image_url: image || undefined
    };

    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setImage(null);

    const thinkingId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: thinkingId, sender: 'agent', text: "Analyzing request...", isThinking: true }]);

    try {
      const res = await fetch(`${config.API_BASE_URL}/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage.text, image_base64: userMessage.image_url ?? null })
      });
      const data = await res.json();

      setMessages(prev => prev.filter(m => m.id !== thinkingId));

      if (!res.ok) {
        appendAgentMessage(apiErrorMessage(data, "Sorry, I couldn't process that. Please try again."));
        return;
      }

      appendAgentMessage(data.reply, data.sources);

      if (data.status === 'investigating' && data.ticket_external_id) {
        openedTickets.current.add(data.ticket_external_id);
      }
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== thinkingId));
      appendAgentMessage("Failed to reach Aether. Please check your connection and try again.");
    }
  };

  return {
    input,
    setInput,
    image,
    setImage,
    messages,
    messagesEndRef,
    handleSubmit,
    onNotification,
  };
}
