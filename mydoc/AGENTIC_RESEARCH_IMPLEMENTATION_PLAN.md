# Agentic Research 実装計画

## 方針

本PoCでは、複数ソース検索とDeep Researchの自律性を重視する。

中核の調査処理は AgentCore Runtime 上の Research Agent に持たせる。GenU はエンドユーザー向けUI、開発検証用のUse Case Builder連携、認証済みフロントエンドとして利用する。

```text
GenU Research Page / Agentic Research Page
GenU Use Case Builder adapter
        |
        v
Existing AgentCore hooks / common response components
        |
        v
AgentCore Research Runtime
        |
        +-- OpenSearch MCP Server
        +-- Neptune Graph MCP Server
        +-- Bedrock Knowledge Base MCP Server
        +-- S3 Document Fetch MCP Server
        +-- Citation Verify MCP Server
```

## 既存実装の前提

このリポジトリには、GenU WebからAgentCore Runtimeを呼ぶ経路がすでに存在する。

主な入口:

```text
packages/web/src/hooks/useResearchAgent.ts
packages/web/src/hooks/useAgentCoreApi.ts
packages/web/src/pages/ResearchAgentPage.tsx
packages/types/src/agent-builder.d.ts
packages/types/src/agent-core.d.ts
packages/cdk/lambda-python/research-agent-core-runtime/
```

`useResearchAgent.ts` は `useAgentCoreApi.ts` を経由して AgentCore Runtime を呼び出す。`AgentCoreRuntimeRequest` には `mode` があり、現状は `technical-research` / `mini-research` / `general-research` を扱う。

したがって、Agentic Research用に `packages/cdk/lambda/api/routes/agenticResearch.ts` のような新規APIをフルスクラッチで作ることは初期方針にしない。まず既存のResearch Agent経路に `agentic-research` mode を追加し、既存のストリーミング、runtime選択、ファイル処理、認証済みユーザー情報の流れを再利用する。

AgentCore Runtime側も、既存実装は Claude Agent SDK + MCP を前提にしている。

```text
packages/cdk/lambda-python/research-agent-core-runtime/src/agent.py
packages/cdk/lambda-python/research-agent-core-runtime/src/tools.py
packages/cdk/lambda-python/research-agent-core-runtime/mcp-configs/
```

`ToolManager` が `mcp.json` を読み、`agent.py` の `allowed_tools` で利用可能ツールを制御している。そのため、OpenSearch / Neptune / Knowledge Base / S3 / Citation Verify は、原則としてMCPサーバとして追加する。in-processカスタムツールを使う場合は、MCP方式と比較したうえで明示的に採用判断する。

重要: 現状の `allowed_tools` はmode非依存のフラットな固定リストである。このままAgentic Research用ツールを追加すると、既存の `technical-research` / `general-research` に業務データ検索ツールが露出し、逆に `agentic-research` でもBrave/Tavily等のオープンWeb検索ツールが使える状態になりうる。Phase 1で `allowed_tools` をmode別に切り替えるリファクタを必須とする。

## 役割分担

### GenU

- 既存Research Agentページに `agentic-research` mode を追加する
- 必要になった段階で、評価者向けの専用Agentic Researchページを追加する
- 回答、引用、関係パス、調査ステップ、検索トレースを表示する
- Use Case Builderから同じResearch経路を呼べるようにする
- Cognito認証済みユーザー情報をAgentCore Runtimeへ渡す

### AgentCore Runtime

- 調査計画を立てる
- 必要なMCPツールを選択する
- 追加検索、関係探索、反証確認を行う
- 根拠付き回答を生成する
- 長時間調査や多段探索を担当する

### Deterministic MCP Servers

エージェントの自律性は保つが、業務RAGで重要な制約はMCPサーバ側で担保する。

- 権限チェック
- 版管理
- 有効期間チェック
- 引用検証
- 関係パス取得
- 文書種別優先度

重要: 権限チェック、版管理、有効期間チェックは、Agentが任意で呼び出す補助ツールにはしない。検索MCPサーバ内部で常時強制適用する。Agentがフィルタ処理をスキップできる設計にしない。

## 実装対象

### 1. 共通型定義

追加候補:

```text
packages/types/src/agentic-research.d.ts
```

