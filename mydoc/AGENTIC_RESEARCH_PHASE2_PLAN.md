# Agentic Research Phase 2 実装計画

## 目的

Phase 2では、Phase 1で追加した `agentic-research` mode に、管理された業務データソースを検索する最小ツールを接続する。

対象は以下に絞る。

```text
Bedrock Knowledge Base MCP Server
S3 Document Fetch MCP Server
Citation Verify MCP Server 最小版
AgenticResearchAuthContext の受け渡し
```

OpenSearch / Neptune は Phase 3 以降で接続する。

## 前提

Phase 1で以下は実装済み。

- `agentic-research` mode
- Research画面でのmode選択
- mode別 `allowed_tools`
- mode別MCP server集合
- `agentic-research` からWebFetch / Brave / Tavilyを隔離
- `prompts/agentic-research.md`

Phase 2では、この隔離されたmodeに業務RAG用MCPツールだけを追加する。

## 方針

### MCPサーバ方式

初期実装は、AgentCore Runtime内で起動できるPython製MCPサーバにする。

理由:

- Bedrock KB / S3 はAWS SDKで呼びたい
- AgentCore RuntimeのIAMロールを利用しやすい
- `npx` / `uvx` で外部パッケージを都度起動するより、PoCでは実装とデバッグがしやすい
- 将来、OpenSearch / Neptune toolも同じ方式に寄せやすい

追加候補:

```text
packages/cdk/lambda-python/research-agent-core-runtime/src/mcp_servers/knowledge_base_retriever.py
packages/cdk/lambda-python/research-agent-core-runtime/src/mcp_servers/s3_document_fetcher.py
packages/cdk/lambda-python/research-agent-core-runtime/src/mcp_servers/citation_verifier.py
```

`mcp-configs/mcp.json` には、これらのMCPサーバ起動定義を追加する。

業務MCPサーバは、LLMが自由に渡すtool inputを信頼しない。権限情報、組織情報、許可機密レベル、時点情報などのセキュリティ上重要な値は、AgentCore Runtime側で検証・確定し、MCPサーバへ帯域外で渡す。

## 認可コンテキスト

### 型

追加候補:

```text
packages/types/src/agentic-research.d.ts
```

```ts
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

export type AgenticResearchResponse = {
  answer?: string;
  jobId?: string;
  status: AgenticResearchStatus;
  citations?: Citation[];
  graphPaths?: GraphPath[];
  trace?: ResearchTrace;
};
```

`Citation` / `GraphPath` / `ResearchTrace` / `RetrieverResult` も同じファイルに定義する。

### 受け渡し

```text
idToken
  -> useResearchAgent / useAgentCoreApi
  -> AgentCoreRuntimeRequest
  -> AgentCoreRequest
  -> research-agent-core-runtime/app.py
  -> JWT署名検証
  -> 検証済みclaimsからAgenticResearchAuthContextを生成
  -> AgentManager.process_request_streaming
  -> MCP server process env / session context
```

Phase 2では、クライアントが申告した `authContext` を信頼しない。ブラウザは既に `InvokeAgentRuntime` を直接呼べるため、payload内の `auth_context` は改ざん可能である。したがって、クライアントから `auth_context` は受け取らない。

代わりに、`idToken` をpayloadに含め、Runtime側でCognito JWKSを使って検証する。検証済みclaimsから `userId` / `groups` / `orgCode` / `deptCodes` / `allowedConfidentialityLevels` を生成する。

JWT検証では、最低限以下を必須にする。

- JWKSによる署名検証に成功すること
- `iss` が対象Cognito User Pool issuerと一致すること
- `aud` が対象Cognito App Client IDと一致すること
- `exp` が現在時刻より後であること
- `token_use == "id"` であること
- `sub` が存在すること

`orgCode` / `deptCodes` / `allowedConfidentialityLevels` は、Cognito claimsに存在しない場合に備え optional にする。ただし、データセットが `orgCode` 必須の場合は検索を拒否する。

MCPサーバへの渡し方:

