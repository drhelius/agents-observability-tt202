"""
Fraud Detection Workflow Orchestration with Observability

This module orchestrates three fraud detection agents using the AzureAIClient
pattern from agent_framework. Agents must be registered in Azure AI Foundry.

Workflow: CustomerDataAgent -> RiskAnalyserAgent -> FraudAlertAgent
"""

import asyncio
import os
import re
import logging
import uuid
from typing import Never, Optional
from datetime import datetime, timedelta

import dotenv
from pydantic import BaseModel

from agent_framework import (
    ChatAgent,
    ChatMessage,
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowOutputEvent,
    WorkflowStatusEvent,
    WorkflowRunState,
    handler,
)
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

# Add paths for imports
import sys, os as _os
_workflow_dir = _os.path.dirname(_os.path.abspath(__file__))
_parent_dir = _os.path.dirname(_workflow_dir)
if _workflow_dir not in sys.path:
    sys.path.insert(0, _workflow_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Import telemetry (now in same folder)
from telemetry import (
    initialize_telemetry,
    flush_telemetry,
    get_telemetry_manager,
    send_business_event,
    get_current_trace_id,
)

# Import tool implementations from existing agents (agents/ folder)
# These are needed so the agents can execute function calls locally
from agents.customer_data_agent import (
    get_customer_data,
    get_customer_transactions,
)
from agents.risk_analyser_agent import (
    analyze_transaction_risk,
)
from agents.fraud_alert_agent import (
    create_fraud_alert,
    get_fraud_alert,
)

# Load environment variables
dotenv.load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize telemetry
telemetry = get_telemetry_manager()

# Agent names as registered in the portal
CUSTOMER_DATA_AGENT_NAME = "CustomerDataAgent"
RISK_ANALYSER_AGENT_NAME = "RiskAnalyserAgent"
FRAUD_ALERT_AGENT_NAME = "FraudAlertAgent"


# ============================================================================
# Request/Response Models for Workflow
# ============================================================================

class AnalysisRequest(BaseModel):
    """Initial request to start the fraud detection workflow."""
    transaction_id: str
    customer_id: str
    amount: Optional[float] = None
    currency: Optional[str] = "USD"


class CustomerDataResponse(BaseModel):
    """Response from the CustomerDataAgent."""
    customer_id: str
    transaction_id: str
    analysis: str
    status: str
    amount: Optional[float] = None
    currency: Optional[str] = "USD"


class RiskAnalysisResponse(BaseModel):
    """Response from the RiskAnalyserAgent."""
    transaction_id: str
    customer_id: str
    risk_analysis: str
    risk_score: int
    risk_level: str
    recommendation: str
    status: str
    amount: Optional[float] = None
    currency: Optional[str] = "USD"
    model_confidence: Optional[float] = None


class FraudAlertResponse(BaseModel):
    """Response from the FraudAlertAgent."""
    transaction_id: str
    customer_id: str
    alert_response: str
    alert_created: bool
    workflow_status: str
    risk_score: int = 0
    risk_level: str = "UNKNOWN"


# ============================================================================
# Shared OpenAI Client Management
# ============================================================================

_openai_client: AsyncAzureOpenAI | None = None

def get_openai_client() -> AsyncAzureOpenAI:
    """Get or create the shared AsyncAzureOpenAI client."""
    global _openai_client
    if _openai_client is None:
        token_provider = get_bearer_token_provider(
            SyncDefaultAzureCredential(),
            "https://cognitiveservices.azure.com/.default",
        )
        _openai_client = AsyncAzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version="2024-10-21",
        )
    return _openai_client


def get_model_id() -> str:
    """Get the model deployment name from environment."""
    return os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4")


# ============================================================================
# Helper to create OpenAIChatClient
# ============================================================================

def create_chat_client() -> OpenAIChatClient:
    """Create an OpenAIChatClient using Azure OpenAI."""
    return OpenAIChatClient(
        async_client=get_openai_client(),
        model_id=get_model_id(),
    )


