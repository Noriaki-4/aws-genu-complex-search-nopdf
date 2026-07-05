import { Construct } from 'constructs';
import {
  Effect,
  PolicyStatement,
  Role,
  ServicePrincipal,
} from 'aws-cdk-lib/aws-iam';
import { Stack, RemovalPolicy } from 'aws-cdk-lib';
import {
  Bucket,
  BlockPublicAccess,
  BucketEncryption,
} from 'aws-cdk-lib/aws-s3';
import {
  Runtime,
  RuntimeNetworkConfiguration,
  ProtocolType,
  AgentRuntimeArtifact,
} from '@aws-cdk/aws-bedrock-agentcore-alpha';
import { BucketInfo } from 'generative-ai-use-cases';
import * as path from 'path';

export interface ResearchAgentCoreProps {
  env: string;
  braveApiKey?: string;
  tavilyApiKey?: string;
  gatewayArns?: string[];
  // Agentic Research (Phase 2: governed business RAG for agentic-research mode)
  agenticResearchKnowledgeBaseId?: string;
  agenticResearchKnowledgeBaseRegion?: string;
  agenticResearchDocumentBucketName?: string;
  agenticResearchDocumentPrefix?: string;
  agenticResearchCognitoUserPoolId?: string;
  agenticResearchCognitoAppClientId?: string;
}

export class ResearchAgentCore extends Construct {
  private readonly _fileBucket: Bucket;
  private readonly _runtime: Runtime;
  private readonly _role: Role;

