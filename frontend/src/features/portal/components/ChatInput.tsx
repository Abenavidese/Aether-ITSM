import { useRef } from 'react';
import { Send, Paperclip, X } from 'lucide-react';

interface ChatInputProps {
  value: string;
  image: string | null;
  onChange: (value: string) => void;
  onImageChange: (base64: string | null) => void;
  onSubmit: (e: React.FormEvent) => void;
}

export function ChatInput({ value, image, onChange, onImageChange, onSubmit }: ChatInputProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        onImageChange(reader.result as string);
      };
      reader.readAsDataURL(file);
    }
  };
  return (
    <div className="p-4 bg-slate-800/30 border-t border-slate-800">
      {image && (
        <div className="mb-3 relative inline-block">
          <img src={image} alt="Attachment preview" className="h-16 rounded border border-slate-600" />
          <button 
            type="button"
            onClick={() => onImageChange(null)}
            className="absolute -top-2 -right-2 bg-rose-500 text-white rounded-full p-1 shadow-md hover:bg-rose-600"
          >
            <X size={12} />
          </button>
        </div>
      )}
      <form onSubmit={onSubmit} className="relative flex items-center">
        <button 
          type="button" 
          onClick={() => fileInputRef.current?.click()}
          className="absolute left-2 p-2 text-slate-400 hover:text-indigo-400 transition-colors"
        >
          <Paperclip size={20} />
        </button>
        <input 
          type="file" 
          ref={fileInputRef} 
          accept="image/*" 
          className="hidden" 
          onChange={handleFileChange} 
        />
        <input 
          type="text" 
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="Type your issue in plain English or attach a screenshot..."
          className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-12 pr-12 py-4 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all shadow-inner"
        />
        <button 
          type="submit" 
          disabled={!value.trim() && !image}
          className="absolute right-2 p-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:hover:bg-indigo-600 text-white rounded-lg transition-colors"
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
