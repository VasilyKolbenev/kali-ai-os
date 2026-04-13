import { useEffect, useState } from "react";
import { Search, Download, Package, Sparkles, Zap } from "lucide-react";
import { api } from "../../api/client";

interface SkillInfo {
  name: string;
  template: string;
  display_name: string;
  config: Record<string, unknown>;
}

interface CatalogItem {
  name: string;
  description: string;
  type: string;
  category: string;
  downloads: number;
  rating_avg: number;
  trust_level: string;
}

export function AgentStore() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [catalogResults, setCatalogResults] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.skills().then(setSkills).catch(console.error);
  }, []);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    try {
      const data = await api.catalogSearch(searchQuery);
      setCatalogResults(data.results || []);
    } catch {
      setCatalogResults([]);
    }
    setLoading(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  return (
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-baseline gap-3 mb-6">
          <Package className="w-5 h-5 text-[var(--j-cyan)]" />
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>
            Agent Store
          </h2>
          <span
            className="mono text-[10px] tracking-widest uppercase ml-auto"
            style={{ color: "var(--j-text-muted)" }}
          >
            {skills.length} installed
          </span>
        </div>

        {/* Search */}
        <div className="glass p-3 mb-6 flex gap-2">
          <Search className="w-4 h-4 text-white/40 mt-2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search agents and skills..."
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-white/20"
          />
          <button
            onClick={handleSearch}
            className="px-3 py-1 text-xs rounded bg-[var(--j-cyan)]/20
              text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30 transition"
          >
            Search
          </button>
        </div>

        {/* Installed Skills */}
        <div className="mb-8">
          <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3">
            Installed Skills
          </h3>
          <div className="grid gap-2 stagger">
            {skills.length === 0 && (
              <div className="glass p-4 text-sm text-white/30">
                No skills installed yet
              </div>
            )}
            {skills.map((skill) => (
              <div key={skill.name} className="glass p-4 flex items-center gap-3">
                <Sparkles className="w-4 h-4 text-[var(--j-green)]" />
                <div className="flex-1">
                  <div className="text-sm font-medium">
                    {skill.display_name || skill.name}
                  </div>
                  <div className="text-xs text-white/40">
                    {skill.template} template
                  </div>
                </div>
                <span className="text-xs px-2 py-0.5 rounded bg-[var(--j-green)]/10 text-[var(--j-green)]">
                  Active
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Catalog Results */}
        {catalogResults.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3">
              Catalog Results
            </h3>
            <div className="grid gap-2 stagger">
              {catalogResults.map((item) => (
                <div key={item.name} className="glass p-4 flex items-center gap-3">
                  <Zap className="w-4 h-4 text-[var(--j-cyan)]" />
                  <div className="flex-1">
                    <div className="text-sm font-medium">{item.name}</div>
                    <div className="text-xs text-white/40">{item.description}</div>
                    <div className="text-xs text-white/20 mt-1">
                      {item.category} &middot; {item.downloads} downloads &middot;{" "}
                      &#9733; {item.rating_avg?.toFixed(1)}
                    </div>
                  </div>
                  <button
                    className="px-3 py-1 text-xs rounded bg-[var(--j-cyan)]/20
                      text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30
                      transition flex items-center gap-1"
                  >
                    <Download className="w-3 h-3" />
                    Install
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {loading && (
          <div className="text-center text-sm text-white/30 py-8">
            Searching...
          </div>
        )}
      </div>
    </div>
  );
}
