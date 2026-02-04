# From Zero to Hero: Building Agents with Microsoft Foundry and Agent Framework

## Create agents in Foundry

### Requirements

#### Login to Azure

```bash
az login
```

#### Environment setup

```bash
export RG=<your-resource-group>
export LOCATION=<your-location> # one that supports hosted agents, e.g., northcentralus
export AGENTS_HOME=from-zero-to-hero
```

Move to `AGENTS_HOME`:
```bash
cd $AGENTS_HOME
```

#### Install resources

Before deploying the infra resources, check the file `infra/basic-setup.parameters.json` to set the location and resource names you want.

```bash
az group create --name $RG --location $LOCATION
# deployment with file parameters
az deployment group create --resource-group $RG --template-file infra/basic-setup.bicep --parameters @infra/basic-setup.parameters.json
```

Update env variables with outputs from deployment

```bash
# get vars from deployment output
export FOUNDRY_RESOURCE_NAME=$(az deployment group show --resource-group $RG --name basic-setup --query properties.outputs.accountName.value -o tsv)
export FOUNDRY_PROJECT_NAME=$(az deployment group show --resource-group $RG --name basic-setup --query properties.outputs.projectName.value -o tsv) 
export AZURE_AI_PROJECT_ENDPOINT="https://$FOUNDRY_RESOURCE_NAME.services.ai.azure.com/api/projects/$FOUNDRY_PROJECT_NAME"
export AZURE_AI_MODEL_DEPLOYMENT_NAME="gpt-4.1"  # or your deployment name
```

From portal:

- Create a `Grounding with bing` resource and connect to the Microsoft Foundry project (https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/bing-tools?view=foundry&tabs=grounding-with-bing&pivots=python#prerequisites)

![alt text](images/bingconnectofoundry.png)

Export variable:

```bash
export BING_CONNECTION_NAME=<your-bing-connection-name> 
export SUBSCRIPTION_ID=$(az account show --query id -o tsv)
export BING_PROJECT_CONNECTION_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/$FOUNDRY_RESOURCE_NAME/projects/$FOUNDRY_PROJECT_NAME/connections/$BING_CONNECTION_NAME"
```


### Create venv and install the Agent Framework packages

As of Feb 4, 2026, I will create two venvs:
- venv260130 for latest MAF packages (260130)
- venv260107 for previous MAF packages (260107) and compatible with azure-ai-agentserver-agentframework 1.0.0b10

```bash
python3 -m venv venv260130
source venv260130/bin/activate
pip install -r requirements-260130.txt
pip list
deactivate
python3 -m venv venv260107
source venv260107/bin/activate
pip install -r requirements-260107.txt
pip list
deactivate
```

### Create agents

Activate latest venv:

```bash
source venv260130/bin/activate
```

**Using Foundry SDK**

```bash
python agents-standalone/foundry/create_research_agent.py
python agents-standalone/foundry/create_writer_agent.py
python agents-standalone/foundry/create_reviewer_agent.py
```

**Using Microsoft Agent Framework**

```bash
python agents-standalone/maf/create_research_agent.py
python agents-standalone/maf/create_writer_agent.py
python agents-standalone/maf/create_reviewer_agent.py
```

### Publish the agent

Use publish in Foundry portal. 

You get a set of endpoints for the Researcher agent (responses api and activity protocol):

### Test the agent

Use the responses endpoint to test the agent:

```bash
export AGENT_NAME=ResearcherAgentV2
python agents-client/agent_client.py "What are the latest AI trends?"
```

## Create workflow

Test the sequential agents workflow

```bash
python orchestration/sequential_agents.py
```

Test the group chat agent workflow

```bash
python orchestration/group_chat_agent_manager.py
```

## Build as Agent and trace the workflow locally

As per today (Feb 4, 2026), we have to use the previous venv (260107) to build the orchestration as an agent.

Activate the previous venv:

```bash
deactivate
source venv260107/bin/activate
```

Use AI Toolkit to generate tracing configuration over a copy of the orchestration/group_chat_agent_manager.py file in  orchestration/tracing/group_chat_agent_manager.py.

Open the Microsoft Foundry extension and start the Local Agent Playground.



## Deploy as hosted agent

First, install required packages.

```bash
pip install azure-ai-agentserver-agentframework
```

Run locally:

```bash
python orchestration/hosted/sequential_agents_as_agent.py
```

Test it using the Local Agent Playground from the Microsoft Foundry extension. Notice no traces yet.


Alternative, test it:

```bash
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Report about the latest AI trends."
}'
```

Use the Microsoft Foundry extension to deploy a hosted agent. 

### Give permission to the Foundry Managed Identity

Use the portal to give "Azure AI User" role to the Foundry Project Managed Identity.

### Publish and test

Publish the hosted agents in Foundry portal.

Test the Group Chat hosted agent:

```bash
export AGENT_NAME=researchgrchatwf
python agents-client/agent_client.py "Write a short article about the latest AI trends."
```

## Observability

### Configure Application Insights

Setup an Application Insights resource connected to the Foundry project.

Make it in the Foundry portal: Operate/Admin/<choose project>/Connected Resources/Application Insights

Run some tests:

```bash
export AGENT_NAME=researchgrchatwf
python agents-client/agent_client.py "What are the latest AI trends?"
```

REVIEW THIS: 

See that data is flowing into Application Insights without any code changes. 
See Traces & Monitor in Foundry portal.
See Application Insights in Azure portal/Agents. (Note: I only see traces in "search". Tables are empty, only  dependency table has some data).

### Add observability using AI Toolkit

Use Ai Toolkit to generate tracing configuration over a copy of the orchestration/hosted/group_chat_agent_manager_as_agent.py file (see result in orchestration/tracing/group_chat_agent_manager_as_agent.py).

IMPORTANT: start the Local Agent Playground in the Microsoft Foundry extension first.

Then change port 4319 and execute:

```bash
python orchestration/tracing/group_chat_agent_manager_as_agent.py
```

Test it using the Local Agent Playground from the Microsoft Foundry extension:

![alt text](images/localtraces.png)

### Deploy new version of the traced hosted agent

Use the Microsoft Foundry extension to deploy the traced version of the group chat hosted agent (orchestration/tracing/group_chat_agent_manager_as_agent.py).

Then, pubslish and test again:

```bash
export AGENT_NAME=researchgrchatwf
python agents-client/agent_client.py "Write a short article about the latest AI trends."
```


