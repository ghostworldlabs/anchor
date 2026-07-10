import React, { useState } from 'react';

export default function CapabilitiesTile({ selectedSkill }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // REAL data: the top-level "## " section titles of the skill's SKILL.md,
  // supplied by /api/skills. Empty when the skill declares no sections.
  const capabilities = selectedSkill?.capabilities || [];

  return (
    <div className={`panel expandable-tile ${isExpanded ? 'expanded' : ''} shrink-0 transition-all duration-300`} id="tile-cc">
      {/* Header */}
      <div 
        className="p-6 flex justify-between items-center cursor-pointer hover:bg-[#0A0A0F]/80 transition-colors h-[80px]" 
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-slate-400">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400 group-hover:text-white font-display">2. Core Capabilities</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">Documented sections of SKILL.md</p>
          </div>
        </div>
        <button 
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#16161A] text-slate-400 hover:text-white transition-all duration-200"
          onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
          aria-label="Toggle Capabilities"
        >
          <svg className={`w-4 h-4 chevron ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-6 pb-6 pt-4 border-t border-[#16161A] bg-black/40">
          {capabilities.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-800 p-6 text-center mt-2">
              <p className="text-xs text-slate-500">This skill's SKILL.md declares no sections yet.</p>
            </div>
          ) : (
            <ul className="space-y-4 mt-2">
              {capabilities.map((cap, idx) => (
                <li key={idx} className="flex items-start gap-3">
                  <span className="text-[#00F0FF] mt-0.5 font-bold">▪</span>
                  <span className="text-slate-300 text-sm leading-relaxed font-light">{cap}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
