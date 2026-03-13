"""
EmTech "Monitoring the Situation" Dashboard — FastAPI backend.

Serves a static single-page dashboard and exposes REST endpoints that
query the Neo4j knowledge graph for EmTech trends, milestones, bets,
and AI-analyzed X/web news.

Run:
    cd /home/sic/dev/oomai
    python -m uvicorn dashboard.server:app --reload --port 8050
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from neo4j import AsyncGraphDatabase
from neo4j.time import Date, DateTime
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from xai_sdk import AsyncClient as XAIAsyncClient
from xai_sdk.chat import system as xai_system, user as xai_user, tool_result as xai_tool_result

# Core function tools (no Chainlit dependency)
from function_tools.core_graph_ops import (
    GraphOpsCtx,
    core_execute_cypher_query,
    core_find_node,
    core_scan_ideas,
    core_scan_trends,
    core_dfs,
)
from function_tools.core_x_search import core_x_search
from function_tools.tool_def import TOOLS_DEFINITIONS

load_dotenv()

logger = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
XAI_API_KEY = os.getenv("XAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
USER_PARTY_NAME = os.getenv("USER_PARTY_NAME", "User")

# ---------------------------------------------------------------------------
# System prompts for chat (read-only two-step pipeline)
# ---------------------------------------------------------------------------
_project_root = Path(__file__).parent.parent

with open(_project_root / "knowledge_graph" / "schema.md", "r") as _f:
    _SCHEMA = _f.read()
with open(_project_root / "knowledge_graph" / "system_prompt_readonly_step1.md", "r") as _f:
    CHAT_SYSTEM_PROMPT_STEP1 = _f.read().format(schema=_SCHEMA, user_party_name=USER_PARTY_NAME)
with open(_project_root / "knowledge_graph" / "system_prompt_dashboard_step2.md", "r") as _f:
    CHAT_SYSTEM_PROMPT_STEP2 = _f.read().format(schema=_SCHEMA, user_party_name=USER_PARTY_NAME)

# Read-only tools for the chat (same as Chainlit read-only mode)
CHAT_TOOLS = [
    TOOLS_DEFINITIONS["execute_cypher_query"],
    TOOLS_DEFINITIONS["find_node"],
    TOOLS_DEFINITIONS["scan_ideas"],
    TOOLS_DEFINITIONS["scan_trends"],
    TOOLS_DEFINITIONS["dfs"],
    TOOLS_DEFINITIONS["x_search"],
]

CHAT_FUNCTION_MAP = {
    "execute_cypher_query": core_execute_cypher_query,
    "find_node": core_find_node,
    "scan_ideas": core_scan_ideas,
    "scan_trends": core_scan_trends,
    "dfs": core_dfs,
    "x_search": core_x_search,
}

FUNCTIONS_WITH_CTX = [
    "execute_cypher_query", "find_node", "scan_ideas", "scan_trends", "dfs",
]

FUNCTIONS_WITH_OPENAI = [
    "find_node", "scan_ideas", "scan_trends",
]

FUNCTIONS_WITH_XAI_CLIENT = [
    "x_search",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def neo4j_to_json(obj):
    """Recursively convert Neo4j types to JSON-serializable Python objects."""
    if isinstance(obj, (Date, DateTime)):
        return obj.iso_format()
    if isinstance(obj, dict):
        return {k: neo4j_to_json(v) for k, v in obj.items() if k != "embedding" and v is not None}
    if isinstance(obj, list):
        return [neo4j_to_json(i) for i in obj]
    return obj

# ---------------------------------------------------------------------------
# Lifespan – Neo4j driver
# ---------------------------------------------------------------------------

driver = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global driver
    driver = AsyncGraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        max_connection_lifetime=120, max_connection_pool_size=5,
    )
    await driver.verify_connectivity()
    logger.info("✅ Neo4j connected")
    yield
    await driver.close()
    logger.info("Neo4j closed")

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse as _FileResponse

app = FastAPI(title="EmTech Situation Dashboard", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Static page — serve React build from frontend/dist/ (fallback: index.html)
# ---------------------------------------------------------------------------

_dashboard_dir = Path(__file__).parent
_react_dist = _dashboard_dir / "frontend" / "dist"

# Mount built assets if they exist
if (_react_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_react_dist / "assets")), name="static-assets")

@app.get("/", response_class=HTMLResponse)
async def root():
    react_index = _react_dist / "index.html"
    if react_index.is_file():
        return react_index.read_text()
    # Fallback to original monolithic dashboard
    return (_dashboard_dir / "index.html").read_text()

# ---------------------------------------------------------------------------
# API: list top-level EmTechs
# ---------------------------------------------------------------------------

TOP_EMTECHS = [
    "artificial intelligence", "robots", "computing", "energy",
    "crypto-currency", "networks", "transportation", "3D printing",
    "internet of things", "virtual reality", "synthetic biology",
]

EMTECH_ICONS = {
    "artificial intelligence": "🧠",
    "robots": "🤖",
    "computing": "💻",
    "energy": "⚡",
    "crypto-currency": "₿",
    "networks": "🌐",
    "transportation": "🚀",
    "3D printing": "🖨️",
    "internet of things": "📡",
    "virtual reality": "🕶️",
    "synthetic biology": "🧬",
}

@app.get("/api/emtechs")
async def list_emtechs():
    query = """
    UNWIND $names AS n
    MATCH (e:EmTech {name: n})
    OPTIONAL MATCH (e)-[:ENABLES]->(c:Capability)
    WITH e, count(DISTINCT c) AS cap_count
    OPTIONAL MATCH (e)-[:ENABLES]->(:Capability)-[:HAS_MILESTONE]->(m:Milestone)
    RETURN e.name AS name, e.description AS description,
           cap_count, count(DISTINCT m) AS milestone_count
    ORDER BY cap_count DESC
    """
    async with driver.session() as session:
        result = await session.run(query, {"names": TOP_EMTECHS})
        data = await result.data()
    out = []
    for r in neo4j_to_json(data):
        r["icon"] = EMTECH_ICONS.get(r["name"], "🔬")
        out.append(r)
    return out

# ---------------------------------------------------------------------------
# API: trends for an EmTech
# ---------------------------------------------------------------------------

@app.get("/api/emtech/{name}/trends")
async def emtech_trends(name: str):
    query = """
    MATCH (e:EmTech {name: $name})-[:ENABLES]->(c:Capability)<-[:PREDICTS]-(t:Trend)
    OPTIONAL MATCH (p:Party)-[r]-(t)
    RETURN DISTINCT t.name AS name, t.description AS description,
           t.observed_date AS observed_date,
           c.name AS capability,
           collect(DISTINCT p.name) AS parties
    ORDER BY t.observed_date
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()
    return neo4j_to_json(data)

# ---------------------------------------------------------------------------
# API: milestones for an EmTech
# ---------------------------------------------------------------------------