主な型:

```ts
AgenticResearchRequest
AgenticResearchResponse
ResearchStep
ResearchTrace
RetrieverResult
Citation
GraphPath
```

`AgenticResearchRequest` には、検索MCPサーバが強制フィルタに使う権限コンテキストを明示的に含める。

```ts
type AgenticResearchAuthContext = {
  userId: string;
  orgCode: string;
  deptCodes?: string[];
  allowedConfidentialityLevels?: string[];
  groups?: string[];
};
```

この権限コンテキストは、Cognito claimsからGenU Web / AgentCore requestへ渡し、各検索MCPサーバの必須入力または環境側コンテキストとして参照できるようにする。ここが切れると、`org_code` / `confidentiality` による絞り込みが形骸化する。

レスポンスは、専用画面でもUse Case Builderでも同じ形で扱えるようにする。

初期は同期ストリーミングで開始するが、Deep Researchの長時間化に備え、型には最初から `jobId` / `status` を予約する。これにより、後から非同期ジョブ方式へ切り替えてもUIとUse Case Builder adapterを壊しにくくする。

### 2. 既存Research Agent経路の拡張

改修候補:

```text
packages/types/src/agent-builder.d.ts
packages/web/src/hooks/useResearchAgent.ts
packages/web/src/hooks/useAgentCoreApi.ts
packages/web/src/pages/ResearchAgentPage.tsx
```

役割:

- `AgentCoreRuntimeRequest.mode` に `agentic-research` を追加する
- `useAgentCoreApi.ts` のmode許可リストへ `agentic-research` を追加する
- ResearchページにAgentic Research modeを追加する
- 既存のAgentCore Runtime呼び出し、ストリーミング、ファイル処理を再利用する
- AgentCore Runtime側で `allowed_tools` をmode別に切り替える
- `technical-research` / `mini-research` / `general-research` に業務データ検索MCPツールを露出しない
- `agentic-research` にBrave/Tavily等のオープンWeb検索ツールを露出しない

新規API adapterは、既存経路では要件を満たせない場合の拡張候補に留める。

### 3. AgentCore Runtime / MCP拡張

既存の以下を拡張する。

```text
packages/cdk/lambda-python/research-agent-core-runtime/
```

追加候補:

```text
prompts/agentic-research.md
src/agent.py
src/tools.py
```

MCP設定は、まず既存の単一 `mcp-configs/mcp.json` と `ToolManager.get_mcp_config(mcp_servers=[...])` の名前フィルタを活用する。必要になった場合のみ、`MCP_CONFIG_PATH` のmode別切り替え、またはmode別mcp.json分割を検討する。

追加するロジック:

```text
mode -> allowed MCP server names
mode -> allowed tool names
```

例:

```text
technical-research:
  MCP servers: brave-search, tavily, aws-knowledge
  allowed_tools: web/search/documentation系

agentic-research:
  MCP servers: knowledge-base-retriever, s3-document-fetcher, opensearch-retriever, neptune-graph-retriever, citation-verifier
  allowed_tools: 業務RAG用ツールのみ
```

MCPサーバ候補:

```text
opensearch-retriever
neptune-graph-retriever
knowledge-base-retriever
s3-document-fetcher
citation-verifier
```

役割:

- Agentが使うMCPサーバを登録する
- mode別MCPサーバ集合を定義する
- mode別 `allowed_tools` を定義する
- 調査用system promptを追加する
- 回答フォーマットを固定する
- 引用と関係パスを構造化して返す

検索MCPサーバは、`org_code` / `status` / `effective_from` / `effective_to` / `confidentiality` 等のフィルタを内部で強制適用する。

MCPサーバの実行方式はPhase 1で決める。既存MCPサーバと同じ `npx` / `uvx` サブプロセス起動にするか、AgentCore Runtime内のin-processカスタムツールにするかで、IAM資格情報、VPC到達性、コールドスタート、パッケージングが変わるためである。

### 4. CDK拡張

既存の以下を拡張する。

```text
packages/cdk/lib/construct/research-agent-core.ts
packages/cdk/lib/research-agent-core-stack.ts
packages/cdk/lib/construct/api.ts
packages/cdk/lib/stack-input.ts
```

追加する設定:

