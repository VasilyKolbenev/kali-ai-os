import { useState } from "react";
import { Download, Heart, Loader2, MessageCircle, Send, Star } from "lucide-react";
import type { CommunityCard as Card, CommunityComment } from "../../api/types";
import { api } from "../../api/client";

/** A single «Сообщество» card: install + the social affordances (like / rate /
    comment). UGC cards (a Supabase slug) get the full social row; curated GitHub
    cards have no slug, so they show install only. Likes are anonymous (device-id,
    optimistic). Rate/comment are account-gated: a "sign-in required" result
    raises `onRequireSignIn` (→ magic-link prompt) instead of faking success. */
export function CommunityCard({
  card, installed, installing, onInstall, onRequireSignIn,
}: {
  card: Card;
  installed: boolean;
  installing: boolean;
  onInstall: (card: Card) => void;
  onRequireSignIn: (reason: string) => void;
}) {
  const hasSocial = card.source === "ugc" && !!card.slug;

  // Optimistic like state, seeded from the merged card's counts.
  const [liked, setLiked] = useState(card.liked);
  const [likeCount, setLikeCount] = useState(card.like_count);
  const [likeBusy, setLikeBusy] = useState(false);

  const [avg, setAvg] = useState(card.avg_rating);
  const [ratingCount, setRatingCount] = useState(card.rating_count);
  const [myStars, setMyStars] = useState<number | null>(card.rated);

  const [commentsOpen, setCommentsOpen] = useState(false);
  const [comments, setComments] = useState<CommunityComment[] | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentBusy, setCommentBusy] = useState(false);
  const [commentNote, setCommentNote] = useState<string | null>(null);

  const toggleLike = async () => {
    if (likeBusy || !card.slug) return;
    const next = !liked;
    // Optimistic flip.
    setLiked(next);
    setLikeCount((c) => Math.max(0, c + (next ? 1 : -1)));
    setLikeBusy(true);
    try {
      const res = next ? await api.catalogLike(card.slug) : await api.catalogUnlike(card.slug);
      if (res.status !== "ok" && res.status !== "noop") {
        // Roll back on a non-success (offline/error) — never a fake like.
        setLiked(!next);
        setLikeCount((c) => Math.max(0, c + (next ? -1 : 1)));
      }
    } catch {
      setLiked(!next);
      setLikeCount((c) => Math.max(0, c + (next ? -1 : 1)));
    }
    setLikeBusy(false);
  };

  const rate = async (stars: number) => {
    if (!card.slug) return;
    try {
      const res = await api.catalogRate(card.slug, stars);
      if (res.status === "sign-in required") {
        onRequireSignIn("Чтобы оценить навык, войди в KALI.");
        return;
      }
      if (res.status === "ok") {
        // Reflect the new own-rating into the local average (approximate; the
        // authoritative avg refreshes on the next feed load).
        const prev = myStars;
        const count = prev == null ? ratingCount + 1 : ratingCount;
        const sum = avg * ratingCount - (prev ?? 0) + stars;
        setMyStars(stars);
        setRatingCount(count);
        setAvg(count > 0 ? Math.round((sum / count) * 100) / 100 : stars);
      }
    } catch {
      /* leave prior rating; the user can retry */
    }
  };

  const openComments = async () => {
    const next = !commentsOpen;
    setCommentsOpen(next);
    if (next && comments === null && card.slug) {
      try {
        const res = await api.catalogComments(card.slug);
        setComments(res.comments || []);
      } catch {
        setComments([]);
      }
    }
  };

  const submitComment = async () => {
    const text = commentDraft.trim();
    if (!text || !card.slug || commentBusy) return;
    setCommentBusy(true);
    setCommentNote(null);
    try {
      const res = await api.catalogComment(card.slug, text);
      if (res.status === "sign-in required") {
        onRequireSignIn("Чтобы оставить отзыв, войди в KALI.");
      } else if (res.status === "pending") {
        setCommentDraft("");
        setCommentNote("Отзыв отправлен — появится после проверки.");
      } else if (res.status === "invalid") {
        setCommentNote("Отзыв слишком короткий или слишком длинный.");
      } else {
        setCommentNote("Не получилось отправить отзыв.");
      }
    } catch {
      setCommentNote("Не получилось отправить отзыв.");
    }
    setCommentBusy(false);
  };

  return (
    <div className="glass glass-interactive p-5 rounded-2xl">
      <div className="flex items-center gap-4">
        <div className="text-2xl w-12 h-12 flex items-center justify-center rounded-xl bg-white/5 shrink-0">
          🤝
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-base font-medium truncate">{card.name}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--j-purple)]/15
              text-[var(--j-purple,#a855f7)] border border-[var(--j-purple)]/30">
              работает везде
            </span>
          </div>
          <div className="text-sm text-white/50 truncate mt-1">{card.description}</div>
          {card.creator_handle && (
            <div className="text-xs text-white/30 mt-1 truncate">@{card.creator_handle}</div>
          )}
        </div>
        {installed ? (
          <span className="px-3 py-1.5 text-xs rounded-lg bg-[var(--j-green)]/10 text-[var(--j-green)] shrink-0">
            Установлено
          </span>
        ) : (
          <button
            disabled={installing}
            onClick={() => onInstall(card)}
            className="px-4 py-2 text-sm rounded-lg bg-[var(--j-cyan)]/15 text-[var(--j-cyan)]
              hover:bg-[var(--j-cyan)]/25 transition flex items-center gap-1.5 shrink-0
              border border-[var(--j-cyan)]/30 disabled:opacity-50"
          >
            {installing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
            {installing ? "Секунду…" : "Установить"}
          </button>
        )}
      </div>

      {hasSocial && (
        <div className="mt-4 pt-3 border-t border-white/5 flex items-center gap-4 text-sm">
          {/* Like — anon device-id, optimistic, no sign-in. */}
          <button
            onClick={toggleLike}
            disabled={likeBusy}
            aria-pressed={liked}
            aria-label="Нравится"
            className={`flex items-center gap-1.5 transition disabled:opacity-50
              ${liked ? "text-[var(--j-red,#ef4444)]" : "text-white/40 hover:text-white/70"}`}
          >
            <Heart className={`w-4 h-4 ${liked ? "fill-current" : ""}`} />
            <span>{likeCount}</span>
          </button>

          {/* Rate — 1-5 stars, account-gated (sign-in prompt on signed-out). */}
          <div className="flex items-center gap-0.5" role="group" aria-label="Оценить">
            {[1, 2, 3, 4, 5].map((s) => (
              <button
                key={s}
                onClick={() => rate(s)}
                aria-label={`Оценить на ${s}`}
                className="p-0.5 text-white/30 hover:text-[var(--j-amber,#f59e0b)] transition"
              >
                <Star
                  className={`w-4 h-4 ${
                    (myStars ?? 0) >= s
                      ? "fill-[var(--j-amber,#f59e0b)] text-[var(--j-amber,#f59e0b)]"
                      : ""
                  }`}
                />
              </button>
            ))}
            {ratingCount > 0 && (
              <span className="ml-1.5 text-xs text-white/40">
                {avg} · {ratingCount}
              </span>
            )}
          </div>

          {/* Comments toggle. */}
          <button
            onClick={openComments}
            className="flex items-center gap-1.5 text-white/40 hover:text-white/70 transition ml-auto"
          >
            <MessageCircle className="w-4 h-4" />
            <span className="text-xs">Отзывы</span>
          </button>
        </div>
      )}

      {hasSocial && commentsOpen && (
        <div className="mt-3 space-y-3">
          <div className="space-y-2">
            {comments === null ? (
              <div className="text-xs text-white/30 flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin" /> Загружаю отзывы…
              </div>
            ) : comments.length === 0 ? (
              <div className="text-xs text-white/30">Пока нет отзывов. Будь первым.</div>
            ) : (
              comments.map((c) => (
                <div key={c.id ?? c.created_at} className="text-sm text-white/70 bg-white/5 rounded-lg px-3 py-2">
                  {c.body}
                </div>
              ))
            )}
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={commentDraft}
              onChange={(e) => setCommentDraft(e.target.value)}
              placeholder="Оставить отзыв…"
              className="flex-1 px-3 py-2 text-sm rounded-lg bg-black/40 border border-white/10
                outline-none focus:border-[var(--j-cyan)]/40 text-white/90"
            />
            <button
              onClick={submitComment}
              disabled={!commentDraft.trim() || commentBusy}
              aria-label="Отправить отзыв"
              className="px-3 py-2 rounded-lg bg-[var(--j-cyan)]/15 text-[var(--j-cyan)]
                hover:bg-[var(--j-cyan)]/25 transition border border-[var(--j-cyan)]/30
                disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {commentBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
          {commentNote && <div className="text-xs text-white/50">{commentNote}</div>}
        </div>
      )}
    </div>
  );
}