@app.get("/api/emtech/{name}/milestones")
async def emtech_milestones(name: str):
    query = """
    MATCH (e:EmTech {name: $name})-[:ENABLES]->(c:Capability)-[:HAS_MILESTONE]->(m:Milestone)
    OPTIONAL MATCH (ptc:PTC)-[:REACHES]->(m)
    OPTIONAL MATCH (m)-[:UNLOCKS]->(lac:LAC)
    RETURN DISTINCT m.name AS name, m.description AS description,
           m.milestone_reached_date AS date,
           c.name AS capability,
           collect(DISTINCT ptc.name) AS reached_by,
           collect(DISTINCT lac.name) AS unlocks
    ORDER BY m.milestone_reached_date
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()
    return neo4j_to_json(data)

# ---------------------------------------------------------------------------
# API: bets for an EmTech
# ---------------------------------------------------------------------------

@app.get("/api/emtech/{name}/bets")
async def emtech_bets(name: str):
    query = """
    MATCH (e:EmTech {name: $name})-[:ENABLES]->(c:Capability)
    OPTIONAL MATCH (b:Bet)-[:DEPENDS_ON]->(c)
    WITH DISTINCT b WHERE b IS NOT NULL
    OPTIONAL MATCH (b)<-[:PLACES]-(idea:Idea)
    OPTIONAL MATCH (vm:Milestone)-[v:VALIDATES]->(b)
    OPTIONAL MATCH (im)-[inv:INVALIDATES]->(b)
    RETURN b.name AS name, b.description AS description,
           b.placed_date AS placed_date, b.result AS result,
           collect(DISTINCT idea.name) AS ideas,
           collect(DISTINCT {milestone: vm.name, date: v.date}) AS validations,
           collect(DISTINCT {source: COALESCE(im.name, labels(im)[0]), date: inv.date}) AS invalidations
    ORDER BY b.placed_date DESC
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()
    return neo4j_to_json(data)

# ---------------------------------------------------------------------------
# API: milestone detail
# ---------------------------------------------------------------------------

@app.get("/api/milestone/{name}")
async def milestone_detail(name: str):
    query = """
    MATCH (m:Milestone {name: $name})
    OPTIONAL MATCH (c:Capability)-[:HAS_MILESTONE]->(m)
    OPTIONAL MATCH (ptc:PTC)-[r:REACHES]->(m)
    OPTIONAL MATCH (m)-[:UNLOCKS]->(lac:LAC)
    RETURN m.name AS name, m.description AS description,
           m.milestone_reached_date AS date,
           collect(DISTINCT {name: c.name, description: c.description}) AS capabilities,
           collect(DISTINCT {name: ptc.name, description: ptc.description, release_date: ptc.release_date, date: r.date}) AS reached_by,
           collect(DISTINCT {name: lac.name, description: lac.description}) AS unlocks
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()
    if not data:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return neo4j_to_json(data[0])

# ---------------------------------------------------------------------------
# API: trend analysis — AI calculates doubling rate
# ---------------------------------------------------------------------------

class TrendAnalyzeRequest(BaseModel):
    trend_name: str
    emtech: str

@app.post("/api/trend/analyze")
async def trend_analyze(req: TrendAnalyzeRequest):
    """Analyze a trend: fetch milestones and use AI to calculate doubling rate."""
    # 1. Get the trend details + its capability + milestones
    trend_query = """
    MATCH (t:Trend {name: $trend_name})
    OPTIONAL MATCH (t)-[:PREDICTS]->(c:Capability)
    RETURN t.name AS name, t.description AS description,
           t.observed_date AS observed_date,
           collect(DISTINCT c.name) AS capabilities
    """
    async with driver.session() as session:
        result = await session.run(trend_query, {"trend_name": req.trend_name})
        trend_data = await result.data()

    if not trend_data:
        raise HTTPException(status_code=404, detail="Trend not found")

    trend = neo4j_to_json(trend_data[0])
    capabilities = trend.get("capabilities", [])

    # 2. Get milestones for the capabilities this trend predicts
    milestones = []
    if capabilities:
        ms_query = """
        MATCH (c:Capability)-[:HAS_MILESTONE]->(m:Milestone)
        WHERE c.name IN $caps
        OPTIONAL MATCH (ptc:PTC)-[:REACHES]->(m)
        OPTIONAL MATCH (m)-[:UNLOCKS]->(lac:LAC)
        RETURN DISTINCT m.name AS name, m.description AS description,
               m.milestone_reached_date AS date,
               c.name AS capability,
               collect(DISTINCT ptc.name) AS reached_by,
               collect(DISTINCT lac.name) AS unlocks
        ORDER BY m.milestone_reached_date
        """
        async with driver.session() as session:
            result = await session.run(ms_query, {"caps": capabilities})
            ms_data = await result.data()
        milestones = neo4j_to_json(ms_data)

    # 3. Use AI to calculate doubling rate
    doubling_info = await _calculate_doubling_rate(trend, milestones)

    return {
        "trend": trend,
        "milestones": milestones,
        "doubling": doubling_info,
    }


class DoublingRateEstimate(BaseModel):
    months_per_doubling: float = Field(description="Estimated months per doubling")
    metric: str = Field(description="What is doubling (e.g., performance, accuracy, capacity)")
    reasoning: str = Field(description="1-2 sentences explaining your estimate")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence level")

async def _calculate_doubling_rate(trend: dict, milestones: list) -> dict:
    """Ask Grok to estimate months_per_doubling from trend data."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user

        # Build context from milestones
        ms_timeline = ""
        dated_milestones = [m for m in milestones if m.get("date")]
        for m in dated_milestones[:30]:
            ms_timeline += f"- {m['date']}: {m['name']}"
            if m.get("reached_by"):
                ms_timeline += f" (by: {', '.join([r for r in m['reached_by'] if r][:3])})"
            ms_timeline += "\n"

        prompt = (
            f"You are analyzing an exponential technology trend to estimate its growth rate.\n\n"
            f"**Trend**: {trend['name']}\n"
            f"**Description**: {trend.get('description', 'N/A')}\n"
            f"**Capabilities**: {', '.join(trend.get('capabilities', []))}\n\n"
            f"**Observed milestones** (chronological):\n{ms_timeline}\n\n"
            f"Based on the pace of these milestones and the nature of this technology area, "
            f"estimate the **doubling rate** — how many months it takes for capability/performance "
            f"to approximately double.\n\n"
            f"For reference:\n"
            f"- Moore's Law: ~18-24 months per doubling\n"
            f"- AI compute scaling (recent): ~6-8 months per doubling\n"
            f"- Solar energy cost: ~36 months per doubling (halving of cost)\n\n"
            f"Extract the doubling rate metrics accurately."
        )

        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=60)
        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            messages=[
                system("You are a technology analyst estimating exponential growth rates."),
                user(prompt),
            ],
            response_format=DoublingRateEstimate,
        )

        response = await chat.sample()
        result = DoublingRateEstimate.model_validate_json(response.content)
        return result.model_dump()

    except Exception as e:
        logger.warning(f"Doubling rate calculation failed: {e}")
        # Fallback: rough estimate based on milestone density
        dated = [m for m in milestones if m.get("date")]
        if len(dated) >= 2:
            from datetime import datetime
            try:
                first = datetime.fromisoformat(str(dated[0]["date"]))
                last = datetime.fromisoformat(str(dated[-1]["date"]))
                span_months = max(1, (last - first).days / 30)
                # Rough: assume each milestone represents ~1 doubling
                mpd = max(1, round(span_months / len(dated)))
                return {"months_per_doubling": mpd, "metric": "capability", "reasoning": "Estimated from milestone density (AI unavailable)", "confidence": "low"}
            except Exception:
                pass
        return {"months_per_doubling": 12, "metric": "capability", "reasoning": "Default estimate (insufficient data)", "confidence": "low"}