```text
AgentCore request id_token
  -> Runtime validates JWT
  -> Runtime creates AUTH_CONTEXT_JSON
  -> ToolManager.get_mcp_config() injects AUTH_CONTEXT_JSON into business MCP server env
  -> MCP server reads AUTH_CONTEXT_JSON from env
```

LLMが構成するtool input schemaには `authContext` を含めない。LLMは `query` / `topK` / `sourceS3Uri` など、業務上安全な検索条件だけを渡す。

ただし、MCPサーバ側では以下を原則とする。

- `AUTH_CONTEXT_JSON` がない場合は検索しない
- `orgCode` が必要なデータセットで `orgCode` がない場合は検索しない
- `status = active` を常に強制する
- `effective_from <= effectiveAsOfDate`、`effective_to` が未設定または `effectiveAsOfDate < effective_to` を常に強制する
- Phase 2では `effectiveAsOfDate` はRuntime側の現在日付を使う。ユーザー指定の `requestedAsOfDate` は受け取っても既定では採用しない

## Bedrock Knowledge Base MCP Server

### 役割

Bedrock Knowledge Base の `Retrieve` を実行し、結果を `RetrieverResult[]` に正規化する。

### 入力

```json
{
  "query": "A手続きで承認不要となる例外条件を教えて",
  "topK": 10
}
```

### 出力

```json
{
  "results": [
    {
      "sourceType": "bedrock-knowledge-base",
      "documentId": "doc-001",
      "chunkId": "doc-001-art-12",
      "title": "A手続き規程",
      "content": "第12条 ...",
      "score": 0.87,
      "metadata": {
        "orgCode": "org-a",
        "status": "active",
        "effectiveFrom": "2026-04-01",
        "effectiveTo": null
      },
      "citation": {
        "sourceS3Uri": "s3://...",
        "page": 3
      }
    }
  ]
}
```

### 実装メモ

- CDKで `KNOWLEDGE_BASE_ID` / `MODEL_REGION` をAgentCore Runtime環境変数に渡す
- Runtime roleに `bedrock:Retrieve` 相当の権限を付与する
- Bedrock KB metadata filterで可能な範囲の `org_code` / `status` / `effective_from` / `effective_to` を適用する
- Retriever結果を返す前にMCPサーバ側で二重チェックする
- `AUTH_CONTEXT_JSON` がない場合は検索を拒否する
- `effectiveAsOfDate` は原則Runtime側の現在日付を使う。ユーザー指定の時点検索を許可する場合は、明示的な要件として別途設計する
- 外部型・回答出力は `orgCode` / `effectiveFrom` などのcamelCaseに寄せる。KB metadata filterの実キーが `org_code` / `effective_from` などのsnake_caseの場合は、Retriever内の正規化層で吸収する

## S3 Document Fetch MCP Server

### 役割

Citationで示されたS3 URIやdocument idから、原文または処理済みチャンクを取得する。

### 入力

```json
{
  "sourceS3Uri": "s3://bucket/path/document.md"
}
```

### 出力

```json
{
  "documentId": "doc-001",
  "content": "...",
  "metadata": {
    "orgCode": "org-a",
    "status": "active"
  }
}
```

### 実装メモ

- CDKで対象S3 bucket名を環境変数に渡す
- Runtime roleに対象bucketのread権限を付与する
- 任意S3 URIを読ませない。許可bucket / prefixだけ許可する
- S3 URIは正規化し、`..` やprefix抜けを拒否する
- 取得後にmetadataの `orgCode` / `status` / 有効期間を再チェックする
- `AUTH_CONTEXT_JSON` がない場合は取得を拒否する

## Citation Verify MCP Server

### 役割

LLMが回答に使う引用候補が、実際に取得済みcontextに含まれているかを検証する。

LLMが渡した `contexts` は信頼しない。Retriever MCPサーバは検索結果をセッションスコープのストアに保存し、Citation Verify MCP Serverはそのストアから検証対象contextを読む。