# ============================================================================
# Workflow Executors
# ============================================================================

class CustomerDataAgentExecutor(Executor):
    """Calls the CustomerDataAgent registered in the Foundry portal."""

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "CustomerDataAgent"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(
        self,
        request: AnalysisRequest,
        ctx: WorkflowContext[CustomerDataResponse],
    ) -> None:
        with telemetry.create_agent_span(
            "CustomerDataAgent",
            "data_retrieval",
            transaction_id=request.transaction_id,
            customer_id=request.customer_id,
        ) as span:
            span.add_event("Calling portal-hosted CustomerDataAgent")

            send_business_event("fraud_detection.customer_data.started", {
                "transaction_id": request.transaction_id,
                "customer_id": request.customer_id,
            })

            try:
                prompt = (
                    f"Analyze customer {request.customer_id} and their transactions "
                    f"comprehensively for fraud detection purposes."
                )

                start_time = asyncio.get_event_loop().time()
                response = await self.agent.run([ChatMessage(role="user", text=prompt)])
                analysis = response.messages[-1].text if response.messages else "No response"
                processing_time = asyncio.get_event_loop().time() - start_time

                span.set_attribute("ai.processing_time", processing_time)
                span.add_event("Customer data analysis completed")
                telemetry.record_transaction_processed("customer_data", request.transaction_id)

                send_business_event("fraud_detection.customer_data.completed", {
                    "transaction_id": request.transaction_id,
                    "customer_id": request.customer_id,
                    "processing_time": processing_time,
                })

                await ctx.send_message(CustomerDataResponse(
                    customer_id=request.customer_id,
                    transaction_id=request.transaction_id,
                    analysis=analysis,
                    status="SUCCESS",
                    amount=request.amount,
                    currency=request.currency,
                ))

            except Exception as e:
                span.record_exception(e)
                logger.error(f"CustomerDataAgent error: {e}")
                await ctx.send_message(CustomerDataResponse(
                    customer_id=request.customer_id,
                    transaction_id=request.transaction_id,
                    analysis=f"Error: {str(e)}",
                    status="ERROR",
                ))


