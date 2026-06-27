import { useState } from "react";
import { Check, Loader2, Mail, X } from "lucide-react";
import { api } from "../../api/client";

/** KALI magic-link sign-in — email → OTP code → session. NOT Google/Apple OAuth
    (§7 anti-pivot). Surfaced honestly when a signed-out rate/comment returns
    "sign-in required"; this is the ONLY sign-in affordance in «Сообщество». */
export function MagicLinkDialog({
  reason, onClose, onSignedIn,
}: {
  /** Plain-RU line explaining why sign-in is needed (e.g. "чтобы оценить навык"). */
  reason?: string;
  onClose: () => void;
  onSignedIn: () => void;
}) {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const sendLink = async () => {
    const addr = email.trim();
    if (!addr) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.communityMagicLink(addr);
      if (res.status === "sent") {
        setStep("code");
        setNotice("Мы отправили код на почту. Введи его ниже.");
      } else if (res.status === "unconfigured") {
        setError("Вход в аккаунт пока недоступен. Лайки работают и без входа.");
      } else {
        setError("Не получилось отправить код. Проверь адрес и попробуй ещё раз.");
      }
    } catch {
      setError("Не получилось отправить код. Попробуй позже.");
    }
    setBusy(false);
  };

  const verify = async () => {
    const code = token.trim();
    if (!code) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.communityVerify(email.trim(), code);
      if (res.status === "signed_in") {
        onSignedIn();
        onClose();
      } else {
        setError("Код не подошёл. Проверь и введи ещё раз.");
      }
    } catch {
      setError("Не получилось войти. Попробуй позже.");
    }
    setBusy(false);
  };

  return (
    <div
      className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div className="glass p-6 max-w-md w-full rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 mb-1">
          <span className="w-9 h-9 rounded-full bg-[var(--j-cyan)]/15 flex items-center justify-center">
            <Mail className="w-4.5 h-4.5 text-[var(--j-cyan)]" />
          </span>
          <h3 className="text-base font-medium">Войти в KALI</h3>
          <button onClick={onClose} className="ml-auto text-white/30 hover:text-white/60">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-white/60 mb-4">
          {reason ? `${reason} ` : ""}Вход — по ссылке на почту, без паролей и без
          Google или Apple. Лайки работают и без входа.
        </p>

        {step === "email" ? (
          <div className="space-y-3">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="твоя@почта.ru"
              className="w-full px-3 py-2 text-sm rounded-lg bg-black/40 border border-white/10
                outline-none focus:border-[var(--j-cyan)]/40 text-white/90"
            />
            {error && <div className="text-xs text-red-400">{error}</div>}
            <button
              onClick={sendLink}
              disabled={!email.trim() || busy}
              className="w-full px-3 py-2.5 text-sm rounded-lg bg-[var(--j-cyan)]/20 hover:bg-[var(--j-cyan)]/30
                transition flex items-center justify-center gap-1.5 text-[var(--j-cyan)]
                border border-[var(--j-cyan)]/30 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
              {busy ? "Отправляю…" : "Прислать ссылку для входа"}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {notice && <div className="text-xs text-white/50">{notice}</div>}
            <input
              type="text"
              inputMode="numeric"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Код из письма"
              className="w-full px-3 py-2 text-sm rounded-lg bg-black/40 border border-white/10
                outline-none focus:border-[var(--j-cyan)]/40 text-white/90 tracking-widest"
            />
            {error && <div className="text-xs text-red-400">{error}</div>}
            <button
              onClick={verify}
              disabled={!token.trim() || busy}
              className="w-full px-3 py-2.5 text-sm rounded-lg bg-[var(--j-cyan)]/20 hover:bg-[var(--j-cyan)]/30
                transition flex items-center justify-center gap-1.5 text-[var(--j-cyan)]
                border border-[var(--j-cyan)]/30 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {busy ? "Проверяю…" : "Войти"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
