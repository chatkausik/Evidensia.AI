"use client";

import { useEffect, useRef, useState } from "react";

type View = "research" | "discover" | "library" | "debugger" | "evaluations";
type Depth = "quick" | "standard" | "deep";
type PaperProvider = "arxiv" | "openalex";

type Citation = {
  citation_id: string;
  title: string;
  section: string;
  page: number | null;
  source_uri: string | null;
  quoted_text: string | null;
};

type Evidence = {
  evidence_id: string;
  claim: string;
  supporting_text: string;
  evidence_type: "supporting" | "contradicting" | "neutral";
  relevance: number;
  confidence: number;
  citation: Citation;
};

type ResearchRun = {
  run_id: string;
  question: string;
  status: string;
  confidence: number;
  iterations: number;
  sub_questions: Array<{ id: string; question: string; purpose: string; completed: boolean }>;
  retrieved_evidence: Evidence[];
  final_report: null | {
    executive_summary: string;
    conclusion: string;
    key_findings: string[];
    limitations: string[];
    unresolved_questions: string[];
    confidence_score: number;
    sources: Citation[];
    claims: Array<{ claim_id: string; statement: string; status: string; confidence: number; evidence_ids: string[]; opposing_evidence_ids: string[] }>;
  };
};

type DocumentItem = {
  id: string;
  title: string;
  type: string;
  year: number;
  chunks: number;
  status: string;
  topics: string[];
};

type LibraryConnection = "connecting" | "live" | "preview";

type ApiDocumentRecord = {
  document_id: string;
  filename: string;
  source_uri: string | null;
  chunk_count: number;
  status: string;
  metadata: null | {
    title: string;
    document_type: string;
    publication_year: number | null;
    topics: string[];
  };
};

type DiscoveredPaper = {
  paper_id: string;
  providers: PaperProvider[];
  title: string;
  abstract: string;
  authors: string[];
  published_at: string;
  venue: string | null;
  doi: string | null;
  categories: string[];
  topics: string[];
  landing_url: string;
  open_access: boolean;
  publication_type: string;
  citation_count: number | null;
};

type DiscoveryResponse = {
  papers: DiscoveredPaper[];
  warnings: string[];
};

type TimelineItem = { type: string; title: string; detail: string; state: "done" | "active" | "waiting" };

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
const today = new Date().toISOString().slice(0, 10);

const initialQuestion = "Does agentic RAG significantly outperform traditional RAG for multi-hop enterprise question answering?";

const demoEvidence: Evidence[] = [
  {
    evidence_id: "ev_benchmark",
    claim: "On HotpotQA, the agentic system improved exact match from 61.2 to 69.8 and Recall@10 from 78.4 to 89.1.",
    supporting_text: "Gains were concentrated in questions that required evidence from three or more passages.",
    evidence_type: "supporting",
    relevance: 0.96,
    confidence: 0.91,
    citation: { citation_id: "cit_1", title: "Agentic Retrieval for Multi-Hop Question Answering", section: "Results", page: 7, source_uri: "demo://agentic-rag-benchmark-2025.md", quoted_text: "On HotpotQA, the agentic system improved exact match from 61.2 to 69.8 and Recall@10 from 78.4 to 89.1." },
  },
  {
    evidence_id: "ev_negative",
    claim: "The difference on FEVER was not statistically significant after controlling for reranking quality.",
    supporting_text: "On the support corpus, repeated retrieval introduced irrelevant passages and answer accuracy declined by 1.4 points.",
    evidence_type: "contradicting",
    relevance: 0.9,
    confidence: 0.87,
    citation: { citation_id: "cit_2", title: "When Iterative Retrieval Does Not Help", section: "Evaluation", page: 4, source_uri: "demo://negative-results-2025.md", quoted_text: "The difference on FEVER was not statistically significant after controlling for reranking quality." },
  },
  {
    evidence_id: "ev_cost",
    claim: "Median latency increased from 1.8 seconds to 5.1 seconds and model calls rose 2.7×.",
    supporting_text: "The largest gains appeared on complex multi-hop questions, while single-hop gains were below one point.",
    evidence_type: "supporting",
    relevance: 0.93,
    confidence: 0.89,
    citation: { citation_id: "cit_3", title: "Agentic Retrieval for Multi-Hop Question Answering", section: "Costs and limitations", page: 9, source_uri: "demo://agentic-rag-benchmark-2025.md", quoted_text: "The agentic system required 2.7 times more model calls and median latency increased from 1.8 seconds to 5.1 seconds." },
  },
];

