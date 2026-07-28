import fs from 'node:fs/promises';
import { validateSchema } from './validateSchema.mjs';

// C8 (2026-07-11): the whitelist is a RANKING prior, not an exclusion list, by default.
// The old default EXCLUDED everything outside 3 ML/security venues — arXiv preprints
// (empty venue) all died as 'low-venue', so a real snowball yielded near-zero candidates
// — and a test fixture ('Some Local Workshop') had leaked into production. Venue
// EXCLUSION is now opt-in via options.excludeByVenue.
export const DEFAULT_VENUE_WHITELIST = {
  venues: [
    { name: 'Conference on Neural Information Processing Systems', abbr: 'NeurIPS', tier: 'Tier-1' },
    { name: 'International Conference on Machine Learning', abbr: 'ICML', tier: 'Tier-1' },
    { name: 'Nature', abbr: 'Nature', tier: 'Tier-1' },
    { name: 'Science', abbr: 'Science', tier: 'Tier-1' },
    { name: 'ACM Conference on Computer and Communications Security', abbr: 'CCS', tier: 'Tier-2' }
  ]
};

/**
 * Matches a venue string case-insensitively and trimmed against the whitelist names and abbreviations.
 * Falls back to case-insensitive substring matching if exact matches are not found.
 */
export function matchVenue(venueStr, whitelist) {
  if (!venueStr) return null;
  const cleaned = venueStr.toLowerCase().trim();

  // 1. Exact match
  for (const v of whitelist.venues || []) {
    const name = (v.name || '').toLowerCase().trim();
    const abbr = (v.abbr || '').toLowerCase().trim();
    if (cleaned === name || cleaned === abbr) {
      return v;
    }
  }

  // 2. Substring match
  for (const v of whitelist.venues || []) {
    const name = (v.name || '').toLowerCase().trim();
    const abbr = (v.abbr || '').toLowerCase().trim();
    if (name && (cleaned.includes(name) || name.includes(cleaned))) {
      return v;
    }
    if (abbr && (cleaned.includes(abbr) || abbr.includes(cleaned))) {
      return v;
    }
  }

  return null;
}

/**
 * Sorts/ranks candidates deterministically:
 * Whitelist Tier (Tier-1 > Tier-2 > Tier-3) -> citation count (desc) -> publication year (desc) -> paperId (alphabetical).
 */
export function rankCandidates(candidates, whitelist) {
  return [...candidates].sort((a, b) => {
    const vA = matchVenue(a.venue, whitelist);
    const vB = matchVenue(b.venue, whitelist);

    const tierMap = { 'Tier-1': 1, 'Tier-2': 2, 'Tier-3': 3 };
    const tierA = vA ? (tierMap[vA.tier] || 4) : 4;
    const tierB = vB ? (tierMap[vB.tier] || 4) : 4;

    if (tierA !== tierB) {
      return tierA - tierB;
    }

    const citA = a.citationCount || 0;
    const citB = b.citationCount || 0;
    if (citA !== citB) {
      return citB - citA;
    }

    const yA = a.year || 0;
    const yB = b.year || 0;
    if (yA !== yB) {
      return yB - yA;
    }

    return (a.paperId || '').localeCompare(b.paperId || '');
  });
}

/**
 * Retries a request with exponential backoff on rate limits (429) or server errors (>= 500).
 */
async function fetchWithBackoff(url, options = {}) {
  const customFetch = options.fetch || fetch;
  const fetchOptions = options.fetchOptions || {};
  const maxRetries = options.maxRetries ?? 3;
  const backoffFactor = options.backoffFactor ?? 50; // ms

  let attempt = 0;
  while (true) {
    try {
      const response = await customFetch(url, fetchOptions);
      if (response.ok) {
        return response;
      }

      if (response.status === 429 || response.status >= 500) {
        if (attempt >= maxRetries) {
          throw new Error(`HTTP error ${response.status} ${response.statusText} after ${maxRetries} retries`);
        }
      } else {
        throw new Error(`HTTP error ${response.status} ${response.statusText}`);
      }
    } catch (error) {
      if (attempt >= maxRetries) {
        throw error;
      }
    }

    attempt++;
    const delay = backoffFactor * Math.pow(2, attempt);
    await new Promise((resolve) => setTimeout(resolve, delay));
  }
}

/**
 * Evaluates a candidate paper against filters, returning { excluded: boolean, reason: string, details: string }.
 */
export function evaluateFilters(paper, whitelist, options = {}) {
  // 1. Date range filter
  if (options.minYear !== undefined && paper.year !== undefined && paper.year !== null) {
    if (paper.year < options.minYear) {
      return {
        excluded: true,
        reason: 'date-range',
        details: `Published in ${paper.year}, but minYear is ${options.minYear}`
      };
    }
  }

  // 2. PDF availability filter
  if (options.requirePdf) {
    const hasPdf = paper.openAccessPdf || paper.pdfUrl || paper.hasPdf;
    if (!hasPdf) {
      return {
        excluded: true,
        reason: 'no-pdf',
        details: 'No open access PDF link available'
      };
    }
  }

  // 3. Venue whitelist filter — OPT-IN (C8): by default the whitelist only RANKS;
  // it excludes only when the operator explicitly asks (options.excludeByVenue).
  if (whitelist && options.excludeByVenue) {
    const matched = matchVenue(paper.venue, whitelist);
    if (!matched) {
      return {
        excluded: true,
        reason: 'low-venue',
        details: `Venue "${paper.venue || 'Unknown'}" is not in the whitelist`
      };
    }

    // 4. Venue tier filter
    if (options.minTier) {
      const tierMap = { 'Tier-1': 1, 'Tier-2': 2, 'Tier-3': 3 };
      const paperTierValue = tierMap[matched.tier] || 4;
      const minTierValue = tierMap[options.minTier] || 4;
      if (paperTierValue > minTierValue) {
        return {
          excluded: true,
          reason: 'low-tier',
          details: `Venue "${paper.venue}" tier is ${matched.tier}, but minTier is ${options.minTier}`
        };
      }
    }
  }

  return { excluded: false };
}

