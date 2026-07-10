import React, { useState, useEffect } from 'react';
import NorthStarTile from './components/NorthStarTile';
import CapabilitiesTile from './components/CapabilitiesTile';
import TimelineTile from './components/TimelineTile';
import KnowledgeGraphTile from './components/KnowledgeGraphTile';
import SleepTrainingTile from './components/SleepTrainingTile';
import ControlPlaneModal from './components/ControlPlaneModal';

const SEED_SKILLS = [
  { name: 'Literature Review', description: 'An interactive, augmented researchPrime skill designed to rigorously ingest, corroborate, and synthesize broad upstream lineage (Google Scholar, arXiv, expert domains).', dependencies: ['foundry://skills/git-client'], file_path: 'skills/literature-review/SKILL.md' },
  { name: 'Jumper', description: 'Ideation & Brainstorming Engine of the portfolio, composing Gandalf to generate novel out-of-the-box solutions using SCAMPER, Analogical Transfer, and TRIZ.', dependencies: ['foundry://skills/gandalf'], file_path: 'skills/jumper/SKILL.md' },
  { name: 'Gandalf', description: 'The deep-think advisor inspecting artifacts and configurations to project regression risks and structural type correctness.', dependencies: [], file_path: 'skills/gandalf/SKILL.md' },
  { name: 'Legal Beagle', description: 'A multi-modal AI Legal Advisor for Contract & Compliance Analysis, Case Law Synthesis, and Boilerplate Drafting with a strict Plain-English Mandate.', dependencies: [], file_path: 'skills/legal-beagle/SKILL.md' },
  { name: 'Crucible', description: 'Standalone Production Planner forging plans via a three-Shark adversarial review loop (Skeptic, Contrarian, Analyst).', dependencies: ['foundry://skills/foreman'], file_path: 'skills/crucible/SKILL.md' },
  { name: 'Foreman', description: 'Autonomous multi-wave build orchestrator running test gates in an EXECUTE -> REVIEW -> FIX loop.', dependencies: [], file_path: 'skills/foreman/SKILL.md' },
  { name: 'Ramanujan', description: 'Mathematical reasoning and algorithm-development partner governed by THE HONESTY LAW.', dependencies: [], file_path: 'skills/ramanujan/SKILL.md' },
  { name: 'Financial Analyst', description: 'Robust deal flow and valuation engine constructing mathematical dependency graphs to generate synchronized sheets.', dependencies: [], file_path: 'skills/financial-analyst/SKILL.md' },
  { name: 'Curriculum Dev', description: 'Specialized curriculum restructuring engine following classical western pedagogy and rigorous scaffolded learning pathways.', dependencies: [], file_path: 'skills/curriculum-developer/SKILL.md' }
];

const SKILL_ICONS = {
  'literature review': '/brand/literature-review-icon.jpg',
  'jumper': '/brand/jumper-icon.jpg',
  'gandalf': '/brand/gandalf-icon-v5.jpg',
  'legal beagle': '/brand/legal-beagle-icon.jpg',
  'crucible': '/brand/crucible-icon.svg',
  'foreman': '/brand/foreman-icon.svg',
  'ramanujan': '/brand/ramanujan-icon.jpg',
  'financial analyst': '/brand/financial-analyst-icon.jpg',
  'financial-analyst': '/brand/financial-analyst-icon.jpg',
  'legal-beagle': '/brand/legal-beagle-icon.jpg',
  'literature-review': '/brand/literature-review-icon.jpg',
  'researchprime': '/brand/research-prime-icon.jpg',
  'research prime': '/brand/research-prime-icon.jpg',
  'research-prime': '/brand/research-prime-icon.jpg',
  'curriculum dev': '/brand/skill-foundry-icon.jpg',
  'tidy idy': '/brand/tidy-idy-icon.jpg',
  'tidy-idy': '/brand/tidy-idy-icon.jpg',
  'zombie hunter': '/brand/zombie-hunter-radar.jpg',
  'zombie-hunter': '/brand/zombie-hunter-radar.jpg'
};

const getSkillIconUrl = (name) => {
  const normalized = (name || '').toLowerCase();
  for (const [key, iconPath] of Object.entries(SKILL_ICONS)) {
    if (normalized.includes(key)) return iconPath;
  }
  return '/brand/skill-foundry-icon.jpg';
};