class RiskAnalyserAgentExecutor(Executor):
    """Calls the RiskAnalyserAgent registered in the Foundry portal."""

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "RiskAnalyserAgent"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(
        self,
        customer_response: CustomerDataResponse,
        ctx: WorkflowContext[RiskAnalysisResponse],
    ) -> None:
        with telemetry.create_agent_span(
            "RiskAnalyserAgent",
            "risk_analysis",
            transaction_id=customer_response.transaction_id,
            customer_id=customer_response.customer_id,
        ) as span:
            span.add_event("Calling portal-hosted RiskAnalyserAgent")

            send_business_event("fraud_detection.risk_analysis.started", {
                "transaction_id": customer_response.transaction_id,
                "customer_id": customer_response.customer_id,
            })

            try:
                prompt = (
                    f"Based on this customer data analysis, perform a comprehensive "
                    f"risk assessment:\n\n{customer_response.analysis}\n\n"
                    f"Transaction ID: {customer_response.transaction_id}\n"
                    f"Customer ID: {customer_response.customer_id}\n\n"
                    f"Provide a complete risk assessment with score (0-100), level "
                    f"(LOW/MEDIUM/HIGH), and recommendation (ALLOW/INVESTIGATE/BLOCK)."
                )

                start_time = asyncio.get_event_loop().time()
                response = await self.agent.run([ChatMessage(role="user", text=prompt)])
                risk_analysis = response.messages[-1].text if response.messages else "No response"
                processing_time = asyncio.get_event_loop().time() - start_time

                span.set_attribute("ai.processing_time", processing_time)

                # Parse risk score from response - try multiple patterns (most specific first)
                risk_score = None
                patterns = [
                    r"risk\s*score[:\s]*(\d{1,3})(?:\s*/\s*100)?",  # "Risk Score: 75" or "Risk Score: 75/100"
                    r"score[:\s]*(\d{1,3})\s*/\s*100",               # "Score: 75/100"
                    r"(\d{1,3})\s*(?:out of|/)\s*100",               # "75 out of 100" or "75/100"
                    r"\*\*risk[:\s]*(\d{1,3})\*\*",                  # "**Risk: 75**"
                    r"overall\s*risk[:\s]*(\d{1,3})",                # "Overall Risk: 75"
                    r"assessment[:\s]*(\d{1,3})",                    # "Assessment: 75"
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, risk_analysis.lower())
                    if match:
                        score = int(match.group(1))
                        if 0 <= score <= 100:
                            risk_score = score
                            break
                
                # Fallback: extract risk level from text if no score found
                if risk_score is None:
                    if re.search(r"\b(high|critical|severe)\s*(risk)?", risk_analysis.lower()):
                        risk_score = 85
                    elif re.search(r"\b(medium|moderate)\s*(risk)?", risk_analysis.lower()):
                        risk_score = 55
                    elif re.search(r"\b(low|minimal)\s*(risk)?", risk_analysis.lower()):
                        risk_score = 25
                    else:
                        risk_score = 50  # Default

                risk_level = "HIGH" if risk_score >= 75 else ("MEDIUM" if risk_score >= 40 else "LOW")
                recommendation = "BLOCK" if risk_level == "HIGH" else ("INVESTIGATE" if risk_level == "MEDIUM" else "ALLOW")

                span.set_attributes({
                    "risk.score": risk_score,
                    "risk.level": risk_level,
                    "risk.recommendation": recommendation,
                })

                telemetry.record_risk_score(risk_score, customer_response.transaction_id, recommendation)

                # Model confidence
                confidence_score = abs(risk_score - 50) / 50
                telemetry.record_model_prediction(
                    transaction_id=customer_response.transaction_id,
                    model_version="v2.3.1",
                    confidence_score=confidence_score,
                    prediction=risk_level,
                    top_features=["general_risk_assessment"],
                )

                # Customer friction tracking
                if recommendation in ["BLOCK", "INVESTIGATE"]:
                    friction_type = "transaction_blocked" if recommendation == "BLOCK" else "step_up_auth"
                    telemetry.record_customer_friction(
                        customer_id=customer_response.customer_id,
                        transaction_id=customer_response.transaction_id,
                        friction_type=friction_type,
                        transaction_declined=(recommendation == "BLOCK"),
                    )

                send_business_event("fraud_detection.risk_analysis.completed", {
                    "transaction_id": customer_response.transaction_id,
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "recommendation": recommendation,
                })

                await ctx.send_message(RiskAnalysisResponse(
                    transaction_id=customer_response.transaction_id,
                    customer_id=customer_response.customer_id,
                    risk_analysis=risk_analysis,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    recommendation=recommendation,
                    status="SUCCESS",
                    amount=customer_response.amount,
                    currency=customer_response.currency,
                    model_confidence=confidence_score,
                ))

            except Exception as e:
                span.record_exception(e)
                logger.error(f"RiskAnalyserAgent error: {e}")
                await ctx.send_message(RiskAnalysisResponse(
                    transaction_id=customer_response.transaction_id,
                    customer_id=customer_response.customer_id,
                    risk_analysis=f"Error: {str(e)}",
                    risk_score=0,
                    risk_level="UNKNOWN",
                    recommendation="INVESTIGATE",
                    status="ERROR",
                ))


