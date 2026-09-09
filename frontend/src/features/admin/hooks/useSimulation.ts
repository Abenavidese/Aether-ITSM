import { useState } from 'react';

export type Ticket = {
  id: string;
  summary: string;
  user_id: string;
  risk_level: number;
  status: "pending" | "processing" | "paused" | "resolved" | "escalated";
};

const INITIAL_TICKETS: Ticket[] = [
  { id: 'IT-101', summary: 'VPN connection dropping', user_id: 'alice.m', risk_level: 1, status: 'pending' },
  { id: 'IT-102', summary: 'Need Docker installed', user_id: 'bob.d', risk_level: 2, status: 'pending' },
  { id: 'IT-103', summary: 'Grant AWS Admin for Project X', user_id: 'charlie.c', risk_level: 3, status: 'pending' },
  { id: 'IT-104', summary: 'OOM Errors in Prod DB', user_id: 'diana.p', risk_level: 4, status: 'pending' },
];

export function useSimulation() {
  const [activeNode, setActiveNode] = useState<string>("idle");
  const [processingTicketId, setProcessingTicketId] = useState<string | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>(INITIAL_TICKETS);

  const runSimulation = async () => {
    for (let i = 0; i < tickets.length; i++) {
      const t = tickets[i];
      setProcessingTicketId(t.id);
      
      setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'processing' } : pt));
      
      setActiveNode("classify");
      await new Promise(r => setTimeout(r, 1500));
      
      setActiveNode("route");
      await new Promise(r => setTimeout(r, 1000));
      
      if (t.risk_level <= 2) {
        setActiveNode("execute");
        await new Promise(r => setTimeout(r, 2000));
        setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'resolved' } : pt));
      } else if (t.risk_level === 3) {
        setActiveNode("draft");
        setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'paused' } : pt));
        setProcessingTicketId(null);
        break; 
      } else {
        setActiveNode("escalate");
        await new Promise(r => setTimeout(r, 1500));
        setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'escalated' } : pt));
      }
      
      setActiveNode("idle");
      setProcessingTicketId(null);
    }
  };

  const approveTicket = async (id: string, approved: boolean) => {
    setActiveNode("execute");
    await new Promise(r => setTimeout(r, 1500));
    setTickets(prev => prev.map(pt => pt.id === id ? { ...pt, status: approved ? 'resolved' : 'escalated' } : pt));
    setActiveNode("idle");
  };

  return {
    activeNode,
    processingTicketId,
    tickets,
    runSimulation,
    approveTicket,
  };
}