# ---------------------------------------------------------------------------
# API: spot a trend from user input (like /trend command)
# ---------------------------------------------------------------------------

class SpottedTrendDetails(BaseModel):
    trend_name: str = Field(description="A concise, descriptive name for the trend")
    description: str = Field(description="A 2-4 sentence description of the trend, explaining what is being observed and why")
    capabilities: list[str] = Field(description="Array of capability names from the KG that this trend relates to")
    evidence: list[str] = Field(description="Array of 3-5 pieces of evidence (milestones, observations) supporting this trend")
    months_per_doubling: Optional[float] = Field(description="Estimated months per doubling (if this is an exponential trend, otherwise null)")
    metric: Optional[str] = Field(description="What is doubling (e.g., performance, adoption, capability)")
    prediction: str = Field(description="What this trend predicts for the next 1-2 years")

class SpotTrendRequest(BaseModel):
    topic: str
    emtech: str

@app.post("/api/trend/spot")
async def spot_trend(req: SpotTrendRequest):
    """Use AI to spot a trend based on user input, using KG context."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user

        # Gather KG context: capabilities and milestones related to the emtech
        cap_query = """
        MATCH (e:EmTech {name: $emtech})-[:ENABLES]->(c:Capability)
        OPTIONAL MATCH (c)-[:HAS_MILESTONE]->(m:Milestone)
        WITH c, collect(DISTINCT m.name) AS milestones
        RETURN c.name AS capability, c.description AS description,
               milestones
        LIMIT 30
        """
        async with driver.session() as session:
            result = await session.run(cap_query, {"emtech": req.emtech})
            caps_data = await result.data()

        # Also grab existing trends for context
        trend_query = """
        MATCH (e:EmTech {name: $emtech})-[:ENABLES]->(c:Capability)<-[:PREDICTS]-(t:Trend)
        RETURN DISTINCT t.name AS name, t.description AS description
        LIMIT 15
        """
        async with driver.session() as session:
            result = await session.run(trend_query, {"emtech": req.emtech})
            trends_data = await result.data()

        kg_context = "\n### Capabilities:\n"
        for c in neo4j_to_json(caps_data)[:20]:
            ms_str = ", ".join(c.get("milestones", [])[:5]) if c.get("milestones") else "none yet"
            kg_context += f"- **{c['capability']}**: {c.get('description', '')[:150]} (milestones: {ms_str})\n"

        kg_context += "\n### Existing Trends:\n"
        for t in neo4j_to_json(trends_data):
            kg_context += f"- {t['name']}: {t.get('description', '')[:100]}\n"

        system_prompt = (
            "You are a technology trend analyst. You identify exponential trends in emerging technologies. "
            "Trends are explanations of what we observe — they must be hard to vary, testable, and have explanatory depth.\n\n"
            "You have access to a knowledge graph with capabilities and milestones. "
            "Your task is to spot a trend related to the user's topic.\n\n"
            "Extract the requested trend properties accurately."
        )

        user_prompt = (
            f"Spot a trend related to: **{req.topic}**\n\n"
            f"EmTech sector: {req.emtech}\n\n"
            f"Knowledge graph context:\n{kg_context}\n\n"
            f"Identify the trend, provide evidence from the KG context, and estimate the growth rate if exponential."
        )

        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=90)
        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            messages=[
                system(system_prompt),
                user(user_prompt),
            ],
            response_format=SpottedTrendDetails,
        )

        response = await chat.sample()

        try:
            result = SpottedTrendDetails.model_validate_json(response.content)
            return {"spotted": result.model_dump(), "emtech": req.emtech}
        except Exception as e:
            return {"spotted": {"trend_name": "Analysis", "description": str(e)}, "emtech": req.emtech, "raw": True}

    except Exception as e:
        logger.error(f"Trend spotting failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: save a spotted trend to the knowledge graph
# ---------------------------------------------------------------------------

class SaveTrendRequest(BaseModel):
    trend_name: str
    description: str
    capabilities: list[str] = []
    emtech: str

@app.post("/api/trend/save")
async def save_trend(req: SaveTrendRequest):
    """Save a spotted trend as a Trend node in Neo4j, with embeddings."""
    try:
        import asyncio
        from openai import AsyncOpenAI
        from groq import AsyncGroq
        from function_tools.core_graph_ops import GraphOpsCtx, core_create_node, core_create_edge

        groq_client = AsyncGroq(api_key=GROQ_API_KEY)
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        ctx = GraphOpsCtx(neo4jdriver=driver, lock=asyncio.Lock())

        # Create the Trend node via smart_upsert
        result = await core_create_node(
            ctx, "Trend", req.trend_name, req.description,
            groq_client=groq_client,
            openai_embedding_client=openai_client,
        )

        # Connect it to capabilities via PREDICTS edges
        edge_results = []
        for cap_name in req.capabilities:
            try:
                edge_result = await core_create_edge(
                    ctx, "Trend", req.trend_name, "PREDICTS", "Capability", cap_name
                )
                edge_results.append(edge_result)
            except Exception as e:
                logger.warning(f"Edge creation failed for {cap_name}: {e}")

        return {
            "status": "saved",
            "node_result": result,
            "edges_created": len(edge_results),
            "trend_name": req.trend_name,
        }

    except Exception as e:
        logger.error(f"Trend save failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: X news scan — returns a list of news items
# ---------------------------------------------------------------------------

class NewsItem(BaseModel):
    headline: str = Field(description="A concise headline (one sentence)")
    summary: str = Field(description="A 2-3 sentence summary of what happened")
    source: str = Field(description="Where the news comes from (e.g., 'X/@handle', 'TechCrunch', 'Reuters')")
    date: str = Field(description="Approximate date (e.g., '2026-03-01')")
    significance: Literal["high", "medium", "low"] = Field(description="Significance of the news")

class NewsResponse(BaseModel):
    items: list[NewsItem] = Field(description="List of 5-12 distinct news items")

class NewsRequest(BaseModel):
    emtech: str
    topic: str | None = None

@app.post("/api/news")
async def news_search(req: NewsRequest):
    """Search X and web for latest news items on an EmTech or a specific topic. Returns a JSON list of items."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user
        from xai_sdk.tools import web_search, x_search
        from datetime import datetime, timedelta, timezone

        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=120)

        now = datetime.now(timezone.utc)
        from_date = now - timedelta(hours=24)

        tools = [
            web_search(excluded_domains=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"]),
            x_search(from_date=from_date, to_date=now),
        ]

        if req.topic:
            # Targeted search: user provided a specific news topic
            system_prompt = (
                f"You are an intelligence analyst monitoring emerging technologies. "
                f"Search X and the web for the latest news and developments specifically about: '{req.topic}' "
                f"(in the context of the '{req.emtech}' sector). Focus on this specific topic. "
                f"Extract 5-12 distinct news items accurately."
            )
            user_prompt = (
                f"Find the latest news, discussions, and expert opinions about: {req.topic}. "
                f"Context: this relates to the {req.emtech} technology sector. "
                f"Search both X and the web for the most recent and relevant developments."
            )
        else:
            # Original EmTech-wide scan
            system_prompt = (
                f"You are an intelligence analyst monitoring emerging technologies. "
                f"Search X and the web for the latest developments in '{req.emtech}' from the last 24 hours. "
                f"Extract 5-12 distinct news items accurately."
            )
            user_prompt = (
                f"What are the latest developments and news in {req.emtech}? "
                f"Focus on breakthroughs, product launches, funding, partnerships, and expert opinions "
                f"from the last 24 hours."
            )

        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            tools=tools,
            messages=[
                system(system_prompt),
                user(user_prompt),
            ],
            response_format=NewsResponse,
        )

        response = await chat.sample()

        try:
            result = NewsResponse.model_validate_json(response.content)
            return {"items": [item.model_dump() for item in result.items], "emtech": req.emtech, "topic": req.topic}
        except Exception as e:
            return {"items": [], "raw_content": str(e) + "\n\n" + response.content, "emtech": req.emtech, "topic": req.topic}


    except Exception as e:
        logger.error(f"News search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: deep analysis of a news item (like /analyze command)
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    headline: str
    summary: str
    emtech: str

@app.post("/api/analyze")
async def analyze_news(req: AnalyzeRequest):
    """Deep-analyze a news event with agentic KG/X tools."""
    try:
        xai_client = XAIAsyncClient(api_key=XAI_API_KEY, timeout=180)
        openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        ctx = GraphOpsCtx(neo4jdriver=driver, lock=asyncio.Lock())

        tools = [
            TOOLS_DEFINITIONS["execute_cypher_query"],
            TOOLS_DEFINITIONS["find_node"],
            TOOLS_DEFINITIONS["scan_ideas"],
            TOOLS_DEFINITIONS["scan_trends"],
            TOOLS_DEFINITIONS["dfs"],
            TOOLS_DEFINITIONS["x_search"],
        ]

        system_prompt = (
            """
            You are an intelligence analyst performing a deep, multi-dimensional analysis of a news event. 
            You have access to a knowledge graph containing ideas, trends, bets, milestones, and assessments about emerging technologies. 
            Gather relevant KG context with tools, search for current evidence, and build a comprehensive analysis.

            Use tools proactively before answering

            Structure your response in exactly these sections using markdown:

            ## 📰 What Happened
            [The facts: who did what, when, and the immediate context.]
            ## 🎯 Why It Matters
            [Significance in the broader technology landscape. What does this signal about where the industry is heading? Connect to known trends and capabilities.]
            ## 🧩 Party Motivations
            [For each party involved, analyze their likely motivations, strategic reasoning, and what they stand to gain or lose.]
            ## 🔮 Who Predicted This
            [Reference any ideas, assessments, or bets from the knowledge graph that anticipated this kind of move. Credit those who saw it coming.]
            ## ⚡ Implications
            [What this means going forward. What does it validate or invalidate? What new capabilities or competitive dynamics might emerge? How does it affect existing bets?]
            ## ❓ Questions to Track
            [Open questions this raises that should be monitored.]
            Be analytical, cite sources, connect dots. This is a deep analysis, not a summary.
            """
        )

        user_prompt = (
            f"Analyze this news event:\n\n"
            f"**{req.headline}**\n{req.summary}\n\n"
            f"EmTech sector: {req.emtech}\n"
        )

        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            tool_choice="auto",
            tools=tools,
            messages=[xai_system(system_prompt), xai_user(user_prompt)],
        )

        for _ in range(40):
            response = await chat.sample()

            if not getattr(response, "tool_calls", None):
                return {"content": response.content, "headline": req.headline, "emtech": req.emtech}

            chat.append(response)

            for tool_call in response.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments or "{}")

                if function_name in FUNCTIONS_WITH_CTX:
                    function_args = {"ctx": ctx, **function_args}
                if function_name in FUNCTIONS_WITH_OPENAI:
                    function_args["openai_embedding_client"] = openai_embedding_client
                if function_name in FUNCTIONS_WITH_XAI_CLIENT:
                    function_args["xai_client"] = xai_client

                try:
                    result = await CHAT_FUNCTION_MAP[function_name](**function_args)
                    result_payload = result if isinstance(result, str) else json.dumps(result)
                except Exception as tool_error:
                    result_payload = json.dumps({"error": str(tool_error)})

                chat.append(xai_tool_result(result_payload))

        raise RuntimeError("Analysis exceeded tool-call iteration limit")

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



    """Query the knowledge graph for related ideas, trends, and bets."""
    context = {"ideas": [], "trends": [], "bets": []}

    try:
        # Find related ideas
        ideas_query = """
        MATCH (e:EmTech {name: $emtech})-[:ENABLES]->(c:Capability)
        OPTIONAL MATCH (i:Idea)-[:RELATES_TO]->(c)
        WITH DISTINCT i WHERE i IS NOT NULL
        RETURN i.name AS name, i.description AS description
        LIMIT 15
        """
        async with driver.session() as session:
            result = await session.run(ideas_query, {"emtech": emtech})
            data = await result.data()
            context["ideas"] = neo4j_to_json(data)

        # Find related trends
        trends_query = """
        MATCH (e:EmTech {name: $emtech})-[:ENABLES]->(c:Capability)<-[:PREDICTS]-(t:Trend)
        RETURN DISTINCT t.name AS name, t.description AS description,
               t.observed_date AS observed_date
        ORDER BY t.observed_date DESC LIMIT 10
        """
        async with driver.session() as session:
            result = await session.run(trends_query, {"emtech": emtech})
            data = await result.data()
            context["trends"] = neo4j_to_json(data)

        # Find related bets
        bets_query = """
        MATCH (e:EmTech {name: $emtech})-[:ENABLES]->(c:Capability)<-[:DEPENDS_ON]-(b:Bet)
        RETURN DISTINCT b.name AS name, b.description AS description,
               b.placed_date AS placed_date, b.result AS result
        LIMIT 10
        """
        async with driver.session() as session:
            result = await session.run(bets_query, {"emtech": emtech})
            data = await result.data()
            context["bets"] = neo4j_to_json(data)

    except Exception as e:
        logger.warning(f"KG context gathering failed: {e}")

    return context

