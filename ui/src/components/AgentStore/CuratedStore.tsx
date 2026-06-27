import { Loader2, Mic, Share2 } from "lucide-react";
import type { CommunityCard as CommunityCardData } from "../../api/types";
import { useAppStore } from "../../stores/appStore";
import { CATEGORIES, searchCurated, type CategoryId, type CuratedEntry } from "./curated";
import { StoreCard, type CardState } from "./StoreCards";
import { CommunityCard } from "./CommunityCard";

/** Hero tile — creation is the headline action of the Мастерская. */
export function CreateByVoiceHero() {
  return (
    <button
      onClick={() => useAppStore.getState().setMode("builder")}
      className="w-full mb-6 p-6 rounded-2xl text-left relative overflow-hidden group
        border border-[var(--j-cyan)]/30 bg-gradient-to-r from-[var(--j-cyan)]/15 to-[var(--j-purple)]/10
        hover:from-[var(--j-cyan)]/25 hover:to-[var(--j-purple)]/15 transition-all"
    >
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-full bg-[var(--j-cyan)]/20 flex items-center justify-center
          group-hover:scale-110 transition-transform">
          <Mic className="w-6 h-6 text-[var(--j-cyan)]" />
        </div>
        <div>
          <div className="text-lg font-medium text-white">Создай своего помощника голосом</div>
          <div className="text-sm text-white/50 mt-0.5">
            Расскажи, что нужно — Джарвис соберёт это сам. Без программирования.
          </div>
        </div>
      </div>
    </button>
  );
}

/** «Витрина» — life categories over human cards. */
export function CuratedStore({
  category, onCategory, searchQuery,
  entries, entryState, onPrimary, onSetup,
}: {
  category: CategoryId;
  onCategory: (id: CategoryId) => void;
  searchQuery: string;
  entries: CuratedEntry[];
  entryState: (entry: CuratedEntry) => CardState;
  onPrimary: (entry: CuratedEntry) => void;
  onSetup: (entry: CuratedEntry) => void;
}) {
  const searched = searchCurated(entries, searchQuery);
  const visible = category === "all"
    ? searched
    : searched.filter((e) => e.category === category);

  return (
    <div>
      <CreateByVoiceHero />

      <div className="flex flex-wrap gap-2 mb-6">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            onClick={() => onCategory(c.id)}
            className={`px-3 py-1.5 text-sm rounded-full transition-all border
              ${category === c.id
                ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border-[var(--j-cyan)]/40"
                : "bg-white/5 text-white/50 border-white/10 hover:text-white/80 hover:bg-white/10"
              }`}
          >
            {c.emoji} {c.label}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <div className="glass p-8 text-center rounded-2xl text-sm text-white/40">
          Ничего не нашлось. Попробуй другое слово — или просто скажи Джарвису,
          что нужно, и он создаст это голосом.
        </div>
      ) : (
        <div className="grid gap-2 stagger">
          {visible.map((entry) => (
            <StoreCard
              key={entry.id}
              entry={entry}
              state={entryState(entry)}
              onPrimary={onPrimary}
              onSetup={onSetup}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** «Сообщество» — the merged feed (Supabase UGC ∪ GitHub curated ∪ local),
    deduped server-side. UGC cards carry like/rate/comment; curated cards install
    only. Empty/offline degrades to the «Стань первым» invite (no error wall). */
export function CommunitySection({
  cards, loading, installedNames, installingName, onInstall, onRequireSignIn, searchQuery,
}: {
  cards: CommunityCardData[];
  loading: boolean;
  installedNames: Set<string>;
  installingName: string | null;
  onInstall: (card: CommunityCardData) => void;
  onRequireSignIn: (reason: string) => void;
  searchQuery: string;
}) {
  if (loading) {
    return (
      <div className="glass p-8 text-center rounded-2xl">
        <Loader2 className="w-5 h-5 text-[var(--j-cyan)] animate-spin mx-auto mb-2" />
        <div className="text-xs text-white/40">Загружаю навыки сообщества…</div>
      </div>
    );
  }

  const q = searchQuery.trim().toLowerCase();
  const visible = q
    ? cards.filter((c) =>
        c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q))
    : cards;

  if (visible.length === 0) {
    return (
      <div className="glass p-8 rounded-2xl text-center space-y-3">
        <Share2 className="w-8 h-8 text-[var(--j-cyan)]/60 mx-auto" />
        <div className="text-sm text-white/70">Здесь будут навыки от других людей</div>
        <div className="text-xs text-white/40 max-w-sm mx-auto">
          Создай свой навык голосом и поделись им — он заработает не только в KALI,
          но и в других ассистентах. Стань первым!
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-2 stagger">
      {visible.map((card) => (
        <CommunityCard
          key={card.slug || `${card.source}:${card.name}`}
          card={card}
          installed={card.installed || installedNames.has(card.name)}
          installing={installingName === card.name}
          onInstall={onInstall}
          onRequireSignIn={onRequireSignIn}
        />
      ))}
    </div>
  );
}
