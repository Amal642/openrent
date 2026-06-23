import { useCallback, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  AlertCircle,
  BarChart2,
  Brain,
  ChevronRight,
  Info,
  Lightbulb,
  Loader2,
  MessageSquare,
  Plus,
  Send,
  ShieldOff,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { postAdvisorChat } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/advisor")({
  head: () => ({
    meta: [
      { title: "AI Advisor - Land Royal" },
      { name: "description", content: "Ask questions about your platform, get troubleshooting help and operational recommendations." },
    ],
  }),
  component: AdvisorPage,
});

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MessageRole = "user" | "assistant";
type ResponseType = "troubleshooting" | "stats" | "recommendation" | "info" | "out_of_scope";

interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  responseType?: ResponseType;
  isError?: boolean;
}

// ---------------------------------------------------------------------------
// Suggested questions
// ---------------------------------------------------------------------------

const SUGGESTED_QUESTIONS = [
  { label: "How many active accounts do we have?", icon: BarChart2, type: "stats" as const },
  { label: "How many phone numbers were collected today?", icon: BarChart2, type: "stats" as const },
  { label: "How many SIMs do we need for South London?", icon: Lightbulb, type: "recommendation" as const },
  { label: "How long will it take to cover Birmingham?", icon: Lightbulb, type: "recommendation" as const },
  { label: "Proxy degraded — what should I do?", icon: Wrench, type: "troubleshooting" as const },
  { label: "Why are messages not sending?", icon: Wrench, type: "troubleshooting" as const },
  { label: "Which area should we target next?", icon: Lightbulb, type: "recommendation" as const },
  { label: "Account cannot log in — how to fix?", icon: Wrench, type: "troubleshooting" as const },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

const TYPE_META: Record<ResponseType, { label: string; color: string; icon: typeof Brain }> = {
  troubleshooting: { label: "Troubleshooting guide", color: "text-blue-500", icon: Wrench },
  stats: { label: "Platform data", color: "text-emerald-500", icon: BarChart2 },
  recommendation: { label: "AI recommendation", color: "text-violet-500", icon: Lightbulb },
  info: { label: "About this advisor", color: "text-primary", icon: Info },
  out_of_scope: { label: "Out of scope", color: "text-muted-foreground", icon: ShieldOff },
};

// Very simple markdown-like renderer: **bold**, bullet lists, section separators
function renderContent(text: string) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];

  lines.forEach((line, idx) => {
    const key = idx;

    if (line.trim() === "---") {
      elements.push(<hr key={key} className="my-3 border-border" />);
      return;
    }

    if (line.trim() === "") {
      elements.push(<div key={key} className="h-2" />);
      return;
    }

    // Parse inline **bold**
    function parseBold(str: string): React.ReactNode[] {
      const parts = str.split(/\*\*(.+?)\*\*/g);
      return parts.map((part, i) =>
        i % 2 === 1 ? <strong key={i} className="font-semibold">{part}</strong> : part
      );
    }

    // Bullet list item
    if (line.startsWith("• ") || line.startsWith("- ")) {
      elements.push(
        <div key={key} className="flex gap-2 text-sm leading-relaxed">
          <span className="mt-1 shrink-0 size-1.5 rounded-full bg-current opacity-50" />
          <span>{parseBold(line.slice(2))}</span>
        </div>
      );
      return;
    }

    // Heading-like line (bold-only line)
    if (line.startsWith("**") && line.endsWith("**") && line.length > 4) {
      elements.push(
        <p key={key} className="text-sm font-semibold mt-1">
          {line.slice(2, -2)}
        </p>
      );
      return;
    }

    // Regular line
    elements.push(
      <p key={key} className="text-sm leading-relaxed">
        {parseBold(line)}
      </p>
    );
  });

  return <div className="space-y-0.5">{elements}</div>;
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function SuggestedQuestionCard({
  question,
  onClick,
}: {
  question: (typeof SUGGESTED_QUESTIONS)[number];
  onClick: (q: string) => void;
}) {
  const Icon = question.icon;
  const colorMap = {
    stats: "text-emerald-500 bg-emerald-500/10",
    recommendation: "text-violet-500 bg-violet-500/10",
    troubleshooting: "text-blue-500 bg-blue-500/10",
  };
  return (
    <button
      type="button"
      onClick={() => onClick(question.label)}
      className="group flex items-center gap-3 rounded-lg border bg-card p-3 text-left text-sm transition hover:border-primary/40 hover:bg-accent/50 hover:shadow-sm"
    >
      <div className={cn("flex size-7 shrink-0 items-center justify-center rounded-md", colorMap[question.type])}>
        <Icon className="size-3.5" />
      </div>
      <span className="flex-1 text-foreground">{question.label}</span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
    </button>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {message.content}
        </div>
      </div>
    );
  }

  const meta = message.responseType ? TYPE_META[message.responseType] : null;
  const MetaIcon = meta?.icon;

  return (
    <div className="flex gap-3">
      <div className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Brain className="size-3.5" />
      </div>
      <div className="flex-1 space-y-2">
        {meta && MetaIcon && (
          <div className={cn("flex items-center gap-1.5 text-xs font-medium", meta.color)}>
            <MetaIcon className="size-3" />
            {meta.label}
          </div>
        )}
        {message.isError ? (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            {message.content}
          </div>
        ) : (
          <div className="rounded-2xl rounded-tl-sm border bg-card px-4 py-3 shadow-sm">
            {renderContent(message.content)}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function AdvisorPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;

      const userMsg: ChatMessage = { id: uid(), role: "user", content: trimmed };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setLoading(true);
      scrollToBottom();

      try {
        const result = await postAdvisorChat(trimmed);
        const assistantMsg: ChatMessage = {
          id: uid(),
          role: "assistant",
          content: result.response,
          responseType: result.type,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch {
        const errMsg: ChatMessage = {
          id: uid(),
          role: "assistant",
          content:
            "Something went wrong. Please check the platform is running and try again.",
          isError: true,
        };
        setMessages((prev) => [...prev, errMsg]);
      } finally {
        setLoading(false);
        scrollToBottom();
        inputRef.current?.focus();
      }
    },
    [loading, scrollToBottom],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const handleNewChat = () => {
    setMessages([]);
    setInput("");
    inputRef.current?.focus();
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b bg-card px-5 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Brain className="size-4" />
          </div>
          <div>
            <h1 className="text-sm font-semibold">AI Advisor</h1>
            <p className="text-xs text-muted-foreground">Ask about accounts, issues, or decisions</p>
          </div>
        </div>
        {!isEmpty && (
          <Button variant="outline" size="sm" onClick={handleNewChat} className="gap-1.5">
            <Plus className="size-3.5" />
            New Chat
          </Button>
        )}
      </div>

      {/* Conversation area */}
      <div className="flex-1 overflow-y-auto">
        {isEmpty ? (
          // Welcome screen
          <div className="flex h-full flex-col items-center justify-center px-4 py-8">
            <div className="mb-4 flex size-14 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Brain className="size-7" />
            </div>
            <h2 className="text-xl font-semibold">Operations Advisor</h2>
            <p className="mt-2 max-w-sm text-center text-sm text-muted-foreground">
              Ask me about your platform data, operational decisions, or get step-by-step help for any issue.
            </p>

            <div className="mt-8 w-full max-w-2xl">
              <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Try asking
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <SuggestedQuestionCard key={q.label} question={q} onClick={sendMessage} />
                ))}
              </div>
            </div>

            <div className="mt-8 flex flex-wrap justify-center gap-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Wrench className="size-3 text-blue-500" />
                Troubleshooting guide
              </span>
              <span className="flex items-center gap-1.5">
                <BarChart2 className="size-3 text-emerald-500" />
                Live platform data
              </span>
              <span className="flex items-center gap-1.5">
                <Lightbulb className="size-3 text-violet-500" />
                AI recommendations
              </span>
              <span className="flex items-center gap-1.5">
                <MessageSquare className="size-3" />
                No chat history saved
              </span>
            </div>
          </div>
        ) : (
          // Messages
          <div className="mx-auto max-w-2xl space-y-5 px-4 py-6">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {loading && (
              <div className="flex gap-3">
                <div className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <Brain className="size-3.5" />
                </div>
                <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border bg-card px-4 py-3 text-sm text-muted-foreground shadow-sm">
                  <Loader2 className="size-4 animate-spin" />
                  Thinking...
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t bg-card px-4 py-3">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about accounts, proxies, coverage, or any issue…"
              rows={1}
              disabled={loading}
              className={cn(
                "w-full resize-none rounded-xl border bg-background px-4 py-3 pr-12 text-sm shadow-sm",
                "placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring",
                "max-h-32 overflow-y-auto",
                loading && "opacity-60",
              )}
              style={{ height: "auto" }}
              onInput={(e) => {
                const el = e.currentTarget;
                el.style.height = "auto";
                el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
              }}
            />
          </div>
          <Button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
            size="icon"
            className="mb-0.5 size-10 shrink-0 rounded-xl"
          >
            {loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-4" />
            )}
          </Button>
        </div>
        <p className="mt-2 text-center text-[11px] text-muted-foreground">
          Press Enter to send · Shift + Enter for new line · Conversations are not saved
        </p>
      </div>
    </div>
  );
}