  constructor(scope: Construct, id: string, props: ResearchAgentCoreProps) {
    super(scope, id);

    const {
      env,
      braveApiKey = '',
      tavilyApiKey = '',
      gatewayArns,
      agenticResearchKnowledgeBaseId,
      agenticResearchKnowledgeBaseRegion,
      agenticResearchDocumentBucketName,
      agenticResearchDocumentPrefix = '',
      agenticResearchCognitoUserPoolId,
      agenticResearchCognitoAppClientId,
    } = props;

    // Create bucket
    this._fileBucket = new Bucket(this, 'ResearchAgentFileBucket', {
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // Create execution role
    this._role = this.createExecutionRole();

    // Configure role permissions
    this.configureRolePermissions(this._role, gatewayArns, {
      knowledgeBaseId: agenticResearchKnowledgeBaseId,
      knowledgeBaseRegion: agenticResearchKnowledgeBaseRegion,
      documentBucketName: agenticResearchDocumentBucketName,
      documentPrefix: this.normalizeDocumentPrefix(
        agenticResearchDocumentPrefix
      ),
    });

    // Create runtime
    this._runtime = this.createRuntime(env, braveApiKey, tavilyApiKey, {
      knowledgeBaseId: agenticResearchKnowledgeBaseId,
      knowledgeBaseRegion: agenticResearchKnowledgeBaseRegion,
      documentBucketName: agenticResearchDocumentBucketName,
      documentPrefix: this.normalizeDocumentPrefix(
        agenticResearchDocumentPrefix
      ),
      cognitoUserPoolId: agenticResearchCognitoUserPoolId,
      cognitoAppClientId: agenticResearchCognitoAppClientId,
    });
  }

  private createRuntime(
    env: string,
    propsBraveApiKey: string,
    propsTavilyApiKey: string,
    agenticResearch: {
      knowledgeBaseId?: string;
      knowledgeBaseRegion?: string;
      documentBucketName?: string;
      documentPrefix?: string;
      cognitoUserPoolId?: string;
      cognitoAppClientId?: string;
    }
  ): Runtime {
    const region = Stack.of(this).region;

    const environmentVariables: Record<string, string> = {
      MCP_CONFIG_PATH: '/var/task/mcp-configs/mcp.json',
      MAX_ITERATIONS: '200',
      CLAUDE_CODE_USE_BEDROCK: '1',
      AWS_REGION: region,
    };

    // Add API key from props or context
    const braveApiKey =
      propsBraveApiKey ||
      (this.node.tryGetContext('researchAgentBraveApiKey') as string) ||
      '';
    if (braveApiKey) {
      environmentVariables.BRAVE_API_KEY = braveApiKey;
    }

    const tavilyApiKey =
      propsTavilyApiKey ||
      (this.node.tryGetContext('researchAgentTavilyApiKey') as string) ||
      '';
    if (tavilyApiKey) {
      environmentVariables.TAVILY_API_KEY = tavilyApiKey;
    }

    // Agentic Research (Phase 2): business MCP server config and Cognito
    // verification settings. Business MCP servers receive these plus the
    // Runtime-verified AUTH_CONTEXT_JSON out-of-band; the agent never
    // supplies them through tool input.
    if (agenticResearch.knowledgeBaseId) {
      environmentVariables.KNOWLEDGE_BASE_ID = agenticResearch.knowledgeBaseId;
    }
    environmentVariables.MODEL_REGION =
      agenticResearch.knowledgeBaseRegion ?? region;
    if (agenticResearch.documentBucketName) {
      environmentVariables.AGENTIC_RESEARCH_DOCUMENT_BUCKET_NAME =
        agenticResearch.documentBucketName;
    }
    environmentVariables.AGENTIC_RESEARCH_DOCUMENT_PREFIX =
      agenticResearch.documentPrefix ?? '';
    if (agenticResearch.cognitoUserPoolId) {
      environmentVariables.AGENTIC_RESEARCH_COGNITO_USER_POOL_ID =
        agenticResearch.cognitoUserPoolId;
      environmentVariables.AGENTIC_RESEARCH_COGNITO_REGION = region;
    }
    if (agenticResearch.cognitoAppClientId) {
      environmentVariables.AGENTIC_RESEARCH_COGNITO_APP_CLIENT_ID =
        agenticResearch.cognitoAppClientId;
    }

    return new Runtime(this, 'ResearchAgentCoreRuntime', {
      runtimeName: `GenUResearchRuntime${env}`,
      agentRuntimeArtifact: AgentRuntimeArtifact.fromAsset(
        path.join(__dirname, '../../lambda-python/research-agent-core-runtime')
      ),
      executionRole: this._role,
      networkConfiguration: RuntimeNetworkConfiguration.usingPublicNetwork(),
      protocolConfiguration: ProtocolType.HTTP,
      environmentVariables,
    });
  }

  private createExecutionRole(): Role {
    const region = Stack.of(this).region;
    const accountId = Stack.of(this).account;

    return new Role(this, 'ResearchAgentCoreRuntimeRole', {
      assumedBy: new ServicePrincipal('bedrock-agentcore.amazonaws.com', {
        conditions: {
          StringEquals: { 'aws:SourceAccount': accountId },
          ArnLike: {
            'aws:SourceArn': `arn:aws:bedrock-agentcore:${region}:${accountId}:*`,
          },
        },
      }),
    });
  }

  private configureRolePermissions(
    role: Role,
    gatewayArns?: string[],
    agenticResearch?: {
      knowledgeBaseId?: string;
      knowledgeBaseRegion?: string;
      documentBucketName?: string;
      documentPrefix?: string;
    }
  ): void {
    // Bedrock permissions
    role.addToPolicy(
      new PolicyStatement({
        sid: 'BedrockModelInvocation',
        effect: Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
        ],
        resources: ['*'],
      })
    );

    // Service-linked role creation
    role.addToPolicy(
      new PolicyStatement({
        sid: 'CreateServiceLinkedRole',
        effect: Effect.ALLOW,
        actions: ['iam:CreateServiceLinkedRole'],
        resources: [
          'arn:aws:iam::*:role/aws-service-role/runtime-identity.bedrock-agentcore.amazonaws.com/AWSServiceRoleForBedrockAgentCoreRuntimeIdentity',
        ],
        conditions: {
          StringEquals: {
            'iam:AWSServiceName':
              'runtime-identity.bedrock-agentcore.amazonaws.com',
          },
        },
      })
    );

    // CodeInterpreter tools
    role.addToPolicy(
      new PolicyStatement({
        sid: 'Tools',
        effect: Effect.ALLOW,
        actions: [
          'bedrock-agentcore:CreateCodeInterpreter',
          'bedrock-agentcore:StartCodeInterpreterSession',
          'bedrock-agentcore:InvokeCodeInterpreter',
          'bedrock-agentcore:StopCodeInterpreterSession',
          'bedrock-agentcore:DeleteCodeInterpreter',
          'bedrock-agentcore:ListCodeInterpreters',
          'bedrock-agentcore:GetCodeInterpreter',
          'bedrock-agentcore:GetCodeInterpreterSession',
          'bedrock-agentcore:ListCodeInterpreterSessions',
        ],
        resources: ['*'],
      })
    );

    // Gateway tools
    role.addToPolicy(
      new PolicyStatement({
        sid: 'AllowGatewayInvocation',
        effect: Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeGateway'],
        resources: gatewayArns && gatewayArns.length > 0 ? gatewayArns : ['*'],
      })
    );

    this._fileBucket.grantWrite(role);

    // Agentic Research (Phase 2): scoped access to the governed knowledge
    // base and document bucket used by the business MCP servers.
    if (agenticResearch?.knowledgeBaseId) {
      const region = Stack.of(this).region;
      const knowledgeBaseRegion = agenticResearch.knowledgeBaseRegion ?? region;
      const accountId = Stack.of(this).account;
      role.addToPolicy(
        new PolicyStatement({
          sid: 'AgenticResearchKnowledgeBaseRetrieve',
          effect: Effect.ALLOW,
          actions: ['bedrock:Retrieve'],
          resources: [
            `arn:aws:bedrock:${knowledgeBaseRegion}:${accountId}:knowledge-base/${agenticResearch.knowledgeBaseId}`,
          ],
        })
      );
    }

    if (agenticResearch?.documentBucketName) {
      const prefix = agenticResearch.documentPrefix ?? '';
      role.addToPolicy(
        new PolicyStatement({
          sid: 'AgenticResearchDocumentBucketRead',
          effect: Effect.ALLOW,
          actions: ['s3:GetObject'],
          resources: [
            `arn:aws:s3:::${agenticResearch.documentBucketName}/${prefix}*`,
          ],
        })
      );
      role.addToPolicy(
        new PolicyStatement({
          sid: 'AgenticResearchDocumentBucketList',
          effect: Effect.ALLOW,
          actions: ['s3:ListBucket'],
          resources: [`arn:aws:s3:::${agenticResearch.documentBucketName}`],
          conditions: prefix
            ? { StringLike: { 's3:prefix': `${prefix}*` } }
            : undefined,
        })
      );
    }
  }

  private normalizeDocumentPrefix(prefix?: string): string {
    const trimmed = (prefix ?? '').replace(/^\/+/, '');
    return trimmed && !trimmed.endsWith('/') ? `${trimmed}/` : trimmed;
  }

  // Public getters
  public get deployedRuntimeArn(): string | undefined {
    return this._runtime.agentRuntimeArn;
  }

  public get fileBucket(): Bucket {
    return this._fileBucket;
  }

  public get fileBucketInfo(): BucketInfo {
    return {
      bucketName: this._fileBucket.bucketName,
      region: Stack.of(this).region,
    };
  }
}