```json
"agenticResearchEnabled": true,
"agenticResearchOpenSearchEndpoint": "",
"agenticResearchNeptuneEndpoint": "",
"agenticResearchKnowledgeBaseId": "",
"agenticResearchRawDocumentBucketName": "",
"agenticResearchMaxIterations": 20,
"agenticResearchModeEnabled": true
```

CDKで行うこと:

- AgentCore Runtimeへ環境変数を渡す
- OpenSearch / Neptune / S3 / Bedrock KBへのIAM権限を付与する
- 既存Research Agent RuntimeへAgentic Research用MCP設定を渡す
- 必要に応じてOpenSearch / Neptune自体の作成もCDK化する

NeptuneはVPC内接続になる可能性が高い。AgentCore RuntimeからNeptuneへ到達できるよう、`RuntimeNetworkConfiguration`、VPC、Security Group、PrivateLinkの要否をPhase 4開始前に確定する。

### 5. GenU UIコンポーネント

初期実装では、既存の `ResearchAgentPage.tsx` に `agentic-research` modeを追加する。専用ページは、評価者向けに引用・関係パス・検索トレースを詳細表示したくなった段階で分離する。

専用ページ化する場合の追加候補:

```text
packages/web/src/pages/AgenticResearchPage.tsx
packages/web/src/hooks/useAgenticResearch.ts
packages/web/src/components/agenticResearch/ResearchAnswerView.tsx
packages/web/src/components/agenticResearch/CitationList.tsx
packages/web/src/components/agenticResearch/GraphPathView.tsx
packages/web/src/components/agenticResearch/ResearchTraceView.tsx
```

表示する情報:

- 回答
- 引用
- 関係パス
- 調査ステップ
- Retriever別検索結果
- 注意点、未確認事項

### 6. Use Case Builder adapter

開発検証用に、Use Case Builderから同じResearch経路を呼べるようにする。

追加するplaceholder案:

```text
{{agenticResearch}}
{{agenticResearch:question}}
```

改修候補:

```text
packages/web/src/components/useCaseBuilder/UseCaseBuilderView.tsx
packages/web/src/components/useCaseBuilder/UseCaseBuilderHelp.tsx
packages/web/tests/use-case-builder/items.test.ts
```

Use Case Builderでは、回答本文と引用要約だけを返す簡易表示にする。Use Case Builderは本番UIではなく、MCPサーバ、prompt、レスポンス形式の開発検証用として使う。

## フェーズ

### Phase 1: 既存Research経路への最小追加

目的: 既存のResearch Agent経路にAgentic Research modeを追加し、GenUから呼べることを確認する。

作業:

- 共通型を追加する
- `AgentCoreRuntimeRequest.mode` に `agentic-research` を追加する
- `useAgentCoreApi.ts` のmode許可リストへ `agentic-research` を追加する
- `ResearchAgentPage.tsx` にAgentic Research modeを追加する
- `prompts/agentic-research.md` を追加する
- `allowed_tools` をmode別に切り替える
- mode別MCPサーバ集合を定義する
- MCPサーバの実行方式を決める
- Cognito claimsからAgenticResearchAuthContextを作り、AgentCore Runtime / MCPサーバへ渡す経路を決める
- ダミーMCPサーバ、または既存MCPサーバで調査ステップと回答を返す
- `AgenticResearchResponse` に `jobId` / `status` を予約する

完了条件:

- GenUのResearch画面からAgentic Research modeで質問できる
- AgentCore Runtimeが呼ばれる
- 回答、引用、調査ステップのダミーデータが表示される
- `agentic-research` modeでBrave/Tavily等のオープンWeb検索ツールが呼べない
- `technical-research` / `general-research` modeに業務データ検索MCPツールが露出しない
- 権限コンテキストがAgentCore Runtimeまで到達する

### Phase 2: Bedrock KB / S3 MCP Server + 安全制約

目的: 既存GenUのKnowledge BaseとS3文書をAgentから使えるようにし、最初から安全制約を強制する。

作業:

- Bedrock Knowledge Base MCP Serverを追加する
- S3 Document Fetch MCP Serverを追加する
- 検索MCPサーバ内部で `org_code` / `status` / `effective_from` / `effective_to` を強制適用する
- `AgenticResearchAuthContext` を検索MCPサーバの必須入力として扱う
- Citation Verify MCP Serverの最小版を追加する
- 引用形式を統一する
- Use Case Builder placeholderを追加する