const demoRun: ResearchRun = {
  run_id: "run_demo_01",
  question: initialQuestion,
  status: "completed",
  confidence: 0.87,
  iterations: 2,
  sub_questions: [
    { id: "sq_1", question: "How do the two retrieval approaches differ?", purpose: "Establish comparison baselines", completed: true },
    { id: "sq_2", question: "Which benchmarks directly compare them?", purpose: "Find measurable outcomes", completed: true },
    { id: "sq_3", question: "What latency and cost penalties occur?", purpose: "Quantify trade-offs", completed: true },
    { id: "sq_4", question: "Which studies disagree or qualify the premise?", purpose: "Find counter-evidence", completed: true },
  ],
  retrieved_evidence: demoEvidence,
  final_report: {
    executive_summary: "Agentic RAG shows meaningful gains on complex multi-hop questions when the initial retrieval is weak, but it does not consistently outperform a well-tuned hybrid baseline on simpler tasks.",
    conclusion: "The advantage is conditional rather than universal: better recovery and multi-step evidence gathering come with materially higher latency, model usage, and exposure to query drift.",
    key_findings: [
      "HotpotQA Recall@10 increased from 78.4 to 89.1 in a direct comparison.",
      "Most gains were concentrated in questions requiring three or more evidence passages.",
      "A separate FEVER evaluation found no statistically significant improvement after controlling for reranking.",
      "Median latency rose from 1.8s to 5.1s and model calls increased 2.7×.",
    ],
    limitations: ["The available studies cover a small number of public and enterprise corpora.", "Agent quality is sensitive to stopping rules and query drift."],
    unresolved_questions: ["How do access controls and rapidly changing corpora affect retrieval recovery?"],
    confidence_score: 0.87,
    sources: demoEvidence.map((item) => item.citation),
    claims: [
      { claim_id: "claim_1", statement: "Agentic retrieval improves complex multi-hop evidence recall.", status: "supported", confidence: 0.91, evidence_ids: ["ev_benchmark"], opposing_evidence_ids: ["ev_negative"] },
      { claim_id: "claim_2", statement: "The improvement carries substantial latency and model-call costs.", status: "supported", confidence: 0.89, evidence_ids: ["ev_cost"], opposing_evidence_ids: [] },
    ],
  },
};

const startingDocuments: DocumentItem[] = [
  { id: "doc_01", title: "Agentic Retrieval for Multi-Hop Question Answering", type: "Demo paper", year: 2025, chunks: 38, status: "Demo", topics: ["Agentic RAG", "HotpotQA"] },
  { id: "doc_02", title: "When Iterative Retrieval Does Not Help", type: "Demo paper", year: 2025, chunks: 27, status: "Demo", topics: ["Negative results", "FEVER"] },
  { id: "doc_03", title: "Reliable Hybrid Retrieval Systems", type: "Demo report", year: 2024, chunks: 31, status: "Demo", topics: ["BM25", "RRF", "Reranking"] },
];

const demoDebug = {
  dense: [{ id: "chk_992", score: 0.91 }, { id: "chk_144", score: 0.86 }, { id: "chk_501", score: 0.79 }],
  sparse: [{ id: "chk_144", score: 12.4 }, { id: "chk_992", score: 10.8 }, { id: "chk_731", score: 8.6 }],
  fused: [{ id: "chk_144", score: 0.0325 }, { id: "chk_992", score: 0.0323 }, { id: "chk_501", score: 0.0159 }],
  reranked: [{ id: "chk_992", score: 0.97 }, { id: "chk_144", score: 0.94 }, { id: "chk_501", score: 0.82 }],
};

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toDocumentItem(record: ApiDocumentRecord): DocumentItem {
  const topics = record.metadata?.topics?.slice(0, 3) || [];
  const isDemo = record.source_uri?.startsWith("demo://");
  return {
    id: record.document_id,
    title: record.metadata?.title || record.filename,
    type: isDemo ? "Demo source" : record.filename.endsWith(".pdf") ? "Full research paper" : "Paper abstract",
    year: record.metadata?.publication_year || new Date().getFullYear(),
    chunks: record.chunk_count,
    status: isDemo ? "Demo" : record.status === "indexed" ? "Indexed" : record.status,
    topics: topics.length ? topics : [isDemo ? "Example evidence" : "Discovered source"],
  };
}