セッションスコープストアは、Runtimeが確定したセッションID配下に置く。ただしリクエスト終了時にworkspace (`/tmp/ws`) は削除されるため、ストアのbase dirはworkspace外（例: `/tmp/agentic-research-session`）に置く。`SESSION_ID` と `RESEARCH_SESSION_STORE_DIR` をKB Retriever / S3 Fetcher / Citation Verifierの各MCPサーバenvへ注入し、別プロセス・別リクエスト間で同じ保存先を参照できるようにする。

Phase 2では最小版として、以下のみ行う。

- citationの `documentId` / `chunkId` が取得済みresultに存在するか
- 引用本文の一部がcontextに含まれるか
- status / effective dateが有効か

この抜粋一致はPhase 2の最小ヒューリスティックであり、正当な要約・言い換えを偽陰性にする可能性がある。Phase 3以降でNLI/LLM verifier等へ置き換える前提とする。また `claims=[]` は「検証すべきclaimなし」として `verified=true` になり得るため、呼び出し側でclaim抽出の失敗とは区別する。

### 入力

```json
{
  "claims": [
    {
      "text": "A手続きでは災害時に承認不要となる",
      "citationIds": ["doc-001-art-12"]
    }
  ]
}
```

### 出力

```json
{
  "verified": false,
  "issues": [
    {
      "claim": "A手続きでは災害時に承認不要となる",
      "reason": "citation_not_found"
    }
  ]
}
```

## Runtime側変更

対象:

```text
packages/cdk/lambda-python/research-agent-core-runtime/src/agent.py
packages/cdk/lambda-python/research-agent-core-runtime/src/tools.py
packages/cdk/lambda-python/research-agent-core-runtime/app.py
```

変更:

- `agentic-research` のMCPサーバ集合に以下を追加する
  - `knowledge-base-retriever`
  - `s3-document-fetcher`
  - `citation-verifier`
- `AGENTIC_RESEARCH_ALLOWED_TOOLS` に各MCP tool名を追加する
- `id_token` をrequestから受け取り、Runtime側でJWT署名検証する
- `mode == "agentic-research"` かつ `id_token` がない、またはJWT検証に失敗した場合は、`app.py` でAgentManager呼び出し前にフェイルファストする
- 検証済みclaimsから `AgenticResearchAuthContext` を生成する
- ToolManagerが業務MCPサーバのenvへ `AUTH_CONTEXT_JSON` を注入する
- ToolManagerが業務MCPサーバのenvへ `SESSION_ID` / `RESEARCH_SESSION_STORE_DIR` を注入する
- non-agentic modeでは、リクエスト由来の `mcp_servers` をWeb research用MCPサーバ集合との積集合に制限する
- Citation Verify用に、Retriever結果のセッションスコープストアを用意する

## CDK変更

対象:

```text
packages/cdk/lib/construct/research-agent-core.ts
packages/cdk/lib/research-agent-core-stack.ts
packages/cdk/lib/construct/api.ts
packages/cdk/lib/stack-input.ts
packages/cdk/cdk.json
```

追加候補:

```json
"agenticResearchKnowledgeBaseId": null,
"agenticResearchDocumentBucketName": null,
"agenticResearchDocumentPrefix": "",
"agenticResearchCognitoUserPoolId": null,
"agenticResearchCognitoAppClientId": null
```

方針:

- `agenticResearchKnowledgeBaseId` が未指定なら、既存の `ragKnowledgeBaseId` または作成済みKB IDを流用する
- `agenticResearchKnowledgeBaseId` を明示指定した場合も、Phase 2ではKBリージョンは `modelRegion` 前提とする。`modelRegion` 外のKB接続が必要になった時点で、別途 `agenticResearchKnowledgeBaseRegion` 相当の入力パラメータを追加する
- `agenticResearchDocumentBucketName` が未指定なら、Knowledge Base data source bucketを流用する
- Runtime roleにBedrock KB retrieve権限とS3 read権限を付与する
- RuntimeへJWT検証用のCognito user pool id / app client id / issuer / regionを環境変数で渡す
- `AGENTIC_RESEARCH_BUSINESS_TIMEZONE` はPhase 2ではRuntime既定値 `Asia/Tokyo` を使う。CDK入力として公開するのは、業務タイムゾーンを環境ごとに切り替える要件が出た時点でよい
- `packages/types/src/agentic-research.d.ts` を追加した場合は `packages/types/src/index.d.ts` からexportする