class FraudAlertAgentExecutor(Executor):
    """Calls the FraudAlertAgent registered in the Foundry portal."""

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "FraudAlertAgent"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(
        self,
        risk_response: RiskAnalysisResponse,
        ctx: WorkflowContext[Never, FraudAlertResponse],
    ) -> None:
        with telemetry.create_agent_span(
            "FraudAlertAgent",
            "alert_creation",
            transaction_id=risk_response.transaction_id,
            customer_id=risk_response.customer_id,
        ) as span:
            span.add_event("Calling portal-hosted FraudAlertAgent")

            send_business_event("fraud_detection.fraud_alert.started", {
                "transaction_id": risk_response.transaction_id,
                "risk_score": risk_response.risk_score,
                "risk_level": risk_response.risk_level,
            })

            try:
                severity = "CRITICAL" if risk_response.risk_score >= 90 else \
                          ("HIGH" if risk_response.risk_score >= 75 else \
                          ("MEDIUM" if risk_response.risk_score >= 50 else "LOW"))

                prompt = (
                    f"Based on this risk analysis, determine if a fraud alert should "
                    f"be created:\n\n"
                    f"Risk Analysis:\n{risk_response.risk_analysis}\n\n"
                    f"Transaction ID: {risk_response.transaction_id}\n"
                    f"Customer ID: {risk_response.customer_id}\n"
                    f"Risk Score: {risk_response.risk_score}/100\n"
                    f"Risk Level: {risk_response.risk_level}\n"
                    f"Recommendation: {risk_response.recommendation}\n"
                    f"Severity: {severity}\n\n"
                    f"If risk score >= 40, create a fraud alert. Otherwise explain "
                    f"why no alert is needed."
                )

                start_time = asyncio.get_event_loop().time()
                response = await self.agent.run([ChatMessage(role="user", text=prompt)])
                alert_response = response.messages[-1].text if response.messages else "No response"
                processing_time = asyncio.get_event_loop().time() - start_time

                span.set_attribute("ai.processing_time", processing_time)

                alert_created = "alert created" in alert_response.lower() or risk_response.risk_score >= 40

                if alert_created:
                    telemetry.record_fraud_alert_created(
                        f"ALERT-{risk_response.transaction_id}",
                        severity,
                        risk_response.recommendation,
                        risk_response.transaction_id,
                    )
                    
                    if risk_response.recommendation == "BLOCK" and risk_response.amount:
                        telemetry.record_fraud_prevented(
                            transaction_id=risk_response.transaction_id,
                            blocked_amount=risk_response.amount,
                            currency=risk_response.currency or "USD",
                            fraud_type="general_fraud",
                            risk_score=risk_response.risk_score,
                        )
                    
                    # SAR filing for high-risk transactions
                    amount_threshold = (risk_response.amount or 0) >= 10000
                    if severity in ["CRITICAL", "HIGH"] or amount_threshold:
                        sar_id = f"SAR-{datetime.now().strftime('%Y')}-{uuid.uuid4().hex[:8].upper()}"
                        filing_deadline = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                        telemetry.record_sar_filed(
                            transaction_id=risk_response.transaction_id,
                            sar_id=sar_id,
                            filing_deadline=filing_deadline,
                            amount_threshold_exceeded=amount_threshold,
                            customer_id=risk_response.customer_id,
                        )

                span.set_attributes({
                    "alert.created": alert_created,
                    "alert.severity": severity if alert_created else "NONE",
                })

                send_business_event("fraud_detection.fraud_alert.completed", {
                    "transaction_id": risk_response.transaction_id,
                    "alert_created": alert_created,
                    "severity": severity if alert_created else "NONE",
                })

                await ctx.yield_output(FraudAlertResponse(
                    transaction_id=risk_response.transaction_id,
                    customer_id=risk_response.customer_id,
                    alert_response=alert_response,
                    alert_created=alert_created,
                    workflow_status="SUCCESS",
                    risk_score=risk_response.risk_score,
                    risk_level=risk_response.risk_level,
                ))

            except Exception as e:
                span.record_exception(e)
                logger.error(f"FraudAlertAgent error: {e}")
                await ctx.yield_output(FraudAlertResponse(
                    transaction_id=risk_response.transaction_id,
                    customer_id=risk_response.customer_id,
                    alert_response=f"Error: {str(e)}",
                    alert_created=False,
                    workflow_status="ERROR",
                    risk_score=risk_response.risk_score,
                    risk_level=risk_response.risk_level,
                ))


# ============================================================================
# Standalone Workflow Runner (for batch processing)
# ============================================================================