# ---------------------------------------------------------------------------
# API: ideas for an EmTech
# ---------------------------------------------------------------------------

@app.get("/api/emtech/{name}/ideas")
async def emtech_ideas(name: str):
    query = """
    MATCH (e:EmTech {name: $name})-[:ENABLES]->(c:Capability)<-[:RELATES_TO]-(i:Idea)
    OPTIONAL MATCH (i)-[:RELATES_TO]->(p:Party)
    RETURN DISTINCT i.name AS name, i.description AS description,
           i.date AS date, i.argument AS argument,
           collect(DISTINCT p.name) AS parties
    ORDER BY i.date DESC
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()
    return neo4j_to_json(data)

# ---------------------------------------------------------------------------
# API: idea detail
# ---------------------------------------------------------------------------

@app.get("/api/idea/{name}")
async def idea_detail(name: str):
    query = """
    MATCH (i:Idea {name: $name})
    OPTIONAL MATCH (i)-[:PLACES]->(b:Bet)
    OPTIONAL MATCH (i)-[:RELATES_TO]->(c:Capability)
    OPTIONAL MATCH (i)-[:RELATES_TO]->(p:Party)
    RETURN i.name AS name, i.description AS description,
           i.argument AS argument, i.assumptions AS assumptions,
           i.counterargument AS counterargument,
           i.date AS date, i.last_updated_date AS last_updated_date,
           collect(DISTINCT {name: b.name, description: b.description, placed_date: b.placed_date, result: b.result}) AS bets,
           collect(DISTINCT {name: c.name, description: c.description}) AS capabilities,
           collect(DISTINCT {name: p.name, description: p.description}) AS parties
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()
    if not data:
        raise HTTPException(status_code=404, detail="Idea not found")
    return neo4j_to_json(data[0])

