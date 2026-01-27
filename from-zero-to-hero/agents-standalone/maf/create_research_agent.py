# Copyright (c) Microsoft. All rights reserved.

"""
Researcher Agent - Standalone Foundry Agent with Bing Grounding

Creates a research analyst agent in Microsoft Foundry with Bing search capabilities.
This agent can search the web for current information and provide comprehensive research. 
"""

import asyncio
import os

from agent_framework.azure import AzureAIProjectAgentProvider
from azure.identity.aio import DefaultAzureCredential


async def create_researcher_agent():
    """Create a researcher agent with Bing search in Microsoft Foundry.

    Returns:
        A configured agent for research tasks with web search capabilities
    """
    print("="*60)
    print("CREATING RESEARCHER AGENT IN MICROSOFT FOUNDRY")
    print("With Bing Grounding Search")
    print("="*60)

    # Verify environment variables
    if not os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required")
    if not os.environ.get("BING_PROJECT_CONNECTION_ID"):
        raise ValueError(
            "BING_PROJECT_CONNECTION_ID environment variable is required")

    async with (
        DefaultAzureCredential() as credential,
        AzureAIProjectAgentProvider(credential=credential) as provider,
    ):
        print("\nCreating Researcher Agent...")
        
        agent = await provider.create_agent(
            name="ResearcherAgentV2",
            instructions="""You are a thorough research analyst with access to web search.
                Your role is to gather, analyze, and synthesize information on given topics.

                When researching:
                - ALWAYS use the Bing Grounding Search tool to find current, accurate information
                - Gather information from multiple sources when possible
                - Provide comprehensive findings with factual details
                - Structure your research with clear sections and bullet points
                - Always cite sources and provide context
                - Distinguish between facts and interpretations
                - Note the recency and reliability of information

                Your research should be:
                - Well-organized with clear headings
                - Factual and evidence-based
                - Comprehensive yet concise
                - Properly sourced with citations""",
            tools={
                "type": "bing_grounding",
                "bing_grounding": {
                    "search_configurations": [
                        {
                            "project_connection_id": os.environ["BING_PROJECT_CONNECTION_ID"],
                        }
                    ]
                },
            },
        )

        print(f"✓ Researcher Agent created successfully!")
        print(f"  Agent ID: {agent.id}")
        print(f"  Agent Name: ResearcherAgentV2")
        print(f"  Web Search: Enabled (Bing Grounding)")

        return agent


async def main() -> None:
    """Main function to create and test the researcher agent."""
    try:
        # Create the agent
        agent = await create_researcher_agent()

        print("\n" + "="*60)
        print("RESEARCHER AGENT SETUP COMPLETE")
        print("="*60)
        print("\nThe agent is now available in Microsoft Foundry.")
        print("You can use it from any application by referencing:")
        print(f"  Agent Name: ResearcherAgentV2")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())