完了条件:

- AgentがKnowledge Base検索を実行できる
- 失効文書、権限外文書、無効ステータス文書を回答根拠にしない
- 引用付き回答を返せる
- Use Case Builderから同じ経路を検証できる

### Phase 3: OpenSearch MCP Server

目的: 日本語全文・hybrid検索をAgentのMCPツールとして使う。

作業:

- OpenSearch接続情報をCDK contextに追加する
- OpenSearch MCP Serverを実装する
- 検索MCPサーバ内部で権限・版・有効期間フィルタを強制適用する
- RetrieverResult形式へ正規化する
- 検索ログをResearchTraceに入れる

完了条件:

- AgentがOpenSearchを呼び、検索結果を回答に使える
- Retriever別結果がGenU UIに表示される

### Phase 4: Neptune Graph MCP Server

目的: 関係パス探索をAgentのMCPツールとして使う。

作業:

- Neptune接続情報をCDK contextに追加する
- AgentCore RuntimeからNeptuneへの到達性を設計する
- VPC / Security Group / PrivateLink / public network のどれを使うか決める
- openCypher実行MCP Serverを実装する
- GraphPath形式へ正規化する
- EXCEPTION_OF / REFERS_TO / DEFINES / EXPLAINSを探索できるようにする

完了条件:

- AgentがOpenSearchのヒットを起点にNeptune探索できる
- 回答に関係パスが表示される

### Phase 5: 検証用制約の強化

目的: Phase 2で入れた安全制約を強化し、業務RAGとしての信頼性を上げる。

作業:

- Citation Verify MCP Serverを強化する
- Effective Date Filterを各検索MCPサーバ内部で共通化する
- org_code / status / effective_from / effective_toの二重チェックをUI投入前にも入れる
- 文書種別優先度を適用する

完了条件:

- 失効文書を回答根拠にしない
- 引用できない主張を抑制できる
- 上位文書と下位文書の矛盾を明記できる

### Phase 6: Deep Research化

目的: 追加検索、反証確認、複数ステップ調査を実装する。

作業:

- 調査計画生成をpromptに追加する
- 最大探索回数を制御する
- 追加検索要否判定を入れる
- 反証・矛盾チェックを入れる
- `jobId` / `status` を使って非同期ジョブ化できるようにする
- 長時間化する場合は非同期ジョブ化する

完了条件:

- Agentが複数MCPツールを使って追加探索できる
- 調査ステップがUIに表示される
- 通常RAGより深い根拠付き回答が出せる

## 初期スコープ

最初に作るべき最小スコープ:

```text
既存Research Agentページ
  + agentic-research mode追加
  + AgentCore Runtime呼び出し再利用
  + Bedrock Knowledge Base MCP Server
  + S3 Document Fetch MCP Server
  + Citation Verify MCP Server最小版
  + Citation表示
  + Use Case Builder placeholder
```

OpenSearchとNeptuneは、MCPインターフェースと型を先に設計してから段階的に接続する。

## リスクと注意点

- AgentCore RuntimeからNeptuneへ接続する場合、VPC到達性が主要リスクになる
- MCPサーバの実行方式、パッケージング、認証情報の渡し方をPhase 1で決める
- `allowed_tools` を共有リストのままにすると、mode間でツールが漏れる
- mode別MCPサーバ集合を定義しないと、既存リサーチmodeと業務RAG modeの境界が崩れる
- Agentが安全制約を迂回できないよう、フィルタは検索MCPサーバ内部で強制する
- 権限コンテキストがMCPサーバまで届かないと、org_code / confidentiality フィルタが形骸化する
- 同期ストリーミングから非同期ジョブへ移行できるよう、レスポンス型に `jobId` / `status` を予約する

## 判断

この構成では、AgentCoreが自律的な探索を担当し、GenUがエンドユーザー体験と開発検証体験を担当する。

Use Case Builderは本番UIではなく、API・プロンプト・MCPサーバ・レスポンス形式の検証用として使う。本番利用ではResearch Agentページまたは専用Agentic Researchページを使う。