# ---------------------------------------------------------------------------
# API: check an idea (like /check command)
# ---------------------------------------------------------------------------

class CheckIdeaRequest(BaseModel):
    idea_name: str
    emtech: str

@app.post("/api/idea/check")
async def check_idea(req: CheckIdeaRequest):
    """Validate an idea/prediction with agentic KG + X/web tool use, like /check."""
    try:
        xai_client = XAIAsyncClient(api_key=XAI_API_KEY, timeout=180)
        openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        ctx = GraphOpsCtx(neo4jdriver=driver, lock=asyncio.Lock())

        # Ensure idea exists early for clearer API behavior.
        exists = await core_execute_cypher_query(
            ctx,
            "MATCH (i:Idea {name: $name}) RETURN i.name AS name LIMIT 1",
            {"name": req.idea_name},
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Idea not found")

        tools = [
            TOOLS_DEFINITIONS["execute_cypher_query"],
            TOOLS_DEFINITIONS["find_node"],
            TOOLS_DEFINITIONS["scan_ideas"],
            TOOLS_DEFINITIONS["scan_trends"],
            TOOLS_DEFINITIONS["dfs"],
            TOOLS_DEFINITIONS["x_search"],
        ]

        system_prompt = (
            "You are an intelligence analyst validating ideas, assessments, and predictions "
            "against evidence from a knowledge graph and current developments. "
            "Gather context agentically by using tools before producing your final answer.\n\n"
            "Structure your response in exactly these sections using markdown:\n\n"
            "## 🧐 Validity Check\nCheck if the prediction/idea is valid based on the evidence.\n\n"
            "## 🔮 Future Outlook\nIf the prediction is valid, what to expect going forward.\n\n"
            "## 📉 Reasoning\nIf the prediction is not valid, explain why.\n\n"
            "Be analytical, cite specific evidence from tool outputs."
        )

        user_prompt = (
            f"Validate this idea/assessment: {req.idea_name}\n"
            f"EmTech sector: {req.emtech}\n\n"
            "First gather relevant graph context around the idea (related trends, neighbors, bets, "
            "supporting/contradicting signals), then gather current external evidence with x_search, "
            "then provide your analysis."
        )

        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            tool_choice="auto",
            tools=tools,
            messages=[xai_system(system_prompt), xai_user(user_prompt)],
        )

        for _ in range(40):
            response = await chat.sample()

            if not getattr(response, "tool_calls", None):
                return {"content": response.content, "idea_name": req.idea_name, "emtech": req.emtech}

            chat.append(response)

            for tool_call in response.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments or "{}")

                if function_name in FUNCTIONS_WITH_CTX:
                    function_args = {"ctx": ctx, **function_args}
                if function_name in FUNCTIONS_WITH_OPENAI:
                    function_args["openai_embedding_client"] = openai_embedding_client
                if function_name in FUNCTIONS_WITH_XAI_CLIENT:
                    function_args["xai_client"] = xai_client

                try:
                    result = await CHAT_FUNCTION_MAP[function_name](**function_args)
                    result_payload = result if isinstance(result, str) else json.dumps(result)
                except Exception as tool_error:
                    result_payload = json.dumps({"error": str(tool_error)})

                chat.append(xai_tool_result(result_payload))

        raise RuntimeError("Idea check exceeded tool-call iteration limit")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Idea check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: evaluate a bet (combines /validate, /gaps, /stale, /contradict)
# ---------------------------------------------------------------------------

class EvaluateBetRequest(BaseModel):
    bet_name: str
    emtech: str