async def run_fraud_detection_workflow(
    transaction_id: str,
    customer_id: str,
    amount: Optional[float] = None,
    currency: Optional[str] = "USD",
) -> FraudAlertResponse:
    """
    Execute a single fraud detection workflow.
    
    This function is used by the batch runner for processing multiple transactions.
    
    Args:
        transaction_id: The transaction ID to analyze
        customer_id: The customer ID
        amount: Transaction amount
        currency: Currency code
        
    Returns:
        FraudAlertResponse with the workflow result
    """
    # Ensure telemetry is initialized (handles cross-module singleton issue)
    if not telemetry._initialized:
        telemetry.initialize_observability()
    
    chat_client = create_chat_client()
    
    # Create ChatAgent instances with tools
    customer_data_agent = ChatAgent(
        name="CustomerDataAgent",
        description="Retrieves customer data from Cosmos DB",
        chat_client=chat_client,
        tools=[get_customer_data, get_customer_transactions],
        instructions="""You are a Data Ingestion Agent responsible for preparing structured input for fraud detection.
You will receive raw transaction records and customer profiles. Your task is to:
- Normalize fields (e.g., currency, timestamps, amounts)
- Remove or flag incomplete data
- Enrich each transaction with relevant customer metadata (e.g., account age, country, device info)
- Output a clean JSON object per transaction with unified structure
Use the available functions to fetch customer data and transactions.""",
    )
    
    risk_analyser_agent = ChatAgent(
        name="RiskAnalyserAgent",
        description="Analyzes transaction risk",
        chat_client=create_chat_client(),
        tools=[analyze_transaction_risk],
        instructions="""You are a Risk Analysis Agent. Evaluate transactions for fraud risk using regulations and policies.
Provide a risk score (0-100), risk level (LOW/MEDIUM/HIGH), and recommendation (ALLOW/INVESTIGATE/BLOCK).
Use the available functions to search regulations and analyze risk.""",
    )
    
    fraud_alert_agent = ChatAgent(
        name="FraudAlertAgent",
        description="Creates fraud alerts",
        chat_client=create_chat_client(),
        tools=[create_fraud_alert, get_fraud_alert],
        instructions="""You are a Fraud Alert Agent. Based on risk analysis results, determine if a fraud alert should be created.
If risk score >= 40, create a fraud alert. Otherwise explain why no alert is needed.
Use the available functions to create and manage fraud alerts.""",
    )
    
    # Build workflow
    workflow = (
        WorkflowBuilder()
        .register_executor(lambda: CustomerDataAgentExecutor(customer_data_agent), name="CustomerDataAgent")
        .register_executor(lambda: RiskAnalyserAgentExecutor(risk_analyser_agent), name="RiskAnalyserAgent")
        .register_executor(lambda: FraudAlertAgentExecutor(fraud_alert_agent), name="FraudAlertAgent")
        .add_edge("CustomerDataAgent", "RiskAnalyserAgent")
        .add_edge("RiskAnalyserAgent", "FraudAlertAgent")
        .set_start_executor("CustomerDataAgent")
        .build()
    )
    
    request = AnalysisRequest(
        transaction_id=transaction_id,
        customer_id=customer_id,
        amount=amount,
        currency=currency,
    )
    
    final_result = None
    async for event in workflow.run_stream(request):
        if isinstance(event, WorkflowOutputEvent):
            final_result = event.data
    
    return final_result


# ============================================================================
# Main
# ============================================================================

