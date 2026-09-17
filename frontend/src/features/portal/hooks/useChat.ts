import { useState, useRef, useEffect } from 'react';
import type { Message } from '../components/ChatBubble';
import { config } from '../../../config';

const POLL_INTERVAL_MS = 5000;
const POLL_MAX_ATTEMPTS = 12; // ~1 minute

export function useChat() {
  const [input, setInput] = useState("");
  const [image, setImage] = useState<string | null>(null);
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

  const appendAgentMessage = (text: string) => {
    setMessages(prev => [...prev, { id: `${Date.now()}-${Math.random()}`, sender: 'agent', text }]);
  };

  const pollTicketUntilSettled = async (externalId: string) => {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt++) {
      await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
      try {
        const res = await fetch(`${config.API_BASE_URL}/tenant/tickets/${externalId}`, {
          credentials: 'include'
        });
        if (!res.ok) continue;
        const data = await res.json();

        if (data.status === 'resolved') {
          appendAgentMessage("Update: your request has been resolved.");
          return;
        }
        if (data.status === 'escalated') {
          appendAgentMessage(
            data.github_issue_url
              ? `Update: this was escalated to engineering. Tracking issue: ${data.github_issue_url}`
              : "Update: this was escalated to our engineering team."
          );
          return;
        }
      } catch {
        // Transient network error — keep polling until POLL_MAX_ATTEMPTS.
      }
    }
  };

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
        body: JSON.stringify({ message: userMessage.text })
      });
      const data = await res.json();

      setMessages(prev => prev.filter(m => m.id !== thinkingId));

      if (!res.ok) {
        appendAgentMessage(data.detail || "Sorry, I couldn't process that. Please try again.");
        return;
      }

      appendAgentMessage(data.reply);

      if (data.status === 'investigating' && data.ticket_external_id) {
        pollTicketUntilSettled(data.ticket_external_id);
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
  };
}