export default function App() {
  const [skills, setSkills] = useState([]);
  const [selectedSkill, setSelectedSkill] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  
  const [globalNorthStar, setGlobalNorthStar] = useState('');
  const [summary, setSummary] = useState('');
  const [timeline, setTimeline] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [agentPayload, setAgentPayload] = useState(null);
  const [isDaemonOnline, setIsDaemonOnline] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isCopied, setIsCopied] = useState(false);
  const [connectionError, setConnectionError] = useState(null);
  const [isDiagnosticsExpanded, setIsDiagnosticsExpanded] = useState(false);
  // Which control-plane op the honest modal describes (null = closed).
  const [opModal, setOpModal] = useState(null);

  // Poll intervals
  const FETCH_INTERVAL_MS = 5000;

  const fetchData = async () => {
    try {
      // Perform requests in parallel
      const [nsRes, sumRes, tlRes, apRes, skRes, mRes] = await Promise.all([
        fetch('/api/north-star').catch(() => null),
        fetch('/api/summary').catch(() => null),
        fetch('/api/timeline').catch(() => null),
        fetch('/api/agent-payload').catch(() => null),
        fetch('/api/skills').catch(() => null),
        fetch('/api/metrics').catch(() => null)
      ]);

      // If all connections fail, the daemon is offline
      if (!nsRes && !sumRes && !tlRes && !apRes && !skRes && !mRes) {
        throw new Error("Unable to connect to daemon endpoints");
      }

      let online = false;

      if (nsRes && nsRes.ok) {
        const data = await nsRes.json();
        setGlobalNorthStar(data.northStar || '');
        online = true;
      }
      
      if (sumRes && sumRes.ok) {
        const data = await sumRes.json();
        setSummary(data.summary || '');
        online = true;
      }

      if (tlRes && tlRes.ok) {
        const data = await tlRes.json();
        setTimeline(data || []);
        online = true;
      }

      if (apRes && apRes.ok) {
        const data = await apRes.json();
        setAgentPayload(data);
        online = true;
      }

      let dbSkills = [];
      if (skRes && skRes.ok) {
        dbSkills = await skRes.json();
        online = true;
      }

      if (mRes && mRes.ok) {
        const data = await mRes.json();
        setMetrics(data);
        online = true;
      }

      // The real /api/skills manifest is the true list; SEED_SKILLS is an
      // offline fallback ONLY (used when the server supplies nothing).
      setSkills(dbSkills && dbSkills.length > 0 ? dbSkills : SEED_SKILLS);

      setIsDaemonOnline(online);
      setConnectionError(null);
    } catch (err) {
      setIsDaemonOnline(false);
      setConnectionError("Daemon offline. Running in fallback mode.");
      
      // Keep using fallback seed skills if daemon is offline
      if (skills.length === 0) {
        setSkills(SEED_SKILLS);
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, FETCH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  // Initialize selectedSkill
  useEffect(() => {
    if (skills.length > 0 && !selectedSkill) {
      setSelectedSkill(skills[0]);
    }
  }, [skills]);

  const handleCopyPayload = () => {
    if (!agentPayload) return;
    navigator.clipboard.writeText(JSON.stringify(agentPayload, null, 2))
      .then(() => {
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), 2000);
      })
      .catch(() => {});
  };

  // Filter skills based on search query
  const filteredSkills = skills.filter(s => 
    (s.name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
    (s.description || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-black text-slate-100 flex flex-col font-sans overflow-hidden h-screen">
      {/* Header bar */}
      <header className="h-28 border-b border-[#16161A] bg-black flex items-center px-8 justify-between shrink-0 z-20">
        <div className="flex items-center gap-4 mr-8 shrink-0">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-900 border border-[#16161A] text-[#00F0FF] overflow-hidden">
            <img src="/brand/skill-foundry-icon.jpg" alt="Skill Foundry" className="w-full h-full object-cover" />
          </div>
          <div>
            <h1 className="text-2xl font-display font-bold tracking-tight text-white">FOUNDRY</h1>
            <div className="text-[10px] text-[#00F0FF] uppercase tracking-widest font-bold flex items-center gap-2 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[#00F0FF] animate-pulse"></span>
              {isDaemonOnline ? 'Sleep Engine Active' : 'Offline Mode'}
            </div>
          </div>
        </div>
        
        {/* Metric Cards — real values from /api/metrics */}
        <div className="flex items-center gap-6 flex-1 justify-end max-w-3xl">
          {/* Tile 1: Skills (manifest count) */}
          <div className="panel h-16 flex-1 max-w-[240px] flex items-center px-5 justify-between shrink-0">
            <div className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold font-display">Skills</div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-mono font-medium text-white">{metrics ? metrics.skills : skills.length}</span>
            </div>
          </div>

          {/* Tile 2: Journal Entries (real journal files across all skills) */}
          <div className="panel h-16 flex-1 max-w-[240px] flex items-center px-5 justify-between shrink-0">
            <div className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold font-display">Journal Entries</div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-mono font-medium text-white">{metrics ? metrics.journalEntries : '—'}</span>
            </div>
          </div>

          {/* Tile 3: Sleep Runs (honest zero until the learning loop is wired) */}
          <div className="panel h-16 flex-1 max-w-[200px] flex items-center px-5 justify-between shrink-0">
            <div className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold font-display">Sleep Runs</div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-mono font-medium text-white">{metrics ? metrics.sleepRuns : '—'}</span>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {connectionError && (
              <span className="text-[10px] text-rose-400 bg-rose-950/20 border border-rose-900/40 px-3 py-1 rounded-full">
                {connectionError}
              </span>
            )}
            
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-[10px] font-mono transition-colors duration-300 ${
              isDaemonOnline 
                ? 'bg-emerald-950/20 border-emerald-900/40 text-emerald-400' 
                : 'bg-slate-900/40 border-slate-800/80 text-slate-400'
            }`}>
              <span className={`h-1.5 w-1.5 rounded-full ${isDaemonOnline ? 'bg-emerald-400 animate-pulse' : 'bg-slate-650'}`} />
              {isDaemonOnline ? 'Daemon Online' : 'Daemon Offline'}
            </div>
          </div>
        </div>
      </header>

      {/* Main Split Container */}
      <div className="flex-1 grid grid-cols-[320px_1fr] overflow-hidden w-full relative">
        
        {/* COL 1: Left Panel (320px) */}
        <div className="bg-black border-r border-[#16161A] flex flex-col h-full z-10 overflow-hidden">
          {/* Search bar */}
          <div className="p-6 border-b border-[#16161A] shrink-0">
            <input 
              type="text" 
              placeholder={`Search ${skills.length} skills...`} 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#08080A] border border-[#16161A] rounded-lg px-4 py-2.5 focus:outline-none focus:border-[#00F0FF] text-xs text-white placeholder-gray-600 transition-colors font-mono"
            />
          </div>
          
          {/* Skill List */}
          <div className="flex-1 overflow-y-auto p-4 space-y-2 min-h-0" id="skill-list">
            {filteredSkills.length === 0 ? (
              <div className="p-6 text-center text-xs text-slate-600 font-mono">
                No skills found matching search.
              </div>
            ) : (
              filteredSkills.map((s, idx) => {
                const isActive = selectedSkill && selectedSkill.name === s.name;
                const iconUrl = getSkillIconUrl(s.name);
                return (
                  <div 
                    key={idx}

                    onClick={() => setSelectedSkill(s)}
                    className={`p-4 rounded-xl panel cursor-pointer transition-all flex justify-between items-start ${
                      isActive 
                        ? 'bg-[#16161A] border-[#00F0FF] shadow-[0_0_15px_rgba(0,240,255,0.04)]' 
                        : 'panel-hover border-transparent'
                    }`}
                  >
                    <div className="overflow-hidden pr-2">
                      <div className="font-semibold text-white flex items-center gap-2.5 text-xs font-display">
                        <img src={iconUrl} alt={s.name} className="w-6 h-6 rounded object-cover select-none" />
                        {s.name}
                      </div>
                      <div className="text-[10px] text-slate-500 mt-2 truncate w-[210px] font-light">
                        {s.description}
                      </div>
                    </div>
                    <span className={`text-[9px] font-bold font-mono tracking-wider px-1.5 py-0.5 rounded border uppercase shrink-0 ${
                      isActive ? 'text-[#00F0FF] border-[#00F0FF]/30' : 'text-slate-600 border-slate-900'
                    }`}>
                      Arch
                    </span>
                  </div>
                );
              })
            )}
          </div>

          {/* Diagnostics Panel (Collapsible) */}
          <div className="border-t border-[#16161A] bg-black shrink-0">
            <div 
              className="p-4 flex items-center justify-between cursor-pointer hover:bg-[#08080a] transition-colors"
              onClick={() => setIsDiagnosticsExpanded(!isDiagnosticsExpanded)}
            >
              <span className="text-[10px] uppercase font-bold tracking-widest text-slate-500 font-display">System Diagnostics</span>
              <svg className={`w-3.5 h-3.5 text-slate-500 chevron ${isDiagnosticsExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
              </svg>
            </div>

            {isDiagnosticsExpanded && (
              <div className="p-4 pt-0 border-t border-[#16161A]/50 space-y-4 max-h-[300px] overflow-y-auto bg-[#050507]">
                {/* Last Synthesis Summary */}
                <div className="space-y-1.5">
                  <span className="text-[9px] uppercase font-bold tracking-widest text-[#00F0FF] font-mono block">Synthesis Summary</span>
                  <div className="rounded-lg bg-black border border-[#16161A] p-3 text-[11px] leading-relaxed text-slate-400 font-light max-h-[100px] overflow-y-auto">
                    {summary || "No active synthesis logs received."}
                  </div>
                </div>

                {/* Technical Payload Viewer */}
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center">
                    <span className="text-[9px] uppercase font-bold tracking-widest text-[#00F0FF] font-mono block">Agent Payload</span>
                    {agentPayload && (
                      <button 
                        onClick={handleCopyPayload}
                        className="text-[8px] uppercase tracking-wider font-bold text-slate-400 hover:text-white px-2 py-0.5 rounded bg-slate-900 border border-slate-800 transition-colors"
                      >
                        {isCopied ? 'Copied' : 'Copy'}
                      </button>
                    )}
                  </div>
                  <div className="rounded-lg bg-black border border-[#16161A] p-3 text-[10px] text-slate-500 font-mono max-h-[120px] overflow-y-auto whitespace-pre-wrap">
                    {agentPayload ? JSON.stringify(agentPayload, null, 2) : "No payload indexed."}
                  </div>
                </div>
              </div>
            )}
          </div>
          
          {/* Create Skill Button */}
          <div className="p-6 border-t border-[#16161A] bg-black shrink-0">
            <button
              onClick={() => setOpModal('scaffold_skill')}
              className="w-full bg-[#16161A] hover:bg-[#00F0FF] hover:text-black text-[#00F0FF] py-3 rounded-lg text-xs font-bold uppercase tracking-widest transition-all duration-300 shadow-[0_0_15px_rgba(0,240,255,0.03)] flex justify-center items-center gap-2 border border-[#00F0FF]/10 hover:border-[#00F0FF]/40 font-display"
            >
              <span className="text-sm">+</span> Create New Skill
            </button>
          </div>
        </div>

        {/* COL 2: Right Panel (1fr) */}
        <div className="flex-1 min-w-0 bg-black p-6 lg:p-10 overflow-y-auto relative h-full z-0">
          <div className="max-w-4xl mx-auto flex flex-col gap-6">
            
            {/* Header info */}
            {selectedSkill && (
              <div className="flex items-center gap-3.5 mb-2 shrink-0 animate-fade-in">
                <img src={getSkillIconUrl(selectedSkill.name)} alt={selectedSkill.name} className="w-10 h-10 rounded-lg border border-[#16161A] object-cover select-none" />
                <h2 className="text-2xl lg:text-3xl font-display font-bold text-white tracking-tight">{selectedSkill.name}</h2>
              </div>
            )}

            {/* Expandable Tiles (Vertical hierarchy) */}
            <NorthStarTile selectedSkill={selectedSkill} globalNorthStar={globalNorthStar} onEditNorthStar={() => setOpModal('edit_north_star')} />

            <CapabilitiesTile selectedSkill={selectedSkill} />

            <TimelineTile timeline={timeline} selectedSkill={selectedSkill} />

            <KnowledgeGraphTile selectedSkill={selectedSkill} skills={skills} onSelectSkill={setSelectedSkill} />

            <SleepTrainingTile selectedSkill={selectedSkill} summary={summary} metrics={metrics} />

          </div>
        </div>

        <ControlPlaneModal op={opModal} onClose={() => setOpModal(null)} />

      </div>
    </div>
  );
}
