# Copyright (c) Microsoft. All rights reserved.

import asyncio
import os
from typing import Never

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
from agent_framework.azure import AzureAIClient
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import DefaultAzureCredential

"""
Sample: Sequential workflow with Foundry agents using Executors

Sequential Workflow: ResearcherAgentV2 -> WriterAgentV2 -> ReviewerAgentV2

This workflow orchestrates three Azure agents in sequence:
1. ResearcherAgentV2: Processes the initial user message using web search
2. WriterAgentV2: Takes the researcher's output and generates content
3. ReviewerAgentV2: Reviews and finalizes the content

Prerequisites:
- AZURE_AI_PROJECT_ENDPOINT environment variable configured
- Agents (ResearcherAgentV2, WriterAgentV2, ReviewerAgentV2) created in Foundry
"""


async def create_chat_client_for_agent(
    project_client: AIProjectClient,
    agent_name: str
) -> AzureAIClient:
    """Create an AzureAIClient for a Foundry agent.

    Args:
        project_client: The AIProjectClient instance
        agent_name: The name of the agent in Foundry

    Returns:
        Configured AzureAIClient for the agent
    """

    return AzureAIClient(
        project_client=project_client,
        agent_name=agent_name,
        use_latest_version=True,
    )


class ResearcherAgentV2Executor(Executor):
    """
    First agent in the sequential workflow.
    Processes the initial user message and passes results to the next agent.
    """

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "ResearcherAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, message: ChatMessage | list[ChatMessage], ctx: WorkflowContext[list[ChatMessage]]) -> None:
        """
        Handle the initial message and forward the conversation to WriterAgentV2.

        Args:
            message: The initial user message
            ctx: Workflow context for sending messages to downstream agents
        """
        if isinstance(message, list):
            messages = message
        else:
            messages = [message]

        response = await self.agent.run(messages)

        print(f"\nResearcherAgentV2 output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class WriterAgentV2Executor(Executor):
    """
    Second agent in the sequential workflow.
    Receives output from ResearcherAgentV2 and generates content.
    """

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "WriterAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, messages: list[ChatMessage], ctx: WorkflowContext[list[ChatMessage]]) -> None:
        """
        Process the researcher's output and forward to ReviewerAgentV2.

        Args:
            message: Message or conversation history from ResearcherAgentV2
            ctx: Workflow context for sending messages to downstream agents
        """

        response = await self.agent.run(messages)

        print(f"\nWriterAgentV2 output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        messages.extend(response.messages)
        await ctx.send_message(messages)


class ReviewerAgentV2Executor(Executor):
    """
    Third and final agent in the sequential workflow.
    Reviews the content and yields the final output.
    """

    agent: ChatAgent

    def __init__(self, agent: ChatAgent, id: str = "ReviewerAgentV2"):
        self.agent = agent
        super().__init__(id=id)

    @handler
    async def handle(self, messages: list[ChatMessage], ctx: WorkflowContext[Never, list[ChatMessage]]) -> None:
        """
        Review the final content and yield the workflow output.

        Args:
            message: Message or full conversation history from previous agents
            ctx: Workflow context for yielding final output
        """
        response = await self.agent.run(messages)

        print(f"\nReviewerAgentV2 output:")
        print(f"{response.messages[-1].text[:500]}..." if len(
            response.messages[-1].text) > 500 else response.messages[-1].text)

        # Yield the final conversation
        messages.extend(response.messages)
        await ctx.yield_output(messages)


async def main() -> None:
    """
    Build and run the sequential workflow using agents from Microsoft Foundry.
    """
    # Verify environment variables
    if not os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")

    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=credential
        ) as project_client:

            # Create chat clients for the three Foundry agents
            print("Loading agents from Microsoft Foundry...")
            researcher_client = await create_chat_client_for_agent(project_client, "ResearcherAgentV2")
            writer_client = await create_chat_client_for_agent(project_client, "WriterAgentV2")
            reviewer_client = await create_chat_client_for_agent(project_client, "ReviewerAgentV2")
            print("✓ All agents loaded successfully\n")

            # Create agents using the Foundry clients
            researcher = ChatAgent(
                name="Researcher",
                description="Collects relevant information using web search",
                chat_client=researcher_client,
            )

            writer = ChatAgent(
                name="Writer",
                description="Creates well-structured content based on research",
                chat_client=writer_client,
            )

            reviewer = ChatAgent(
                name="Reviewer",
                description="Evaluates content quality and provides constructive feedback",
                chat_client=reviewer_client,
            )

            # Build the workflow using the executor pattern
            # This mirrors the sequential structure: Researcher -> Writer -> Reviewer
            workflow = (
                WorkflowBuilder()
                # Register executors with lazy instantiation
                .register_executor(lambda: ResearcherAgentV2Executor(researcher), name="ResearcherAgentV2")
                .register_executor(lambda: WriterAgentV2Executor(writer), name="WriterAgentV2")
                .register_executor(lambda: ReviewerAgentV2Executor(reviewer), name="ReviewerAgentV2")
                # Define the sequential flow: Researcher -> Writer -> Reviewer
                .add_edge("ResearcherAgentV2", "WriterAgentV2")
                .add_edge("WriterAgentV2", "ReviewerAgentV2")
                # Set the entry point
                .set_start_executor("ResearcherAgentV2")
                .build()
            )

            task = "Research and write a comprehensive article about the impact of AI agents in software development. Include recent trends and real-world examples."

            # Run the workflow with streaming to observe events as they occur
            print("=" * 80)
            print(
                "Starting sequential workflow: ResearcherAgentV2 -> WriterAgentV2 -> ReviewerAgentV2")
            print("=" * 80)
            print(f"\nTASK: {task}\n")

            async for event in workflow.run_stream(
                ChatMessage(role="user", text=task)
            ):
                if isinstance(event, WorkflowStatusEvent):
                    if event.state == WorkflowRunState.IDLE:
                        print("\n" + "=" * 80)
                        print("✓ Workflow completed successfully")
                        print("=" * 80)
                elif isinstance(event, WorkflowOutputEvent):
                    print("\n" + "=" * 80)
                    print("FINAL CONVERSATION")
                    print("=" * 80)
                    messages = event.data
                    for i, msg in enumerate(messages, start=1):
                        name = msg.author_name or (
                            "assistant" if msg.role.value == "assistant" else "user")
                        print(f"\n{'-' * 80}\n{i:02d} [{name}]")
                        print(msg.text)

            # Allow time for async cleanup
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
