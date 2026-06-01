import { useEffect, useState } from "react";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { api } from "../../../api/client";
import { Loader2, DownloadCloud, CheckCircle2 } from "lucide-react";

export function ModelsDownloadStep() {
  const advance = useOnboardingStore((s) => s.advance);
  const progressDict = useOnboardingStore((s) => s.modelProgress);
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Calculate aggregate progress
  const progressValues = Object.values(progressDict);
  const totalBytes = progressValues.reduce((acc, p) => acc + p.total_bytes, 0);
  const downloadedBytes = progressValues.reduce((acc, p) => acc + p.downloaded_bytes, 0);
  
  const percent = totalBytes > 0 ? Math.round((downloadedBytes / totalBytes) * 100) : 0;
  const currentFile = progressValues.length > 0 ? progressValues[progressValues.length - 1].filename : "Подготовка...";
  
  useEffect(() => {
    let mounted = true;
    
    async function checkAndDownload() {
      try {
        const status = await api.modelsStatus();
        if (status.ready) {
          if (mounted) advance();
          return;
        }
        
        if (mounted) {
          setLoading(false);
          await api.modelsDownload();
        }
      } catch (err: any) {
        if (mounted) setError(err.message || "Failed to check models");
      }
    }
    
    checkAndDownload();
    return () => { mounted = false; };
  }, [advance]);

  if (loading) {
    return (
      <div className="flex flex-col items-center gap-4 text-[var(--j-cyan-dim)]">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p className="text-sm tracking-widest uppercase">Анализ компонентов...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass p-8 max-w-md w-full flex flex-col items-center text-center gap-4 border-red-500/30">
        <div className="w-16 h-16 rounded-full bg-red-500/10 flex items-center justify-center text-red-400">
          <DownloadCloud className="w-8 h-8" />
        </div>
        <h2 className="text-xl font-medium text-white">Ошибка сети</h2>
        <p className="text-sm text-red-400/80">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="mt-4 px-6 py-2 rounded-lg bg-[var(--j-surface-hover)] border border-[var(--j-border)] hover:bg-[var(--j-surface-soft)] transition"
        >
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div className="glass glass-interactive p-10 max-w-lg w-full flex flex-col items-center text-center gap-8 relative overflow-hidden group">
      {/* Decorative background glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[150%] h-[150%] bg-[var(--j-cyan)] opacity-[0.03] blur-[100px] pointer-events-none" />

      <div className="w-20 h-20 rounded-full bg-gradient-to-b from-[var(--j-cyan)]/20 to-transparent flex items-center justify-center text-[var(--j-cyan)] shadow-[0_0_30px_rgba(0,212,255,0.2)]">
        {percent === 100 ? (
          <CheckCircle2 className="w-10 h-10 text-[var(--j-green)] drop-shadow-[0_0_10px_var(--j-green)]" />
        ) : (
          <DownloadCloud className="w-10 h-10 animate-pulse drop-shadow-[0_0_10px_var(--j-cyan)]" />
        )}
      </div>

      <div className="space-y-3 w-full">
        <h2 className="text-2xl font-medium tracking-wide">
          Загрузка ядра AI
        </h2>
        <p className="text-sm text-white/50 leading-relaxed">
          KALI загружает необходимые нейросетевые компоненты (Voice, TTS). 
          Это разовая процедура для обеспечения автономной работы.
        </p>
      </div>

      <div className="w-full space-y-4">
        <div className="flex justify-between text-xs text-white/40 tracking-wider uppercase font-medium">
          <span className="truncate max-w-[70%] text-left">{currentFile}</span>
          <span>{percent}%</span>
        </div>
        
        <div className="h-2 w-full bg-[var(--j-surface-soft)] rounded-full overflow-hidden border border-[var(--j-border)] relative">
          <div 
            className="h-full bg-gradient-to-r from-[var(--j-cyan-dim)] to-[var(--j-cyan)] rounded-full transition-all duration-300 relative shadow-[0_0_10px_var(--j-cyan)]"
            style={{ width: `${percent}%` }}
          >
            <div className="absolute inset-0 bg-white/20 animate-pulse" />
          </div>
        </div>
        
        <div className="text-[10px] text-[var(--j-cyan-dim)]/50 tracking-widest uppercase">
          {(downloadedBytes / 1024 / 1024).toFixed(1)} MB / {(totalBytes / 1024 / 1024).toFixed(1)} MB
        </div>
      </div>
    </div>
  );
}