## Web側変更

対象:

```text
packages/web/src/hooks/useAgentCoreApi.ts
packages/web/src/hooks/useResearchAgent.ts
```

変更:

- Amplify Auth sessionから `idToken` を取り出す
- `mode === 'agentic-research'` の場合、AgentCore request payloadに `id_token` を含める
- `auth_context` はpayloadに含めない

Phase 2では `orgCode` はCognito claimsになければ未設定でよい。ただし、MCPサーバ側でorgCode必須のデータセットなら検索を拒否する。

セキュリティ注意:

- `id_token` はRuntime側で署名検証する
- クライアントが申告したユーザーID、orgCode、groups、confidentialityは信頼しない
- RuntimeへJWTを渡すことによるログ出力リスクを避けるため、payloadログには `id_token` を出さない
- 既存の `useAgentCoreApi.ts` の `console.log('AgentCoreRequest payload:', JSON.stringify(agentCoreRequest, null, 2))` は、`id_token` 追加前に削除するか、`id_token` をredactしたオブジェクトだけを出力する

## 完了条件

- `agentic-research` modeでBedrock KB MCP Serverが呼べる
- `agentic-research` modeでS3 Document Fetch MCP Serverが呼べる
- `agentic-research` modeでCitation Verify MCP Serverが呼べる
- Brave / Tavily / WebFetch は引き続き使えない
- `technical-research` / `general-research` に業務RAG MCP toolsが露出しない
- non-agentic modeで `mcp_servers=["knowledge-base-retriever"]` のような細工をしても業務MCPサーバがロードされない
- idTokenがRuntimeに届く
- RuntimeがJWTを検証し、検証済みclaimsからauthContextを生成する
- `agentic-research` modeでidToken欠落またはJWT検証失敗の場合、RuntimeがAgent起動前にエラーを返す
- AUTH_CONTEXT_JSONがない検索は拒否される
- status / effective dateの二重チェックがMCPサーバ側で行われる
- Citation VerifyはLLMが渡したcontextsではなく、Retriever / Fetcherが保存したセッションスコープのcontextを検証する
- マルチターンで前ターンに取得したcontextを引用検証できる
- デプロイ後、uv runで起動される業務MCPサブプロセスにAWS認証情報が伝播し、boto3経由のKB/S3アクセスが成功することを確認する

## テスト

最小テスト:

- `agentic-research` のMCP server集合に業務MCPだけが入る
- `agentic-research` のallowed_toolsにWeb系toolが入らない
- `technical-research` のMCP server集合に業務MCPが入らない
- non-agentic modeのrequested `mcp_servers` に業務MCPを指定してもロードされない
- idTokenなしのKB検索が拒否される
- 不正JWTのKB検索が拒否される
- JWTの `iss` / `aud` / `exp` / `token_use` が不正な場合に拒否される
- AUTH_CONTEXT_JSONなしのKB検索が拒否される
- statusがactiveでない結果が除外される
- effective date範囲外の結果が除外される
- Citation VerifyがLLM提供contextsを信頼しない
- orgCodeなしユーザーのKB検索が単一filterで成功する
- request間のworkspace cleanup後も同一SESSION_IDのcitation検証ストアが残る

Runtimeパッケージには現時点でpytest等のテスト基盤が薄いため、Phase 2着手時に最小pytest環境を追加する。

## Phase 2でやらないこと

- OpenSearch直接検索
- Neptune Graph探索
- RRF / rerank
- 非同期Deep Research job
- 本格的なCitation Accuracy評価

これらはPhase 3以降で扱う。