/**
 * Formats a visual citation graph as a Mermaid markdown diagram.
 */
export function generateMermaidGraph(nodes, edges) {
  let mermaid = 'graph TD\n';
  for (const node of nodes) {
    const cleanTitle = (node.title || 'Untitled')
      .replace(/"/g, '\\"')
      .replace(/[\n\r]/g, ' ')
      .slice(0, 50);
    const venue = node.venue || 'No Venue';
    const year = node.year || 'No Year';
    mermaid += `  ${node.paperId}["${cleanTitle}\\n(${venue}, ${year})"]\n`;
    if (node.status === 'excluded') {
      mermaid += `  style ${node.paperId} fill:#ffcccc,stroke:#333,stroke-width:1px\n`;
    } else {
      mermaid += `  style ${node.paperId} fill:#ccffcc,stroke:#333,stroke-width:2px\n`;
    }
  }
  for (const edge of edges) {
    mermaid += `  ${edge.source} --> ${edge.target}\n`;
  }
  return mermaid;
}

/**
 * Performs a depth-bounded citation snowball search starting from seedEntityId.
 */
export async function performSnowballSearch(seedEntityId, venueWhitelist, options = {}) {
  const depthLimit = options.depth ?? 1;
  const customFetch = options.fetch || fetch;
  
  const allPapers = new Map();
  const edges = [];
  const visited = new Set();
  const queue = [];

  // Fetch seed paper details first
  try {
    const seedUrl = `https://api.semanticscholar.org/graph/v1/paper/${seedEntityId}?fields=title,venue,year,citationCount,authors,openAccessPdf,abstract`;
    const res = await fetchWithBackoff(seedUrl, { fetch: customFetch, ...options });
    const data = await res.json();
    if (data && data.paperId) {
      allPapers.set(data.paperId, data);
      queue.push({ paperId: data.paperId, depth: 0 });
      visited.add(data.paperId);
    }
  } catch (err) {
    // If the seed paper cannot be loaded, we fail or handle gracefully. Let's throw if seed cannot be resolved.
    throw new Error(`Failed to fetch seed paper metadata: ${err.message}`);
  }

  // Traversal loop (BFS)
  while (queue.length > 0) {
    const { paperId, depth } = queue.shift();
    const currentPaper = allPapers.get(paperId);

    // If we've reached the depth limit, we do not query references of this paper.
    if (depth >= depthLimit) {
      continue;
    }

    // Fetch references of current paper
    try {
      const refUrl = `https://api.semanticscholar.org/graph/v1/paper/${paperId}/references?fields=title,venue,year,citationCount,authors,openAccessPdf,abstract`;
      const res = await fetchWithBackoff(refUrl, { fetch: customFetch, ...options });
      const responseData = await res.json();
      
      // Parse references (accepts data.data or data.references or raw array)
      const refs = responseData.data || responseData.references || [];
      for (const item of refs) {
        const refPaper = item.citedPaper || item;
        if (!refPaper || !refPaper.paperId) continue;

        const childId = refPaper.paperId;
        
        // Record the edge
        edges.push({ source: paperId, target: childId });

        if (!visited.has(childId)) {
          visited.add(childId);
          allPapers.set(childId, refPaper);

          // Evaluate filters for the paper
          const filterResult = evaluateFilters(refPaper, venueWhitelist, options);
          refPaper.filterResult = filterResult;

          // If not excluded, and depth is within limits, queue it
          if (!filterResult.excluded) {
            if (depth + 1 < depthLimit) {
              queue.push({ paperId: childId, depth: depth + 1 });
            }
          }
        }
      }
    } catch (err) {
      // Gracefully handle query failures by proceeding with whatever we have.
    }
  }

  // Prepare final results
  const nodes = [];
  const exclusions = [];
  const candidates = [];

  for (const [id, paper] of allPapers.entries()) {
    const isSeed = id === seedEntityId;
    
    // Evaluate filters for seed too, or keep it included. Let's evaluate it for nodes representation.
    const filterResult = isSeed ? { excluded: false } : (paper.filterResult || evaluateFilters(paper, venueWhitelist, options));
    
    const nodeStatus = filterResult.excluded ? 'excluded' : 'included';
    nodes.push({
      paperId: id,
      title: paper.title || 'Untitled',
      venue: paper.venue || 'Unknown',
      year: paper.year || null,
      status: nodeStatus,
      reason: filterResult.reason || null
    });

    if (filterResult.excluded) {
      exclusions.push({
        paperId: id,
        title: paper.title || 'Untitled',
        reason: filterResult.reason,
        details: filterResult.details || ''
      });
    } else {
      candidates.push(paper);
    }
  }

  // Deterministically rank the candidates
  const rankedCandidates = rankCandidates(candidates, venueWhitelist);

  // Schema-validate the exclusions
  const prismaExclusions = { exclusions };
  validateSchema(prismaExclusions, 'PrismaExclusions');

  // Write exclusions file if path provided
  if (options.exclusionsPath) {
    await fs.writeFile(options.exclusionsPath, JSON.stringify(prismaExclusions, null, 2), 'utf8');
  }

  // Generate Mermaid graph
  const mermaid = generateMermaidGraph(nodes, edges);

  return {
    graph: { nodes, edges },
    prismaExclusions,
    candidates: rankedCandidates,
    mermaid
  };
}
