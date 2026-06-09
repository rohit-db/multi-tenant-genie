import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Sparkles,
  Lock,
  ShieldCheck,
  AlertCircle,
  MessageSquarePlus,
  History,
  ArrowRight,
} from "lucide-react";
import { api, type Tenant } from "@/lib/api";
import { ChatThread, type ChatMessage } from "@/components/ask/ChatThread";
import { ChatComposer } from "@/components/ask/ChatComposer";
import { useTenant } from "@/lib/tenant";

const SAMPLE_QUESTIONS = [
  "How many bookings do I have and what is my total spend?",
  "Show my top 5 routes by total spend",
  "What's my average booking amount, by cabin class?",
  "Which suppliers appear most in my bookings?",
  "Which cabin class do my travelers use most?",
  "What was my busiest booking month this year?",
];

let uidCounter = 0;
function uid(): string {
  uidCounter += 1;
  return `m${Date.now().toString(36)}-${uidCounter}`;
}

export function DemoPage() {
  const { active, selected, loading: tenantsLoading } = useTenant();
  const [searchParams, setSearchParams] = useSearchParams();

  const pick = selected?.tenant_id;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Reset the conversation whenever the active tenant changes.
  useEffect(() => {
    setMessages([]);
    setConversationId(null);
  }, [pick]);

  const ask = useMutation({
    mutationFn: (vars: { id: string; question: string }) =>
      api.ask(pick!, vars.question, {
        inspect: true,
        conversation_id: conversationId,
      }),
    onSuccess: (resp, vars) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === vars.id ? { ...m, answer: resp, pending: false } : m,
        ),
      );
      if (resp.conversation_id) setConversationId(resp.conversation_id);
    },
    onError: (err: Error, vars) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === vars.id ? { ...m, pending: false, error: err.message } : m,
        ),
      );
    },
  });

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const submit = (question: string) => {
    const text = question.trim();
    if (!text || !pick || ask.isPending) return;
    const id = uid();
    setMessages((prev) => [
      ...prev,
      { id, question: text, answer: null, pending: true },
    ]);
    ask.mutate({ id, question: text });
  };

  const newChat = () => {
    setMessages([]);
    setConversationId(null);
    ask.reset();
  };

  // Prefill from Home ("?q=..."): submit once the tenant is ready, then
  // clear the param so it doesn't re-fire on navigation.
  const prefill = searchParams.get("q");
  useEffect(() => {
    if (prefill && pick) {
      submit(prefill);
      searchParams.delete("q");
      setSearchParams(searchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill, pick]);

  const latestInspectorId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].answer?.inspector) return messages[i].id;
    }
    return null;
  }, [messages]);

  if (tenantsLoading) {
    return (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[264px_1fr]">
        <div className="h-96 animate-pulse rounded-xl bg-slate-100" />
        <div className="h-[560px] animate-pulse rounded-xl bg-slate-100" />
      </div>
    );
  }

  if (active.length === 0) {
    return (
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>No active tenants</AlertTitle>
        <AlertDescription>
          Onboard a tenant in the operator console first, then come back to
          explore as that tenant.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="grid animate-fade-in grid-cols-1 gap-6 lg:grid-cols-[264px_1fr]">
      {/* ───────────────── Left rail — conversation nav ───────────────── */}
      <aside className="space-y-4">
        {selected && <IdentityCard tenant={selected} />}

        <Button
          className="w-full justify-start gap-2"
          style={{ background: "var(--brand)" }}
          onClick={newChat}
        >
          <MessageSquarePlus className="h-4 w-4" />
          New chat
        </Button>

        {messages.length > 0 && (
          <RailSection icon={<History className="h-3 w-3" />} label="This chat">
            <ul className="space-y-1">
              {messages
                .filter((m) => m.question)
                .map((m) => (
                  <li key={m.id}>
                    <button
                      type="button"
                      onClick={() =>
                        scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" })
                      }
                      className="block w-full truncate rounded-md px-2.5 py-1.5 text-left text-xs text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                      title={m.question}
                    >
                      {m.question}
                    </button>
                  </li>
                ))}
            </ul>
          </RailSection>
        )}
      </aside>

      {/* ───────────────── Main — chat surface ───────────────── */}
      <section className="flex min-h-[640px] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {/* Header */}
        <div className="flex items-center gap-2.5 border-b border-slate-100 px-5 py-3.5">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-lg shadow-sm"
            style={{ background: "var(--brand)" }}
          >
            <Sparkles className="h-4 w-4 text-white" />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold leading-tight">Ask</div>
            <div className="truncate text-[11px] text-slate-500">
              Travel analytics · as {selected?.tenant_name}
            </div>
          </div>
        </div>

        {/* Body */}
        <div
          ref={scrollRef}
          className="scrollbar-soft flex-1 overflow-y-auto bg-slate-50/40 px-5 py-6"
        >
          {messages.length === 0 ? (
            <Welcome
              tenantName={selected?.tenant_name ?? "this tenant"}
              onAsk={submit}
            />
          ) : (
            <ChatThread messages={messages} latestInspectorId={latestInspectorId} />
          )}
        </div>

        {/* Composer */}
        <div className="border-t border-slate-100 bg-white px-5 py-3.5">
          <ChatComposer
            onSubmit={submit}
            suggestions={SAMPLE_QUESTIONS.slice(0, 4)}
            disabled={!pick || ask.isPending}
            sending={ask.isPending}
            showSuggestions={messages.length > 0}
            placeholder={`Ask as ${selected?.tenant_name ?? "tenant"}…`}
          />
        </div>
      </section>
    </div>
  );
}

// ============================================================================
// Left rail pieces
// ============================================================================

function RailSection({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {icon}
        {label}
      </div>
      {children}
    </div>
  );
}

function IdentityCard({ tenant }: { tenant: Tenant }) {
  return (
    <div className="space-y-2.5 rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-3.5 shadow-sm">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--brand-strong)]">
        <Lock className="h-3 w-3" />
        Active workspace
      </div>
      <div className="text-sm font-semibold text-slate-900">
        {tenant.tenant_name}
      </div>
      <Badge
        variant="outline"
        className="border-emerald-200 bg-emerald-50 text-[11px] text-emerald-700"
      >
        <ShieldCheck className="mr-1 h-3 w-3" />
        Secured by Unity Catalog
      </Badge>
    </div>
  );
}

// ============================================================================
// Welcome — suggested questions only (one clear job: ask)
// ============================================================================

function Welcome({
  tenantName,
  onAsk,
}: {
  tenantName: string;
  onAsk: (q: string) => void;
}) {
  return (
    <div className="mx-auto max-w-3xl space-y-8 py-4">
      <div className="text-center">
        <span
          className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl shadow-md"
          style={{ background: "var(--brand)" }}
        >
          <Sparkles className="h-7 w-7 text-white" />
        </span>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">
          Ask about {tenantName}&rsquo;s travel data
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
          Ask in plain English. Every answer is scoped to {tenantName} by Unity
          Catalog — and each one carries a request-flow inspector that shows
          exactly where that isolation happens.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {SAMPLE_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onAsk(q)}
            className="group flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-700 shadow-sm transition-all hover:border-[var(--brand)] hover:bg-[var(--brand-soft)] hover:shadow"
          >
            <span className="min-w-0">{q}</span>
            <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition-colors group-hover:text-[var(--brand)]" />
          </button>
        ))}
      </div>
    </div>
  );
}
