import { useState } from "react";
import { Wand2, Check, Loader2 } from "lucide-react";
import { api } from "../../api/client";

interface ClassifyResult {
  type: string;
  template: string | null;
  confidence: number;
  reason: string;
}

export function Builder() {
  const [input, setInput] = useState("");
  const [classifyResult, setClassifyResult] = useState<ClassifyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [created, setCreated] = useState<string | null>(null);

  const handleClassify = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setCreated(null);
    try {
      const result = await api.builderClassify(input);
      setClassifyResult(result);
    } catch {
      setClassifyResult(null);
    }
    setLoading(false);
  };

  const handleCreate = async () => {
    if (!classifyResult) return;
    setLoading(true);
    try {
      if (classifyResult.type === "skill" && classifyResult.template) {
        const result = await api.builderCreateSkill({
          name: input.toLowerCase().replace(/\s+/g, "-").slice(0, 30),
          template: classifyResult.template,
          description: input,
          config: {},
        });
        setCreated(result.status === "deployed" ? result.name : null);
      } else {
        setCreated(null); // Agent creation needs more params
      }
    } catch {
      setCreated(null);
    }
    setLoading(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleClassify();
  };

  return (
    <div className="glass p-4 mb-6">
      <div className="flex items-center gap-2 mb-3">
        <Wand2 className="w-4 h-4 text-[var(--j-cyan)]" />
        <span className="text-sm font-medium">Create Agent or Skill</span>
      </div>

      <div className="flex gap-2 mb-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe what you want... e.g. 'track my water intake'"
          className="flex-1 bg-white/5 rounded px-3 py-2 text-sm outline-none placeholder:text-white/20 focus:bg-white/10 transition"
        />
        <button
          onClick={handleClassify}
          disabled={loading || !input.trim()}
          className="px-4 py-2 text-xs rounded bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30 transition disabled:opacity-30"
        >
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Analyze"}
        </button>
      </div>

      {classifyResult && (
        <div className="bg-white/5 rounded p-3 text-sm">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`px-2 py-0.5 rounded text-xs ${
                classifyResult.type === "skill"
                  ? "bg-[var(--j-green)]/10 text-[var(--j-green)]"
                  : "bg-[var(--j-cyan)]/10 text-[var(--j-cyan)]"
              }`}
            >
              {classifyResult.type}
            </span>
            {classifyResult.template && (
              <span className="text-xs text-white/40">
                template: {classifyResult.template}
              </span>
            )}
          </div>
          <p className="text-xs text-white/50 mb-3">{classifyResult.reason}</p>
          <button
            onClick={handleCreate}
            disabled={loading}
            className="px-4 py-1.5 text-xs rounded bg-[var(--j-green)]/20 text-[var(--j-green)] hover:bg-[var(--j-green)]/30 transition flex items-center gap-1"
          >
            <Check className="w-3 h-3" />
            Create {classifyResult.type}
          </button>
        </div>
      )}

      {created && (
        <div className="mt-3 text-xs text-[var(--j-green)]">
          &#x2713; Created &quot;{created}&quot; successfully! Refresh skills to see it.
        </div>
      )}
    </div>
  );
}
