// Types for the agentic-research mode (Phase 2: governed business RAG).
//
// AgenticResearchAuthContext is derived exclusively from a Runtime-verified
// Cognito id_token. Clients never construct or send this shape directly.

export type AgenticResearchAuthContext = {
  userId: string;
  orgCode?: string;
  deptCodes?: string[];
  groups?: string[];
  allowedConfidentialityLevels?: string[];
};

export type AgenticResearchStatus =
  | 'streaming'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed';

export type AgenticResearchRequest = {
  query: string;
  requestedAsOfDate?: string;
  jobId?: string;
};

export type RetrieverResultMetadata = {
  orgCode?: string;
  status?: string;
  effectiveFrom?: string;
  effectiveTo?: string | null;
  confidentiality?: string;
};

export type Citation = {
  sourceS3Uri?: string;
  page?: number;
  documentId?: string;
  chunkId?: string;
};

export type RetrieverResult = {
  sourceType: string;
  documentId: string;
  chunkId?: string;
  title?: string;
  content: string;
  score?: number;
  metadata: RetrieverResultMetadata;
  citation?: Citation;
};

export type GraphPath = {
  path: string[];
  relation: string;
};

export type ResearchStep = {
  description: string;
  toolName?: string;
};

export type ResearchTrace = {
  steps: ResearchStep[];
  retrieverResults?: RetrieverResult[];
};

export type AgenticResearchResponse = {
  answer?: string;
  jobId?: string;
  status: AgenticResearchStatus;
  citations?: Citation[];
  graphPaths?: GraphPath[];
  trace?: ResearchTrace;
};