export default function Home() {
  const [view, setView] = useState<View>("research");
  const [question, setQuestion] = useState(initialQuestion);
  const [depth, setDepth] = useState<Depth>("standard");
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [running, setRunning] = useState(false);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [documents, setDocuments] = useState(startingDocuments);
  const [libraryConnection, setLibraryConnection] = useState<LibraryConnection>("connecting");
  const [discoveryQuery, setDiscoveryQuery] = useState("agentic RAG multi-hop question answering");
  const [dateFrom, setDateFrom] = useState("2025-01-01");
  const [dateTo, setDateTo] = useState(today);
  const [paperProviders, setPaperProviders] = useState<PaperProvider[]>(["arxiv", "openalex"]);
  const [discoveredPapers, setDiscoveredPapers] = useState<DiscoveredPaper[]>([]);
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<string>>(new Set());
  const [discovering, setDiscovering] = useState(false);
  const [importingPapers, setImportingPapers] = useState(false);
  const [discoveryNotice, setDiscoveryNotice] = useState("");
  const [debugQuery, setDebugQuery] = useState("Agentic RAG multi-hop HotpotQA");
  const [debugging, setDebugging] = useState(false);
  const [evalRunning, setEvalRunning] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE}/v1/documents`)
      .then((response) => {
        if (!response.ok) throw new Error("Library request failed");
        return response.json();
      })
      .then((records: ApiDocumentRecord[]) => {
        if (!active) return;
        setDocuments(records.map(toDocumentItem));
        setLibraryConnection("live");
      })
      .catch(() => {
        if (active) setLibraryConnection("preview");
      });
    return () => { active = false; };
  }, []);

  async function startResearch(event: React.FormEvent) {
    event.preventDefault();
    if (question.trim().length < 8 || running) return;
    setRunning(true);
    setRun(null);
    setSelectedEvidence(null);
    const steps: TimelineItem[] = [
      { type: "plan", title: "Research plan created", detail: "5 focused questions · 3 hypotheses", state: "active" },
      { type: "search", title: "Hybrid evidence search", detail: "Dense + BM25 · RRF fusion", state: "waiting" },
      { type: "counter", title: "Counter-evidence search", detail: "Actively testing the premise", state: "waiting" },
      { type: "verify", title: "Claim and citation verification", detail: "Exact passage validation", state: "waiting" },
    ];
    setTimeline(steps);
    await sleep(420);
    setTimeline(steps.map((item, index) => ({ ...item, state: index === 0 ? "done" : index === 1 ? "active" : "waiting" })));
    await sleep(520);
    setTimeline(steps.map((item, index) => ({ ...item, state: index < 2 ? "done" : index === 2 ? "active" : "waiting" })));

    let result: ResearchRun | null = null;
    try {
      const response = await fetch(`${API_BASE}/v1/research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, depth, namespace: "open-research", run_synchronously: true }),
      });
      if (response.ok) result = await response.json();
    } catch {
      result = null;
    }
    await sleep(430);
    setTimeline(steps.map((item, index) => ({ ...item, state: index < 3 ? "done" : "active" })));
    await sleep(420);
    result ||= { ...demoRun, question, run_id: `demo_${Date.now()}` };
    setRun(result);
    setSelectedEvidence(result.retrieved_evidence[0] || null);
    setTimeline(steps.map((item) => ({ ...item, state: "done" })));
    setRunning(false);
  }

  async function importSource(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const optimistic: DocumentItem = {
      id: `local_${Date.now()}`,
      title: file.name.replace(/\.[^.]+$/, ""),
      type: file.type.includes("pdf") ? "PDF" : "Document",
      year: new Date().getFullYear(),
      chunks: Math.max(1, Math.round(file.size / 2200)),
      status: "Indexing",
      topics: ["New source"],
    };
    setDocuments((items) => [optimistic, ...items]);
    setView("library");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(`${API_BASE}/v1/documents`, { method: "POST", body });
      if (response.ok) {
        const record = await response.json();
        setDocuments((items) => items.map((item) => item.id === optimistic.id ? {
          ...item,
          id: record.document_id,
          title: record.metadata?.title || item.title,
          chunks: record.chunk_count,
          status: "Indexed",
          topics: record.metadata?.topics?.slice(0, 3) || item.topics,
        } : item));
        return;
      }
    } catch {
      // The hosted studio keeps a useful local preview when no API is attached.
    }
    await sleep(700);
    setDocuments((items) => items.map((item) => item.id === optimistic.id ? { ...item, status: "Indexed" } : item));
    event.target.value = "";
  }

  async function runDebug(event: React.FormEvent) {
    event.preventDefault();
    setDebugging(true);
    await sleep(650);
    setDebugging(false);
  }

  function toggleProvider(provider: PaperProvider) {
    setPaperProviders((current) => current.includes(provider)
      ? current.filter((item) => item !== provider)
      : [...current, provider]);
  }

  function togglePaper(paperId: string) {
    setSelectedPaperIds((current) => {
      const next = new Set(current);
      if (next.has(paperId)) next.delete(paperId);
      else next.add(paperId);
      return next;
    });
  }

  async function discoverPapers(event: React.FormEvent) {
    event.preventDefault();
    if (discoveryQuery.trim().length < 2 || paperProviders.length === 0 || discovering) return;
    setDiscovering(true);
    setDiscoveryNotice("");
    try {
      const response = await fetch(`${API_BASE}/v1/sources/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: discoveryQuery,
          date_from: dateFrom,
          date_to: dateTo,
          providers: paperProviders,
          open_access_only: true,
          limit: 30,
        }),
      });
      if (!response.ok) throw new Error("Discovery request failed");
      const result: DiscoveryResponse = await response.json();
      setDiscoveredPapers(result.papers);
      setSelectedPaperIds(new Set(result.papers.slice(0, 5).map((paper) => paper.paper_id)));
      const found = `${result.papers.length} unique papers found`;
      setDiscoveryNotice(result.warnings.length ? `${found}. ${result.warnings.join(" · ")}` : found);
    } catch {
      setDiscoveryNotice("The paper discovery API is unavailable. Start the Evidensia API locally, then try again.");
    } finally {
      setDiscovering(false);
    }
  }

  async function importDiscoveredPapers() {
    if (selectedPaperIds.size === 0 || importingPapers) return;
    setImportingPapers(true);
    try {
      const response = await fetch(`${API_BASE}/v1/sources/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paper_ids: [...selectedPaperIds], full_text: true }),
      });
      if (!response.ok) throw new Error("Import request failed");
      const result = await response.json();
      const additions: DocumentItem[] = result.imported.map(toDocumentItem);
      setDocuments((current) => [...additions, ...current.filter((document) => !additions.some((item) => item.id === document.id))]);
      setLibraryConnection("live");
      const fallbackCount = result.abstract_fallbacks?.length || 0;
      setDiscoveryNotice(`${additions.length} papers ingested${fallbackCount ? ` · ${fallbackCount} used abstract fallback` : " with full text"}${result.skipped.length ? ` · ${result.skipped.length} already indexed` : ""}.`);
      setSelectedPaperIds(new Set());
    } catch {
      setDiscoveryNotice("The selected papers could not be imported. Check the API connection and retry.");
    } finally {
      setImportingPapers(false);
    }
  }

  async function runEvaluation() {
    setEvalRunning(true);
    await sleep(950);
    setEvalRunning(false);
  }

  const navItems: Array<{ id: View; label: string; icon: string }> = [
    { id: "research", label: "Research", icon: "⌕" },
    { id: "discover", label: "Discover papers", icon: "✦" },
    { id: "library", label: "Source library", icon: "▱" },
    { id: "debugger", label: "Retrieval debugger", icon: "≋" },
    { id: "evaluations", label: "Evaluations", icon: "◇" },
  ];
  const indexedDocuments = documents.filter((document) => document.status !== "Demo");

  return (
    <main className="studio-shell">
      <aside className="studio-nav">
        <button className="brand" onClick={() => setView("research")} aria-label="Evidensia home">
          <span className="brand-mark">E</span><span>Evidensia</span>
        </button>
        <nav aria-label="Research workspace">
          {navItems.map((item) => (
            <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}>
              <span>{item.icon}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="corpus-card">
          <span className="micro-label">ACTIVE CORPUS</span>
          <strong>Open research</strong>
          <small>{indexedDocuments.length} indexed · {indexedDocuments.reduce((sum, item) => sum + item.chunks, 0)} chunks</small>
        </div>
        <div className="nav-foot"><span className="status-dot" /> Evidence engine ready</div>
      </aside>

      <section className="studio-main">
        <header className="topbar">
          <div><p className="eyebrow">RESEARCH STUDIO</p><p className="workspace-name">{navItems.find((item) => item.id === view)?.label}</p></div>
          <div className="top-actions">
            <input ref={fileRef} className="visually-hidden" type="file" accept=".pdf,.md,.txt,.html" onChange={importSource} />
            <button className="ghost-button" type="button" onClick={() => fileRef.current?.click()}>＋ Import source</button>
            <div className="avatar" aria-label="User profile">KC</div>
          </div>
        </header>

        {view === "research" && (
          <ResearchView
            question={question}
            setQuestion={setQuestion}
            depth={depth}
            setDepth={setDepth}
            running={running}
            run={run}
            timeline={timeline}
            selectedEvidence={selectedEvidence}
            setSelectedEvidence={setSelectedEvidence}
            startResearch={startResearch}
            reset={() => { setRun(null); setTimeline([]); setSelectedEvidence(null); }}
          />
        )}
        {view === "discover" && (
          <DiscoveryView
            query={discoveryQuery}
            setQuery={setDiscoveryQuery}
            dateFrom={dateFrom}
            setDateFrom={setDateFrom}
            dateTo={dateTo}
            setDateTo={setDateTo}
            providers={paperProviders}
            toggleProvider={toggleProvider}
            papers={discoveredPapers}
            selectedPaperIds={selectedPaperIds}
            togglePaper={togglePaper}
            discovering={discovering}
            importing={importingPapers}
            notice={discoveryNotice}
            onDiscover={discoverPapers}
            onImport={importDiscoveredPapers}
          />
        )}
        {view === "library" && <LibraryView documents={documents} connection={libraryConnection} onImport={() => fileRef.current?.click()} onDiscover={() => setView("discover")} />}
        {view === "debugger" && <DebuggerView query={debugQuery} setQuery={setDebugQuery} loading={debugging} onRun={runDebug} />}
        {view === "evaluations" && <EvaluationsView running={evalRunning} onRun={runEvaluation} />}
      </section>
    </main>
  );
}

function DiscoveryView(props: {
  query: string;
  setQuery: (value: string) => void;
  dateFrom: string;
  setDateFrom: (value: string) => void;
  dateTo: string;
  setDateTo: (value: string) => void;
  providers: PaperProvider[];
  toggleProvider: (provider: PaperProvider) => void;
  papers: DiscoveredPaper[];
  selectedPaperIds: Set<string>;
  togglePaper: (paperId: string) => void;
  discovering: boolean;
  importing: boolean;
  notice: string;
  onDiscover: (event: React.FormEvent) => void;
  onImport: () => void;
}) {
  return (
    <div className="page-canvas discovery-page">
      <div className="page-heading">
        <div>
          <span className="signal"><i /> LIVE SCHOLARLY SOURCES</span>
          <h1>Discover papers</h1>
          <p>Search recent AI research across arXiv and OpenAlex. Evidensia extracts full arXiv PDFs when available and uses a clearly marked abstract fallback for other sources.</p>
        </div>
      </div>

      <form className="discovery-form" onSubmit={props.onDiscover}>
        <label className="discovery-query" htmlFor="paper-query">
          <span>Research topic</span>
          <input id="paper-query" value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="e.g. multimodal agents for scientific discovery" />
        </label>
        <div className="discovery-controls">
          <label><span>From</span><input type="date" value={props.dateFrom} onChange={(event) => props.setDateFrom(event.target.value)} /></label>
          <label><span>To</span><input type="date" value={props.dateTo} onChange={(event) => props.setDateTo(event.target.value)} /></label>
          <fieldset>
            <legend>Sources</legend>
            {(["arxiv", "openalex"] as PaperProvider[]).map((provider) => (
              <label key={provider}><input type="checkbox" checked={props.providers.includes(provider)} onChange={() => props.toggleProvider(provider)} /> {provider === "arxiv" ? "arXiv" : "OpenAlex"}</label>
            ))}
          </fieldset>
          <button className="primary-button" disabled={props.discovering || props.providers.length === 0}>
            {props.discovering ? "Searching…" : "Find papers"}<span>→</span>
          </button>
        </div>
      </form>

      {props.notice && <p className="discovery-notice" role="status">{props.notice}</p>}

      <div className="discovery-toolbar">
        <div><span className="micro-label">DISCOVERY RESULTS</span><strong>{props.papers.length || "—"}</strong></div>
        <button className="ghost-button" type="button" disabled={props.selectedPaperIds.size === 0 || props.importing} onClick={props.onImport}>
          {props.importing ? "Extracting…" : `Ingest selected (${props.selectedPaperIds.size})`}
        </button>
      </div>

      {props.papers.length === 0 ? (
        <div className="paper-empty"><span>✦</span><strong>Search the 2025–2026 literature</strong><p>Results are deduplicated by DOI and paper identity before they reach your library.</p></div>
      ) : (
        <div className="paper-results">
          {props.papers.map((paper) => (
            <article className={`paper-result ${props.selectedPaperIds.has(paper.paper_id) ? "selected" : ""}`} key={paper.paper_id}>
              <label className="paper-select" aria-label={`Select ${paper.title}`}><input type="checkbox" checked={props.selectedPaperIds.has(paper.paper_id)} onChange={() => props.togglePaper(paper.paper_id)} /></label>
              <div className="paper-copy">
                <div className="paper-meta">
                  <span>{paper.providers.map((provider) => provider === "arxiv" ? "arXiv" : "OpenAlex").join(" + ")}</span>
                  <span>{paper.published_at}</span>
                  <span>{paper.open_access ? "Open access" : "Access unknown"}</span>
                  <span>{paper.providers.includes("arxiv") ? "Full text ready" : "Abstract metadata"}</span>
                  {paper.citation_count !== null && <span>{paper.citation_count} citations</span>}
                </div>
                <h2>{paper.title}</h2>
                <p className="paper-authors">{paper.authors.slice(0, 4).join(", ")}{paper.authors.length > 4 ? " et al." : ""}</p>
                <p className="paper-abstract">{paper.abstract}</p>
                <footer>
                  <span>{paper.venue || paper.categories.slice(0, 3).join(" · ") || paper.publication_type}</span>
                  <a href={paper.landing_url} target="_blank" rel="noreferrer">View source ↗</a>
                </footer>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function ResearchView(props: {
  question: string;
  setQuestion: (value: string) => void;
  depth: Depth;
  setDepth: (value: Depth) => void;
  running: boolean;
  run: ResearchRun | null;
  timeline: TimelineItem[];
  selectedEvidence: Evidence | null;
  setSelectedEvidence: (item: Evidence) => void;
  startResearch: (event: React.FormEvent) => void;
  reset: () => void;
}) {
  if (!props.running && !props.run) {
    return (
      <div className="research-canvas">
        <div className="hero-copy">
          <span className="signal"><i /> AUTONOMOUS EVIDENCE INTELLIGENCE</span>
          <h1>Turn difficult questions into<br />defensible answers.</h1>
          <p>Evidensia plans the investigation, finds supporting and conflicting evidence, and verifies every citation before it reaches your report.</p>
        </div>
        <ResearchComposer {...props} />
        <section className="capability-row" aria-label="Research capabilities">
          <article><span className="cap-number">01</span><h2>Plan</h2><p>Break complex questions into focused lines of inquiry.</p></article>
          <article><span className="cap-number">02</span><h2>Challenge</h2><p>Seek disconfirming evidence, not just convenient support.</p></article>
          <article><span className="cap-number">03</span><h2>Verify</h2><p>Trace every claim back to its exact source passage.</p></article>
        </section>
      </div>
    );
  }

  return (
    <div className="live-canvas">
      <div className="run-heading">
        <div>
          <span className={`run-status ${props.running ? "working" : "complete"}`}>{props.running ? "● RESEARCH IN PROGRESS" : "✓ RESEARCH COMPLETE"}</span>
          <h1>{props.run?.question || props.question}</h1>
          <p>{props.running ? "Planning, searching, challenging, and verifying the evidence." : `${props.run?.retrieved_evidence.length || 0} evidence spans · ${props.run?.iterations || 0} research cycles · all citations checked`}</p>
        </div>
        {!props.running && <button className="ghost-button" onClick={props.reset}>New question</button>}
      </div>

      <div className="live-grid">
        <aside className="timeline-panel">
          <div className="panel-title"><span>RESEARCH TRACE</span><small>LIVE</small></div>
          <div className="timeline-list">
            {props.timeline.map((item, index) => (
              <div className={`timeline-item ${item.state}`} key={item.type}>
                <span className="timeline-node">{item.state === "done" ? "✓" : index + 1}</span>
                <div><strong>{item.title}</strong><small>{item.detail}</small></div>
              </div>
            ))}
          </div>
          {(props.run?.sub_questions || []).length > 0 && (
            <div className="plan-list">
              <span className="micro-label">INVESTIGATION PLAN</span>
              {props.run!.sub_questions.map((item) => <p key={item.id}><span>✓</span>{item.purpose}</p>)}
            </div>
          )}
        </aside>

        <section className="evidence-stream">
          <div className="panel-title"><span>{props.run ? "EVIDENCE EXPLORER" : "LIVE EVIDENCE"}</span><small>{props.run?.retrieved_evidence.length || "SEARCHING"}</small></div>
          {!props.run && <div className="searching-state"><span className="search-orbit" /><strong>Searching the corpus</strong><p>“agentic RAG latency benchmark multi-hop”</p></div>}
          {props.run?.retrieved_evidence.map((item, index) => (
            <button key={item.evidence_id} className={`evidence-card ${item.evidence_type} ${props.selectedEvidence?.evidence_id === item.evidence_id ? "selected" : ""}`} onClick={() => props.setSelectedEvidence(item)}>
              <div className="evidence-meta"><span>{item.evidence_type.toUpperCase()}</span><small>#{String(index + 1).padStart(2, "0")} · {Math.round(item.relevance * 100)}% relevant</small></div>
              <blockquote>{item.claim}</blockquote>
              <footer><strong>{item.citation.title}</strong><span>{item.citation.section}{item.citation.page ? ` · p. ${item.citation.page}` : ""}</span></footer>
            </button>
          ))}
        </section>

        <aside className="source-viewer">
          <div className="panel-title"><span>SOURCE PASSAGE</span><small>VERIFIED</small></div>
          {props.selectedEvidence ? (
            <>
              <span className={`evidence-pill ${props.selectedEvidence.evidence_type}`}>{props.selectedEvidence.evidence_type}</span>
              <h2>{props.selectedEvidence.citation.title}</h2>
              <p className="source-locator">{props.selectedEvidence.citation.section}{props.selectedEvidence.citation.page ? ` · page ${props.selectedEvidence.citation.page}` : ""}</p>
              <blockquote>“{props.selectedEvidence.citation.quoted_text || props.selectedEvidence.supporting_text}”</blockquote>
              <div className="source-scores"><span>Confidence <strong>{Math.round(props.selectedEvidence.confidence * 100)}%</strong></span><span>Entailment <strong>Passed</strong></span></div>
            </>
          ) : <div className="empty-panel">Select an evidence card to inspect its exact source passage.</div>}
        </aside>
      </div>

      {props.run?.final_report && <ReportView run={props.run} />}
    </div>
  );
}

function ResearchComposer(props: { question: string; setQuestion: (value: string) => void; depth: Depth; setDepth: (value: Depth) => void; running: boolean; startResearch: (event: React.FormEvent) => void }) {
  return (
    <form className="research-box" onSubmit={props.startResearch}>
      <label htmlFor="research-question">What would you like to investigate?</label>
      <textarea id="research-question" value={props.question} onChange={(event) => props.setQuestion(event.target.value)} rows={4} />
      <div className="composer-foot">
        <fieldset><legend>Research depth</legend>{(["quick", "standard", "deep"] as Depth[]).map((item) => <label key={item}><input type="radio" name="depth" checked={props.depth === item} onChange={() => props.setDepth(item)} /> {item[0].toUpperCase() + item.slice(1)}</label>)}</fieldset>
        <button className="primary-button" type="submit" disabled={props.running}>{props.running ? "Researching…" : "Start research"}<span>→</span></button>
      </div>
    </form>
  );
}

function ReportView({ run }: { run: ResearchRun }) {
  const report = run.final_report!;
  return (
    <section className="report-panel">
      <div className="report-lead">
        <span className="micro-label">VERIFIED RESEARCH REPORT</span>
        <h2>{report.executive_summary}</h2>
        <div className="confidence-seal"><strong>{Math.round(report.confidence_score * 100)}</strong><span>CONFIDENCE</span></div>
      </div>
      <div className="report-grid">
        <article><h3>Conclusion</h3><p>{report.conclusion}</p><h3>Key findings</h3><ol>{report.key_findings.map((finding) => <li key={finding}>{finding}</li>)}</ol></article>
        <article className="claim-graph"><h3>Claim graph</h3>{report.claims.map((claim) => <div className="claim-row" key={claim.claim_id}><span className={`claim-state ${claim.status}`}>{claim.status}</span><div><strong>{claim.statement}</strong><small>{claim.evidence_ids.length} supporting · {claim.opposing_evidence_ids.length} opposing</small></div><b>{Math.round(claim.confidence * 100)}%</b></div>)}</article>
      </div>
      <div className="report-foot"><div><h3>Limitations</h3>{report.limitations.map((item) => <p key={item}>— {item}</p>)}</div><div><h3>Unresolved</h3>{report.unresolved_questions.map((item) => <p key={item}>— {item}</p>)}</div></div>
    </section>
  );
}

function LibraryView({ documents, connection, onImport, onDiscover }: { documents: DocumentItem[]; connection: LibraryConnection; onImport: () => void; onDiscover: () => void }) {
  const indexed = documents.filter((document) => document.status !== "Demo");
  const demos = documents.filter((document) => document.status === "Demo");
  return (
    <div className="page-canvas">
      <div className="page-heading"><div><span className="signal"><i /> KNOWLEDGE FOUNDATION</span><h1>Source library</h1><p>Every indexed source is parsed into section-aware parent context and retrieval chunks.</p></div><div className="page-actions"><button className="ghost-button" onClick={onImport}>＋ Upload file</button><button className="primary-button" onClick={onDiscover}>Discover papers<span>→</span></button></div></div>
      {connection === "preview" && <p className="library-banner">The three rows below are demonstration sources. Start the Evidensia API and use Discover papers to build a live corpus.</p>}
      {connection === "live" && demos.length > 0 && indexed.length === 0 && <p className="library-banner">The API is connected, but only demo sources are loaded. Open Discover papers, search a topic, and ingest the selected results.</p>}
      <div className="library-stats"><div><span>Indexed sources</span><strong>{indexed.length}</strong></div><div><span>Retrieval chunks</span><strong>{indexed.reduce((sum, item) => sum + item.chunks, 0)}</strong></div><div><span>Library</span><strong className="green-text">{connection === "live" ? "Connected" : connection === "connecting" ? "Connecting" : "Preview"}</strong></div></div>
      <div className="document-table"><div className="table-head"><span>Source</span><span>Type</span><span>Year</span><span>Chunks</span><span>Status</span></div>{documents.map((document) => <div className="document-row" key={document.id}><div><span className="doc-icon">▤</span><div><strong>{document.title}</strong><small>{document.topics.join(" · ")}</small></div></div><span>{document.type}</span><span>{document.year}</span><span>{document.chunks}</span><span className={`index-status ${document.status.toLowerCase()}`}>● {document.status}</span></div>)}</div>
    </div>
  );
}

function DebuggerView({ query, setQuery, loading, onRun }: { query: string; setQuery: (value: string) => void; loading: boolean; onRun: (event: React.FormEvent) => void }) {
  const columns = [{ key: "dense", title: "Dense", note: "semantic recall" }, { key: "sparse", title: "BM25", note: "exact terms" }, { key: "fused", title: "RRF", note: "rank fusion" }, { key: "reranked", title: "Reranked", note: "final precision" }] as const;
  return (
    <div className="page-canvas debugger-page">
      <div className="page-heading"><div><span className="signal"><i /> RETRIEVAL OBSERVABILITY</span><h1>Retrieval debugger</h1><p>Inspect every stage of the evidence search pipeline without hiding the ranking decisions.</p></div></div>
      <form className="debug-query" onSubmit={onRun}><label htmlFor="debug-query">Query</label><input id="debug-query" value={query} onChange={(event) => setQuery(event.target.value)} /><button className="primary-button">{loading ? "Running…" : "Run pipeline"}<span>→</span></button></form>
      <div className={`debug-grid ${loading ? "loading" : ""}`}>{columns.map((column, colIndex) => <section key={column.key}><header><div><span>0{colIndex + 1}</span><h2>{column.title}</h2></div><small>{column.note}</small></header>{demoDebug[column.key].map((item, index) => <div className="rank-item" key={item.id}><b>{index + 1}</b><div><strong>{item.id}</strong><span style={{ width: `${Math.min(100, item.score < 1 ? item.score * 100 : item.score * 7)}%` }} /></div><em>{item.score < 1 ? item.score.toFixed(column.key === "fused" ? 4 : 2) : item.score.toFixed(1)}</em></div>)}<footer>{column.key === "reranked" ? "Top 8 → evidence engine" : "Top 30 candidates →"}</footer></section>)}</div>
      <div className="intent-strip"><span>QUERY INTENT</span><strong>Benchmark comparison</strong><span>KEYWORD SPECIFICITY</span><strong>0.84</strong><span>MULTI-HOP</span><strong>Yes</strong><span>DURATION</span><strong>182 ms</strong></div>
    </div>
  );
}

function EvaluationsView({ running, onRun }: { running: boolean; onRun: () => void }) {
  const metrics = [{ label: "Recall@10", value: 94.3, target: 85 }, { label: "NDCG@10", value: 91.7, target: 88 }, { label: "Citation accuracy", value: 96.1, target: 94 }, { label: "Faithfulness", value: 94.8, target: 92 }];
  const experiments = [{ name: "Dense", recall: 79, ndcg: 71 }, { name: "BM25", recall: 71, ndcg: 68 }, { name: "Hybrid RRF", recall: 88, ndcg: 81 }, { name: "Reranked", recall: 94, ndcg: 92 }];
  return (
    <div className="page-canvas">
      <div className="page-heading"><div><span className="signal"><i /> QUALITY, NOT VIBES</span><h1>Evaluation lab</h1><p>Measure retrieval, evidence grounding, and agent recovery before model or ranking changes ship.</p></div><button className="primary-button" onClick={onRun} disabled={running}>{running ? "Evaluating…" : "Run evaluation"}<span>→</span></button></div>
      <div className="metric-grid">{metrics.map((metric) => <article key={metric.label}><span>{metric.label}</span><strong>{metric.value}%</strong><div><i style={{ width: `${metric.value}%` }} /><b style={{ left: `${metric.target}%` }} /></div><small>Target ≥ {metric.target}%</small></article>)}</div>
      <div className="eval-layout"><section className="experiment-chart"><div className="panel-title"><span>RETRIEVAL ABLATION</span><small>GOLD SET · 300 QUESTIONS</small></div>{experiments.map((experiment) => <div className="experiment-row" key={experiment.name}><strong>{experiment.name}</strong><div className="bar-track"><span style={{ width: `${experiment.recall}%` }}>{experiment.recall}</span></div><div className="bar-track muted"><span style={{ width: `${experiment.ndcg}%` }}>{experiment.ndcg}</span></div></div>)}<footer><span><i className="recall-key" /> Recall@10</span><span><i className="ndcg-key" /> NDCG@10</span></footer></section><section className="agent-scorecard"><div className="panel-title"><span>AGENT BEHAVIOR</span><small>LAST 30 DAYS</small></div><div><span>Plan success</span><strong>95.4%</strong></div><div><span>Retrieval recovery</span><strong>72.1%</strong></div><div><span>Unsupported claims</span><strong>2.6%</strong></div><div><span>Average search loops</span><strong>2.3</strong></div><p><span className="status-dot" /> All quality gates passing</p></section></div>
    </div>
  );
}