@app.post("/api/bet/evaluate")
async def evaluate_bet(req: EvaluateBetRequest):
    """Comprehensive bet evaluation using agentic tool calls for KG + X context gathering."""
    try:
        # 1) Basic bet fetch for existence + key metadata; deeper context is gathered agentically via tools.
        bet_query = """
        MATCH (b:Bet {name: $name})
        RETURN b.name AS name,
               b.description AS description,
               b.placed_date AS placed_date,
               b.result AS result,
               b.validations AS validations,
               b.invalidations AS invalidations
        LIMIT 1
        """
        async with driver.session() as session:
            result = await session.run(bet_query, {"name": req.bet_name})
            bet_row = await result.single()

        if not bet_row:
            raise HTTPException(status_code=404, detail="Bet not found")

        bet = neo4j_to_json(dict(bet_row))

        # 2) Agentic evaluation with tool calling.
        xai_client = XAIAsyncClient(api_key=XAI_API_KEY, timeout=180)
        openai_embedding_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        ctx = GraphOpsCtx(neo4jdriver=driver, lock=asyncio.Lock())

        tools = [
            TOOLS_DEFINITIONS["execute_cypher_query"],
            TOOLS_DEFINITIONS["find_node"],
            TOOLS_DEFINITIONS["scan_ideas"],
            TOOLS_DEFINITIONS["scan_trends"],
            TOOLS_DEFINITIONS["dfs"],
            TOOLS_DEFINITIONS["x_search"],
        ]

        system_prompt = (
            "You are an intelligence analyst performing a comprehensive evaluation of a strategic bet. "
            "You have function tools to gather context from the knowledge graph and X. "
            "Before producing your final answer, proactively call tools to collect concrete evidence. "
            "Your evaluation must cover ALL of the following dimensions:\n\n"
            "Structure your response in exactly these sections using markdown:\n\n"
            "## 📊 Current Evidence\n"
            "What does the latest data say? Use x_search for recent developments related to "
            "this bet's thesis. Compare against the validation/invalidation signals.\n\n"
            "## ⏰ Staleness Check\n"
            "Is this bet outdated? Has the landscape shifted since the bet was placed? "
            "Are the assumptions still valid given recent milestones and developments? "
            "Flag if the bet is older than 6 months with no result.\n\n"
            "## 🕳️ Blindspots\n"
            "What gaps exist in the thinking? Are there dependencies or capabilities not being tracked? "
            "Are there known blindspots in the bet description that have no corresponding ideas exploring them? "
            "What questions should be asked but aren't?\n\n"
            "## ⚔️ Contradictions & Tensions\n"
            "Are there other positions, bets, or trends that contradict this bet? "
            "Do the parent idea's assumptions conflict with evidence from other ideas? "
            "Are there tensions that need to be resolved?\n\n"
            "## 🔮 Updated Assessment\n"
            "Based on all of the above, should this bet be:\n"
            "- ✅ **Maintained** — still valid, evidence supports it\n"
            "- 🔄 **Revised** — core thesis has merit but needs updating\n"
            "- ❌ **Closed** — evidence has moved decisively against it\n\n"
            "Be analytical, cite specific evidence, and be honest about uncertainty."
        )

        user_prompt = (
            f"Evaluate this strategic bet:\n\n"
            f"- Bet: {bet.get('name')}\n"
            f"- Description: {bet.get('description', 'N/A')}\n"
            f"- Placed date: {bet.get('placed_date', 'N/A')}\n"
            f"- Current result: {bet.get('result', 'N/A')}\n"
            f"- Existing validations (if any): {bet.get('validations', [])}\n"
            f"- Existing invalidations (if any): {bet.get('invalidations', [])}\n\n"
            f"EmTech sector: {req.emtech}\n\n"
            "Use tools to gather missing context from the graph and recent X evidence. "
            "Then provide your comprehensive evaluation covering all five dimensions."
        )

        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            tool_choice="auto",
            tools=tools,
            messages=[
                xai_system(system_prompt),
                xai_user(user_prompt),
            ],
        )

        content = ""
        for _ in range(40):
            response = await chat.sample()
            if not getattr(response, "tool_calls", None):
                content = response.content
                break

            chat.append(response)

            for tool_call in response.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments or "{}")

                if function_name in FUNCTIONS_WITH_CTX:
                    function_args = {"ctx": ctx, **function_args}
                if function_name in FUNCTIONS_WITH_OPENAI:
                    function_args["openai_embedding_client"] = openai_embedding_client
                if function_name in FUNCTIONS_WITH_XAI_CLIENT:
                    function_args["xai_client"] = xai_client

                try:
                    result = await CHAT_FUNCTION_MAP[function_name](**function_args)
                    result_payload = result if isinstance(result, str) else json.dumps(result)
                except Exception as tool_error:
                    result_payload = json.dumps({"error": str(tool_error)})

                chat.append(xai_tool_result(result_payload))

        if not content:
            raise RuntimeError("Bet evaluation exceeded tool-call iteration limit")

        # 3) Persist latest evaluation snapshot on the Bet node so UI/state can
        # immediately reflect the most recent validation and invalidation signals.
        # Keep both `validations` and legacy typo `vallidations` for compatibility.
        evaluation_result = None
        content_lower = content.lower()
        if "maintained" in content_lower:
            evaluation_result = "maintained"
        elif "revised" in content_lower:
            evaluation_result = "revised"
        elif "closed" in content_lower:
            evaluation_result = "closed"

        update_query = """
        MATCH (b:Bet {name: $name})
        SET b.validations = $validations,
            b.vallidations = $validations,
            b.invalidations = $invalidations,
            b.last_evaluated_at = datetime(),
            b.last_evaluation = $evaluation
        FOREACH (_ IN CASE WHEN $result IS NULL THEN [] ELSE [1] END |
            SET b.result = $result
        )
        RETURN b.name AS name,
               b.result AS result,
               b.validations AS validations,
               b.invalidations AS invalidations
        """

        async with driver.session() as session:
            update_result = await session.run(update_query, {
                "name": req.bet_name,
                "validations": bet.get("validations", []),
                "invalidations": bet.get("invalidations", []),
                "evaluation": content,
                "result": evaluation_result,
            })
            updated_bet = await update_result.single()

        updated_payload = neo4j_to_json(dict(updated_bet)) if updated_bet else {
            "name": req.bet_name,
            "result": evaluation_result,
            "validations": bet.get("validations", []),
            "invalidations": bet.get("invalidations", []),
        }

        return {
            "content": content,
            "bet_name": req.bet_name,
            "emtech": req.emtech,
            "validations": updated_payload.get("validations", bet.get("validations", [])),
            "invalidations": updated_payload.get("invalidations", bet.get("invalidations", [])),
            "result": updated_payload.get("result", evaluation_result),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bet evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: map/search — semantic search for trends + ideas
# ---------------------------------------------------------------------------

class MapRequest(BaseModel):
    query: str
    emtech: str

@app.post("/api/map")
async def map_search(req: MapRequest):
    """Semantic search for trends, ideas, and convergences related to a query."""
    try:
        import asyncio
        from openai import AsyncOpenAI
        from function_tools.core_graph_ops import GraphOpsCtx, core_scan_ideas, core_scan_trends

        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        ctx = GraphOpsCtx(neo4jdriver=driver, lock=asyncio.Lock())

        # Use the query itself as the probe for semantic search
        probes = [req.query]

        # Run ideas + trends scans in parallel
        ideas_task = core_scan_ideas(
            ctx, query_probes=probes, top_k_per_probe=15, max_results=20,
            openai_embedding_client=openai_client,
        )
        trends_task = core_scan_trends(
            ctx, query_probes=probes, top_k_per_probe=15, max_results=20,
            emtech_filter=req.emtech,
            openai_embedding_client=openai_client,
        )

        ideas_results, trends_results = await asyncio.gather(ideas_task, trends_task)

        # Format results
        ideas = []
        for r in ideas_results:
            node = r.get("node", {})
            ideas.append({
                "name": node.get("name", ""),
                "description": node.get("description", ""),
                "score": r.get("score", 0),
                "node_type": r.get("node_type", "Idea"),
                "date": node.get("date"),
                "argument": node.get("argument"),
            })

        trends = []
        for r in trends_results:
            node = r.get("node", {})
            trends.append({
                "name": node.get("name", ""),
                "description": node.get("description", ""),
                "score": r.get("score", 0),
            })

        # Semantic search for convergences
        convergences = await _search_convergences(openai_client, req.query, req.emtech)

        return {
            "query": req.query,
            "emtech": req.emtech,
            "trends": trends,
            "ideas": ideas,
            "convergences": convergences,
        }

    except Exception as e:
        logger.error(f"Map search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _search_convergences(openai_client, query: str, emtech: str) -> list:
    """Semantic vector search for Convergence nodes filtered to the given EmTech."""
    try:
        # 1. Generate embedding for the query
        emb_response = await openai_client.embeddings.create(
            model="text-embedding-3-large", input=[query]
        )
        embedding = emb_response.data[0].embedding

        # 2. Query the convergence vector index
        vector_query = """
        CALL db.index.vector.queryNodes('convergence_description_embeddings', $top_k, $embedding)
        YIELD node, score
        WITH node AS conv, score
        // Filter: must be connected to the selected EmTech
        WHERE EXISTS {
            (e:EmTech {name: $emtech})-[:ACCELERATES|IS_ACCELERATED_BY]->(conv)
        }
        // Get the other EmTechs involved and the direction
        OPTIONAL MATCH (e:EmTech {name: $emtech})-[r:ACCELERATES|IS_ACCELERATED_BY]->(conv)
        OPTIONAL MATCH (other:EmTech)-[:ACCELERATES|IS_ACCELERATED_BY]->(conv)
        WHERE other.name <> $emtech
        RETURN conv.name AS name, conv.description AS description,
               score,
               type(r) AS direction,
               collect(DISTINCT other.name) AS other_emtechs
        ORDER BY score DESC
        """
        async with driver.session() as session:
            result = await session.run(vector_query, {
                "top_k": 20,
                "embedding": embedding,
                "emtech": emtech,
            })
            data = await result.data()

        return neo4j_to_json(data)

    except Exception as e:
        logger.warning(f"Convergence semantic search failed: {e}")
        return []

# ---------------------------------------------------------------------------
# API: EmTech advancement — capabilities, milestones, use cases, products
# ---------------------------------------------------------------------------

@app.get("/api/emtech/{name}/advancement")
async def emtech_advancement(name: str):
    """Return a structured tree: Capability → Milestones → LAC → LTC → PTC (with vendor)."""
    query = """
    MATCH (e:EmTech {name: $name})-[:ENABLES]->(c:Capability)
    OPTIONAL MATCH (c)-[:HAS_MILESTONE]->(m:Milestone)
    OPTIONAL MATCH (m)-[:UNLOCKS]->(lac:LAC)
    OPTIONAL MATCH (lac)-[:USES]->(ltc:LTC)
    OPTIONAL MATCH (ltc)-[:IS_REALIZED_BY]->(ptc:PTC)
    OPTIONAL MATCH (party:Party)-[:MAKES]->(ptc)
    RETURN c.name AS capability, c.description AS cap_desc,
           m.name AS milestone, m.description AS ms_desc,
           m.milestone_reached_date AS ms_date,
           lac.name AS lac_name, lac.description AS lac_desc,
           ltc.name AS ltc_name, ltc.description AS ltc_desc,
           ptc.name AS ptc_name, ptc.description AS ptc_desc,
           ptc.release_date AS ptc_release_date,
           party.name AS vendor
    ORDER BY c.name, m.milestone_reached_date, lac.name, ltc.name, ptc.name
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()

    rows = neo4j_to_json(data)

    # Restructure flat rows into a nested tree
    cap_map = {}  # capability_name -> { ... }
    for row in rows:
        cap_name = row.get("capability")
        if not cap_name:
            continue

        if cap_name not in cap_map:
            cap_map[cap_name] = {
                "capability": cap_name,
                "capability_desc": row.get("cap_desc", ""),
                "milestones": {},
            }
        cap = cap_map[cap_name]

        ms_name = row.get("milestone")
        if not ms_name:
            continue

        if ms_name not in cap["milestones"]:
            cap["milestones"][ms_name] = {
                "name": ms_name,
                "description": row.get("ms_desc", ""),
                "date": row.get("ms_date"),
                "unlocks": {},
            }
        ms = cap["milestones"][ms_name]

        lac_name = row.get("lac_name")
        if not lac_name:
            continue

        if lac_name not in ms["unlocks"]:
            ms["unlocks"][lac_name] = {
                "lac_name": lac_name,
                "lac_desc": row.get("lac_desc", ""),
                "products": {},
            }
        lac = ms["unlocks"][lac_name]

        ltc_name = row.get("ltc_name")
        if not ltc_name:
            continue

        if ltc_name not in lac["products"]:
            lac["products"][ltc_name] = {
                "ltc_name": ltc_name,
                "ltc_desc": row.get("ltc_desc", ""),
                "ptcs": [],
            }
        ltc = lac["products"][ltc_name]

        ptc_name = row.get("ptc_name")
        if ptc_name and not any(p["name"] == ptc_name for p in ltc["ptcs"]):
            ltc["ptcs"].append({
                "name": ptc_name,
                "description": row.get("ptc_desc", ""),
                "release_date": row.get("ptc_release_date"),
                "vendor": row.get("vendor"),
            })

    # Convert dicts to lists for JSON response
    result_tree = []
    for cap in cap_map.values():
        ms_list = sorted(cap["milestones"].values(), key=lambda m: m.get("date") or "9999")
        for ms in ms_list:
            unlocks_list = list(ms["unlocks"].values())
            for lac in unlocks_list:
                lac["products"] = list(lac["products"].values())
            ms["unlocks"] = unlocks_list
        cap["milestones"] = ms_list
        result_tree.append(cap)

    return result_tree

# ---------------------------------------------------------------------------
# API: convergences for an EmTech
# ---------------------------------------------------------------------------

@app.get("/api/emtech/{name}/convergences")
async def emtech_convergences(name: str):
    """Return Convergence nodes where the selected EmTech ACCELERATES or IS_ACCELERATED_BY."""
    query = """
    MATCH (e:EmTech {name: $name})-[r:ACCELERATES|IS_ACCELERATED_BY]->(conv:Convergence)
    OPTIONAL MATCH (other:EmTech)-[:ACCELERATES|IS_ACCELERATED_BY]->(conv)
    WHERE other.name <> $name
    RETURN conv.name AS name, conv.description AS description,
           type(r) AS direction,
           collect(DISTINCT other.name) AS other_emtechs
    ORDER BY conv.name
    """
    async with driver.session() as session:
        result = await session.run(query, {"name": name})
        data = await result.data()
    return neo4j_to_json(data)


# ---------------------------------------------------------------------------
# API: pathway — AI analysis of why a use case matters for global problems
# ---------------------------------------------------------------------------

class PathwayRequest(BaseModel):
    lac_name: str
    emtech: str

@app.post("/api/advancement/pathway")
async def advancement_pathway(req: PathwayRequest):
    """Show why a use case matters — using the /pathway prompt from command_sources."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user
        from xai_sdk.tools import web_search, x_search
        from datetime import datetime, timedelta, timezone

        # 1. Gather KG context about the LAC
        lac_query = """
        MATCH (lac:LAC {name: $lac_name})
        OPTIONAL MATCH (m:Milestone)-[:UNLOCKS]->(lac)
        OPTIONAL MATCH (c:Capability)-[:HAS_MILESTONE]->(m)
        OPTIONAL MATCH (lac)-[:USES]->(ltc:LTC)
        OPTIONAL MATCH (lac)-[:IS_REALIZED_BY]->(pac:PAC)
        RETURN lac.name AS name, lac.description AS description,
               collect(DISTINCT c.name) AS capabilities,
               collect(DISTINCT m.name) AS milestones,
               collect(DISTINCT ltc.name) AS product_categories,
               collect(DISTINCT pac.name) AS implementations
        """
        async with driver.session() as session:
            result = await session.run(lac_query, {"lac_name": req.lac_name})
            lac_data = await result.data()

        lac_context = ""
        if lac_data:
            lac = neo4j_to_json(lac_data[0])
            lac_context = (
                f"\n### Knowledge Graph Context for '{lac.get('name', req.lac_name)}':\n"
                f"- Description: {lac.get('description', 'N/A')}\n"
                f"- Related Capabilities: {', '.join(lac.get('capabilities', [])) or 'N/A'}\n"
                f"- Key Milestones: {', '.join(lac.get('milestones', [])[:10]) or 'N/A'}\n"
                f"- Product Categories: {', '.join(lac.get('product_categories', [])) or 'N/A'}\n"
                f"- Implementations: {', '.join(lac.get('implementations', [])) or 'N/A'}\n"
            )

        # 2. Call AI with the /pathway prompt structure
        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=180)

        now = datetime.now(timezone.utc)
        from_date = now - timedelta(hours=168)

        tools = [
            web_search(excluded_domains=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"]),
            x_search(from_date=from_date, to_date=now),
        ]

        global_problems = (
            "Rogue SuperIntelligence, Prevent Genocide, Extreme Poverty, "
            "Chemical and Biological Weapons, Asteroid Impact, Extreme Weather Events, "
            "Peace in the Middle East, Nuclear Annihilation, Slavery, "
            "Promote Equal Rights for Women, Lack of Education, Automation/UBI, "
            "Refugees, Sustainable Agriculture, Food Security, Ecological Crises, "
            "Infectious Diseases, Climate Crises, Cure Cancer, Mental Health Crises, "
            "Alzheimer, Ageing as a Disease, Clean Water, Air Pollution, Access to Energy, "
            "Homelessness, Cities/Urbanization, Child Health, Maternal Health"
        )

        system_prompt = (
            "You are a technology strategist who connects emerging technology use cases to "
            "humanity's biggest problems. Your analysis should be inspiring yet grounded. "
            "Use search tools to find current real-world examples.\n\n"
            "Structure your response in markdown with these sections:\n\n"
            "## 🌍 Why This Matters\n"
            "Explain what this use case is and why it's significant.\n\n"
            "## 🎯 Target Problem\n"
            "Pick the global problem where this use case can have the biggest impact. "
            "Provide a brief root cause analysis.\n\n"
            "## 🛤️ Pathway to Impact\n"
            "Propose a concrete solution using this use case. Show how it addresses root causes.\n\n"
            "## 🔗 Convergence Canvas\n"
            "Layer on more complexity: show how at least 5-6 emerging technology categories "
            "(AI, robots, synthetic biology, IoT, VR, 3D printing, networks, computing, etc.) "
            "can combine to deliver a comprehensive, interdisciplinary solution.\n\n"
            "## 📊 Real-World Evidence\n"
            "Current projects, companies, or research already working on this.\n\n"
            "## 🔮 Timeline\n"
            "Realistic timeline for when this pathway could start delivering meaningful impact."
        )

        user_prompt = (
            f"# Why should we care about {req.lac_name}?\n\n"
            f"New advancements in science, technology and engineering really only matter "
            f"when we can use them to solve humanity's big, global problems.\n\n"
            f"EmTech sector: {req.emtech}\n"
            f"{lac_context}\n\n"
            f"Global problems to consider: {global_problems}\n\n"
            f"Pick the problem where {req.lac_name} can have the biggest impact, "
            f"do a brief root cause analysis, and propose a pathway. "
            f"Use web and X search for current evidence."
        )

        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            tools=tools,
            messages=[
                system(system_prompt),
                user(user_prompt),
            ],
        )

        response = await chat.sample()
        return {"content": response.content, "lac_name": req.lac_name, "emtech": req.emtech}

    except Exception as e:
        logger.error(f"Pathway analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: filter advancement — AI-powered search of use cases (LAC)
# ---------------------------------------------------------------------------

class AdvFilterRequest(BaseModel):
    query: str
    emtech: str

@app.post("/api/advancement/filter")
async def advancement_filter(req: AdvFilterRequest):
    """Use AI to narrow down relevant use cases (LAC) based on user query."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user
        import json

        # 1. Gather all LACs for the EmTech
        lac_query = """
        MATCH (e:EmTech {name: $emtech})-[:ENABLES]->(c:Capability)
        MATCH (c)-[:HAS_MILESTONE]->(m:Milestone)
        MATCH (m)-[:UNLOCKS]->(lac:LAC)
        RETURN DISTINCT lac.name AS name, lac.description AS description
        """
        async with driver.session() as session:
            result = await session.run(lac_query, {"emtech": req.emtech})
            lac_data = await result.data()

        lacs = neo4j_to_json(lac_data)
        if not lacs:
            return {"lacs": []}

        # Format LAC list for the prompt
        lac_list_str = "\\n".join([f"- **{l['name']}**: {l.get('description', '')}" for l in lacs])

        # 2. Ask Grok to filter
        system_prompt = (
            "You are a technology analyst helping to filter a list of use cases (LACs). "
            "The user will provide a search query, and you must return ONLY the exact names "
            "of the use cases from the provided list that are highly relevant to the query. "
            "Return your answer ONLY as a valid JSON array of strings (the LAC names). "
            "Do not include any other text, markdown formatting, or explanation."
        )

        user_prompt = (
            f"Filter this list of use cases for the EmTech '{req.emtech}' based on "
            f"the user query: '{req.query}'\\n\\n"
            f"Use Cases:\\n{lac_list_str}\\n\\n"
            "Return ONLY a JSON array of the exact names of the relevant use cases."
        )

        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=60)
        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            messages=[
                system(system_prompt),
                user(user_prompt),
            ],
        )

        response = await chat.sample()
        content = response.content.strip()
        
        # Clean up potential markdown formatting in the LLM response
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            matched_lacs = json.loads(content)
            if not isinstance(matched_lacs, list):
                matched_lacs = []
        except json.JSONDecodeError:
            logger.warning(f"Advancement filter returned invalid JSON: {content}")
            matched_lacs = []

        return {"lacs": matched_lacs, "query": req.query, "emtech": req.emtech}

    except Exception as e:
        logger.error(f"Advancement filter failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
