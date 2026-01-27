# Copyright (c) Microsoft. All rights reserved.

"""
Reviewer Agent - Standalone Foundry Agent

Creates a content reviewer and editor agent in Azure AI Foundry. 
This agent specializes in evaluating content quality and providing constructive feedback.
"""

import asyncio
import os

from agent_framework.azure import AzureAIProjectAgentProvider
from azure.identity.aio import DefaultAzureCredential


async def create_reviewer_agent():
    """Create a reviewer agent in Azure AI Foundry. 

    Returns:
        A configured agent for reviewing content (created in Foundry)
    """
    print("="*60)
    print("CREATING REVIEWER AGENT IN AZURE AI FOUNDRY")
    print("="*60)

    # Verify environment variables
    if not os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")

    async with (
        DefaultAzureCredential() as credential,
        AzureAIProjectAgentProvider(credential=credential) as provider,
    ):
        print("\nCreating Reviewer Agent...")

        agent = await provider.create_agent(
            name="ReviewerAgentV2",
            instructions="""You are a meticulous content reviewer and editor.
                Your role is to evaluate content for quality and provide constructive feedback.

                Evaluate content based on:
                1. Clarity and Coherence
                - Is the message clear and easy to understand?
                - Do ideas flow logically from one to another?
                - Are there any confusing or ambiguous statements?

                2. Factual Accuracy
                - Are claims supported by evidence?
                - Are there any factual errors?
                - Are sources cited appropriately?

                3. Grammar and Style
                - Are there spelling or grammar errors?
                - Is the tone appropriate for the audience?
                - Is the writing style consistent?

                4. Overall Quality and Completeness
                - Does the content meet its stated purpose?
                - Are there gaps in information?
                - Is the structure effective?

                Provide feedback that:
                - Starts with positive observations (what works well)
                - Identifies specific areas for improvement
                - Offers concrete suggestions for enhancement
                - Maintains a constructive and supportive tone
                - Prioritizes the most important issues

                Structure your review with clear sections and be thorough but fair.""",
        )

        print(f"✓ Reviewer Agent created successfully!")
        print(f"  Agent ID: {agent.id}")
        print(f"  Agent Name: ReviewerAgentV2")

        return agent


async def main() -> None:
    """Main function to create and test the reviewer agent."""
    try:
        # Create the agent
        agent = await create_reviewer_agent()

        print("\n" + "="*60)
        print("REVIEWER AGENT SETUP COMPLETE")
        print("="*60)
        print("\nThe agent is now available in Azure AI Foundry.")
        print("You can use it from any application by referencing:")
        print(f"  Agent Name: ReviewerAgentV2")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    asyncio. run(main())
