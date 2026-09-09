export function TypingIndicator() {
  return (
    <div className="flex items-center gap-2">
      <div className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" />
      <div className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
      <div className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
    </div>
  );
}