async def main():
    """Run the fraud detection workflow."""
    
    # Initialize observability
    initialize_telemetry()
    
    if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is required")

    # Create OpenAI chat clients for the three agents
    print("Creating agent chat clients...")
    customer_data_client = create_chat_client()
    risk_analyser_client = create_chat_client()
    fraud_alert_client = create_chat_client()
    print("✓ All agents ready\n")

    # Create ChatAgent instances with tools registered for local execution
    customer_data_agent = ChatAgent(
        name="CustomerDataAgent",
        description="Retrieves customer data from Cosmos DB",
        chat_client=customer_data_client,
        tools=[get_customer_data, get_customer_transactions],
        instructions="""You are a Data Ingestion Agent responsible for preparing structured input for fraud detection.
You will receive raw transaction records and customer profiles. Your task is to:
- Normalize fields (e.g., currency, timestamps, amounts)
- Remove or flag incomplete data
- Enrich each transaction with relevant customer metadata (e.g., account age, country, device info)
- Output a clean JSON object per transaction with unified structure
Use the available functions to fetch customer data and transactions.""",
    )

    risk_analyser_agent = ChatAgent(
        name="RiskAnalyserAgent",
        description="Analyzes transaction risk",
        chat_client=risk_analyser_client,
        tools=[analyze_transaction_risk],
        instructions="""You are a Risk Analysis Agent. Evaluate transactions for fraud risk using regulations and policies.
Provide a risk score (0-100), risk level (LOW/MEDIUM/HIGH), and recommendation (ALLOW/INVESTIGATE/BLOCK).
Use the available functions to search regulations and analyze risk.""",
    )

    fraud_alert_agent = ChatAgent(
        name="FraudAlertAgent",
        description="Creates fraud alerts",
        chat_client=fraud_alert_client,
        tools=[create_fraud_alert, get_fraud_alert],
        instructions="""You are a Fraud Alert Agent. Based on risk analysis results, determine if a fraud alert should be created.
If risk score >= 40, create a fraud alert. Otherwise explain why no alert is needed.
Use the available functions to create and manage fraud alerts.""",
    )

    # Build the workflow
    workflow = (
        WorkflowBuilder()
        .register_executor(lambda: CustomerDataAgentExecutor(customer_data_agent), name="CustomerDataAgent")
        .register_executor(lambda: RiskAnalyserAgentExecutor(risk_analyser_agent), name="RiskAnalyserAgent")
        .register_executor(lambda: FraudAlertAgentExecutor(fraud_alert_agent), name="FraudAlertAgent")
        .add_edge("CustomerDataAgent", "RiskAnalyserAgent")
        .add_edge("RiskAnalyserAgent", "FraudAlertAgent")
        .set_start_executor("CustomerDataAgent")
        .build()
    )

    with telemetry.create_workflow_span("fraud_detection_application") as main_span:
        trace_id = get_current_trace_id()
        print(f"\n🔍 Fraud Detection Workflow")
        print(f"📊 Trace ID: {trace_id}")
        print("=" * 70)

        # Test transactions
        test_cases = [
            ("TX1001", "CUST1001", 5200.00, "USD"),
            ("TX1005", "CUST1005", 15000.00, "USD"),
        ]

        for transaction_id, customer_id, amount, currency in test_cases:
            print(f"\n{'='*70}")
            print(f"Processing: Transaction {transaction_id}, Customer {customer_id}")
            print(f"Amount: {amount} {currency}")
            print(f"{'='*70}")

            request = AnalysisRequest(
                transaction_id=transaction_id,
                customer_id=customer_id,
                amount=amount,
                currency=currency,
            )

            final_result = None
            async for event in workflow.run_stream(request):
                if isinstance(event, WorkflowStatusEvent):
                    if event.state == WorkflowRunState.IDLE:
                        print("✓ Workflow completed")
                elif isinstance(event, WorkflowOutputEvent):
                    final_result = event.data

            if final_result:
                print(f"\n📋 WORKFLOW RESULT:")
                print(f"   Transaction: {final_result.transaction_id}")
                print(f"   Customer: {final_result.customer_id}")
                print(f"   Alert Created: {'✅ YES' if final_result.alert_created else '❌ NO'}")
                print(f"   Status: {final_result.workflow_status}")
                print(f"\n   Agent Response:")
                print(f"   {final_result.alert_response[:500]}...")

        print(f"\n{'='*70}")
        print(f"🔍 Trace completed: {trace_id}")

    await asyncio.sleep(1.0)
    
    # Flush telemetry to ensure all data is sent to Application Insights
    flush_telemetry()


if __name__ == "__main__":
    asyncio.run(main())
