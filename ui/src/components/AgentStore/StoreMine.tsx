import { Loader2, Power, Share2, ShieldCheck, ShieldOff, Sparkles, Trash2 } from "lucide-react";
import type { InstalledSkill } from "../../api/types";
import { CURATED } from "./curated";
import { CreateByVoiceHero } from "./CuratedStore";

/** Running agent presented as «мой помощник» (RU title via curated map). */
export interface MyAgent {
  name: string;
  running: boolean;
}

const CURATED_BY_AGENT = new Map(
  CURATED.filter((e) => e.kind === "agent").map((e) => [e.agentName!, e]),
);

/** One running helper with its consent state: «Отозвать доступ» revokes access
    (sticky — denied until re-enabled); once revoked, «Разрешить снова» restores
    it. «Остановить» stays a separate, lighter pause that keeps consent. */
function RunningAgentCard({
  agent, revoked, busy, onRevoke, onReenable, onToggle,
}: {
  agent: MyAgent;
  revoked: boolean;
  busy: boolean;
  onRevoke: (agent: MyAgent) => void;
  onReenable: (agent: MyAgent) => void;
  onToggle: (agent: MyAgent) => void;
}) {
  const curated = CURATED_BY_AGENT.get(agent.name);
  return (
    <div className="glass glass-interactive p-5 flex items-center gap-4 rounded-2xl">
      <div className="text-3xl w-12 h-12 flex items-center justify-center rounded-xl bg-white/5 shrink-0">
        {curated?.emoji ?? "🤖"}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-base font-medium truncate">{curated?.title ?? agent.name}</div>
        <div
          className={`text-sm mt-0.5 flex items-center gap-1.5 ${
            revoked ? "text-[var(--j-red,#ef4444)]" : "text-[var(--j-green)]"
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-current" />
          {revoked ? "Доступ отозван" : "Работает"}
        </div>
      </div>
      {revoked ? (
        <button
          disabled={busy}
          onClick={() => onReenable(agent)}
          className="px-3 py-2 text-xs rounded-lg bg-[var(--j-cyan)]/15 text-[var(--j-cyan)]
            hover:bg-[var(--j-cyan)]/25 transition flex items-center gap-1.5
            border border-[var(--j-cyan)]/30 disabled:opacity-50"
          title="Снова разрешить доступ к твоим данным"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
          Разрешить снова
        </button>
      ) : (
        <button
          disabled={busy}
          onClick={() => onRevoke(agent)}
          className="px-3 py-2 text-xs rounded-lg bg-[var(--j-amber,#f59e0b)]/15 text-[var(--j-amber,#f59e0b)]
            hover:bg-[var(--j-amber,#f59e0b)]/25 transition flex items-center gap-1.5
            border border-[var(--j-amber,#f59e0b)]/30 disabled:opacity-50"
          title="Забрать доступ к твоим данным — помощник не сможет действовать, пока не разрешишь снова"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldOff className="w-3.5 h-3.5" />}
          Отозвать доступ
        </button>
      )}
      <button
        disabled={busy}
        onClick={() => onToggle(agent)}
        className="px-3 py-2 text-xs rounded-lg bg-white/5 text-white/60 hover:bg-white/10
          hover:text-white/90 transition flex items-center gap-1.5 border border-white/10
          disabled:opacity-50"
        title="Остановить помощника (доступ сохранится)"
      >
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Power className="w-3.5 h-3.5" />}
        Остановить
      </button>
    </div>
  );
}

/** «Мои» — everything the user enabled, installed or created:
    создавать → делиться (или нет) → брать чужое (в Сообществе). */
export function MineSection({
  agents, skills, busyAgent, consents, onToggleAgent, onRevoke, onReenable,
  onPublish, onUninstall, searchQuery,
}: {
  agents: MyAgent[];
  skills: InstalledSkill[];
  busyAgent: string | null;
  consents: Record<string, "approved" | "revoked">;
  onToggleAgent: (agent: MyAgent) => void;
  onRevoke: (agent: MyAgent) => void;
  onReenable: (agent: MyAgent) => void;
  onPublish: (skill: InstalledSkill) => void;
  onUninstall: (skill: InstalledSkill) => void;
  searchQuery: string;
}) {
  const q = searchQuery.trim().toLowerCase();
  const runningAgents = agents.filter((a) => a.running);
  const visibleAgents = q
    ? runningAgents.filter((a) => agentTitle(a.name).toLowerCase().includes(q))
    : runningAgents;
  const userSkills = skills.filter((s) => s.source !== "builtin");
  const visibleSkills = q
    ? userSkills.filter(
        (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q))
    : userSkills;

  if (visibleAgents.length === 0 && visibleSkills.length === 0) {
    return (
      <div>
        <CreateByVoiceHero />
        <div className="glass p-8 text-center rounded-2xl text-sm text-white/40">
          Пока пусто. Создай помощника голосом — или загляни в «Витрину»
          и включи готового в один клик.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {visibleAgents.length > 0 && (
        <div>
          <div className="text-xs text-white/40 uppercase tracking-wider mb-2">
            Работают сейчас
          </div>
          <div className="grid gap-2 stagger">
            {visibleAgents.map((agent) => (
              <RunningAgentCard
                key={agent.name}
                agent={agent}
                revoked={consents[agent.name] === "revoked"}
                busy={busyAgent === agent.name}
                onRevoke={onRevoke}
                onReenable={onReenable}
                onToggle={onToggleAgent}
              />
            ))}
          </div>
        </div>
      )}

      {visibleSkills.length > 0 && (
        <div>
          <div className="text-xs text-white/40 uppercase tracking-wider mb-2">
            Мои навыки
          </div>
          <div className="grid gap-2 stagger">
            {visibleSkills.map((skill) => (
              <div
                key={skill.name}
                className="glass glass-interactive p-5 flex items-center gap-4 rounded-2xl"
              >
                <Sparkles className="w-5 h-5 text-[var(--j-green)] shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-base font-medium truncate">{skill.name}</div>
                  <div className="text-sm text-white/50 truncate mt-1">{skill.description}</div>
                </div>
                <button
                  onClick={() => onPublish(skill)}
                  className="px-3 py-2 text-xs rounded-lg bg-[var(--j-purple)]/15 text-[var(--j-purple,#a855f7)]
                    hover:bg-[var(--j-purple)]/25 transition flex items-center gap-1.5
                    border border-[var(--j-purple)]/30"
                  title="Поделиться с сообществом — навык заработает и в других ассистентах"
                >
                  <Share2 className="w-3.5 h-3.5" />
                  Поделиться
                </button>
                <button
                  onClick={() => onUninstall(skill)}
                  className="text-white/30 hover:text-red-400 hover:bg-red-400/10 transition p-2 rounded-lg"
                  title="Удалить"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function agentTitle(name: string): string {
  return CURATED_BY_AGENT.get(name)?.title ?? name;
}
