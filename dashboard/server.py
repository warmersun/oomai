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
from xai_sdk.chat import system as xai_system

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
    """Deep-analyze a news event using KG context + X/web research."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user
        from xai_sdk.tools import web_search, x_search
        from datetime import datetime, timedelta, timezone

        # 1. Gather KG context in parallel
        kg_context = await _gather_kg_context(req.emtech, req.headline, req.summary)

        # 2. Run the deep analysis via Grok
        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=180)

        now = datetime.now(timezone.utc)
        from_date = now - timedelta(hours=24)

        tools = [
            web_search(excluded_domains=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"]),
            x_search(from_date=from_date, to_date=now),
        ]

        system_prompt = (
            "You are an intelligence analyst performing a deep, multi-dimensional analysis of a news event. "
            "You have access to a knowledge graph containing ideas, trends, bets, milestones, and assessments "
            "about emerging technologies. Use the KG context provided AND your X/web search tools to build "
            "a comprehensive analysis.\n\n"
            "Structure your response in exactly these sections using markdown:\n\n"
            "## 📰 What Happened\nThe facts: who did what, when, and the immediate context.\n\n"
            "## 🎯 Why It Matters\nSignificance in the broader technology landscape. What does this signal "
            "about where the industry is heading? Connect to known trends and capabilities.\n\n"
            "## 🧩 Party Motivations\nFor each party involved, analyze their likely motivations, strategic reasoning, "
            "and what they stand to gain or lose.\n\n"
            "## 🔮 Who Predicted This\nReference any ideas, assessments, or bets from the knowledge graph that "
            "anticipated this kind of move. Credit those who saw it coming.\n\n"
            "## ⚡ Implications\nWhat this means going forward. What does it validate or invalidate? "
            "What new capabilities or competitive dynamics might emerge? How does it affect existing bets?\n\n"
            "## ❓ Questions to Track\nOpen questions this raises that should be monitored.\n\n"
            "Be analytical, cite sources, connect dots. This is a deep analysis, not a summary."
        )

        kg_context_str = ""
        if kg_context.get("ideas"):
            kg_context_str += "\n\n### Related Ideas from Knowledge Graph:\n"
            for idea in kg_context["ideas"][:10]:
                kg_context_str += f"- **{idea['name']}**: {idea.get('description', '')[:200]}\n"
        if kg_context.get("trends"):
            kg_context_str += "\n\n### Related Trends from Knowledge Graph:\n"
            for trend in kg_context["trends"][:8]:
                kg_context_str += f"- **{trend['name']}**: {trend.get('description', '')[:200]}\n"
        if kg_context.get("bets"):
            kg_context_str += "\n\n### Active Bets from Knowledge Graph:\n"
            for bet in kg_context["bets"][:5]:
                kg_context_str += f"- **{bet['name']}**: {bet.get('description', '')[:200]}\n"

        user_prompt = (
            f"Analyze this news event:\n\n"
            f"**{req.headline}**\n{req.summary}\n\n"
            f"EmTech sector: {req.emtech}\n"
            f"{kg_context_str}\n\n"
            f"Use x_search and web_search to get the full story and latest reactions. "
            f"Then provide your deep analysis."
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
        return {"content": response.content, "headline": req.headline, "emtech": req.emtech}

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _gather_kg_context(emtech: str, headline: str, summary: str) -> dict:
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
    """Validate an idea/prediction using KG context + AI analysis, like /check command."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user

        # 1. Gather KG context around the idea
        idea_query = """
        MATCH (i:Idea {name: $name})
        OPTIONAL MATCH (i)-[:RELATES_TO]->(c)
        OPTIONAL MATCH (i)-[:PLACES]->(b:Bet)
        RETURN i.name AS name, i.description AS description,
               i.argument AS argument, i.assumptions AS assumptions,
               i.counterargument AS counterargument,
               collect(DISTINCT {name: c.name, type: labels(c)[0], description: c.description}) AS related,
               collect(DISTINCT {name: b.name, description: b.description, result: b.result}) AS bets
        """
        async with driver.session() as session:
            result = await session.run(idea_query, {"name": req.idea_name})
            idea_data = await result.data()

        if not idea_data:
            raise HTTPException(status_code=404, detail="Idea not found")

        idea = neo4j_to_json(idea_data[0])

        # 2. BFS — find related capabilities, milestones, products, applications
        bfs_query = """
        MATCH (i:Idea {name: $name})-[:RELATES_TO]->(c)
        WITH c
        OPTIONAL MATCH (c)-[:HAS_MILESTONE]->(m:Milestone)
        OPTIONAL MATCH (ptc:PTC)-[:REACHES]->(m)
        OPTIONAL MATCH (m)-[:UNLOCKS]->(lac:LAC)
        OPTIONAL MATCH (ltc:LTC)-[:PROVIDES]->(c)
        RETURN c.name AS capability, c.description AS cap_desc,
               collect(DISTINCT {name: m.name, date: m.milestone_reached_date}) AS milestones,
               collect(DISTINCT ptc.name) AS products,
               collect(DISTINCT lac.name) AS applications,
               collect(DISTINCT ltc.name) AS product_categories
        LIMIT 20
        """
        async with driver.session() as session:
            result = await session.run(bfs_query, {"name": req.idea_name})
            bfs_data = await result.data()

        bfs_context = neo4j_to_json(bfs_data)

        # 3. Build context string
        kg_str = f"**Idea**: {idea['name']}\n**Description**: {idea.get('description', 'N/A')}\n"
        if idea.get('argument'):
            kg_str += f"**Argument**: {idea['argument']}\n"
        if idea.get('assumptions'):
            kg_str += f"**Assumptions**: {idea['assumptions']}\n"
        if idea.get('counterargument'):
            kg_str += f"**Counterargument**: {idea['counterargument']}\n"

        if idea.get('bets'):
            kg_str += "\n**Associated Bets**:\n"
            for b in idea['bets']:
                if b.get('name'):
                    kg_str += f"- {b['name']}: {b.get('description', '')[:200]}\n"

        if bfs_context:
            kg_str += "\n**Related from Knowledge Graph**:\n"
            for item in bfs_context[:15]:
                kg_str += f"\n- **Capability**: {item.get('capability', 'N/A')}"
                if item.get('milestones'):
                    dated_ms = [m for m in item['milestones'] if m.get('name')]
                    if dated_ms:
                        kg_str += f"\n  Milestones: {', '.join(m['name'] + (' (' + str(m['date']) + ')' if m.get('date') else '') for m in dated_ms[:5])}"
                if item.get('products'):
                    prods = [p for p in item['products'] if p]
                    if prods:
                        kg_str += f"\n  Products: {', '.join(prods[:5])}"
                if item.get('applications'):
                    apps = [a for a in item['applications'] if a]
                    if apps:
                        kg_str += f"\n  Applications: {', '.join(apps[:5])}"

        # 4. Send to Grok with /check command structure
        system_prompt = (
            "You are an intelligence analyst validating ideas, assessments, and predictions "
            "against evidence from a knowledge graph and current developments. "
            "Structure your response in exactly these sections using markdown:\n\n"
            "## 🧐 Validity Check\nCheck if the prediction/idea is valid based on the evidence.\n\n"
            "## 🔮 Future Outlook\nIf the prediction is valid, what to expect going forward.\n\n"
            "## 📉 Reasoning\nIf the prediction is not valid, explain why.\n\n"
            "Be analytical, cite specific evidence from the knowledge graph context."
        )

        user_prompt = (
            f"Validate this idea/assessment:\n\n{kg_str}\n\n"
            f"EmTech sector: {req.emtech}\n\n"
            f"Evaluate whether the evidence supports or contradicts this idea. "
            f"Provide your analysis."
        )

        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=120)
        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            messages=[
                system(system_prompt),
                user(user_prompt),
            ],
        )

        response = await chat.sample()
        return {"content": response.content, "idea_name": req.idea_name, "emtech": req.emtech}

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
    """Comprehensive bet evaluation: validate, find blindspots, check staleness, find contradictions."""
    try:
        from xai_sdk import AsyncClient
        from xai_sdk.chat import system, user
        from xai_sdk.tools import web_search, x_search
        from datetime import datetime, timedelta, timezone

        # 1. Fetch the bet with all relationships
        bet_query = """
        MATCH (b:Bet {name: $name})
        OPTIONAL MATCH (b)-[:DEPENDS_ON]->(c:Capability)
        OPTIONAL MATCH (idea:Idea)-[:PLACES]->(b)
        OPTIONAL MATCH (vm:Milestone)-[v:VALIDATES]->(b)
        OPTIONAL MATCH (im)-[inv:INVALIDATES]->(b)
        RETURN b.name AS name, b.description AS description,
               b.placed_date AS placed_date, b.result AS result,
               collect(DISTINCT {name: c.name, description: c.description}) AS capabilities,
               collect(DISTINCT {name: idea.name, description: idea.description,
                                 argument: idea.argument, assumptions: idea.assumptions,
                                 counterargument: idea.counterargument}) AS ideas,
               collect(DISTINCT {milestone: vm.name, date: v.date, desc: vm.description}) AS validations,
               collect(DISTINCT {source: COALESCE(im.name, labels(im)[0]), date: inv.date}) AS invalidations
        """
        async with driver.session() as session:
            result = await session.run(bet_query, {"name": req.bet_name})
            bet_data = await result.data()

        if not bet_data:
            raise HTTPException(status_code=404, detail="Bet not found")

        bet = neo4j_to_json(bet_data[0])

        # 2. Get milestone timeline for dependent capabilities
        cap_names = [c["name"] for c in bet.get("capabilities", []) if c.get("name")]
        milestones = []
        if cap_names:
            ms_query = """
            MATCH (c:Capability)-[:HAS_MILESTONE]->(m:Milestone)
            WHERE c.name IN $caps
            OPTIONAL MATCH (ptc:PTC)-[:REACHES]->(m)
            RETURN DISTINCT m.name AS name, m.description AS description,
                   m.milestone_reached_date AS date, c.name AS capability,
                   collect(DISTINCT ptc.name) AS reached_by
            ORDER BY m.milestone_reached_date
            """
            async with driver.session() as session:
                result = await session.run(ms_query, {"caps": cap_names})
                ms_data = await result.data()
            milestones = neo4j_to_json(ms_data)

        # 3. Find potentially contradicting ideas/bets in the same space
        contradict_query = """
        MATCH (b:Bet {name: $name})-[:DEPENDS_ON]->(c:Capability)<-[:DEPENDS_ON]-(other:Bet)
        WHERE other.name <> $name
        RETURN DISTINCT other.name AS name, other.description AS description,
               other.placed_date AS placed_date, other.result AS result
        LIMIT 10
        """
        async with driver.session() as session:
            result = await session.run(contradict_query, {"name": req.bet_name})
            related_bets_data = await result.data()
        related_bets = neo4j_to_json(related_bets_data)

        # 4. Build comprehensive context string
        kg_str = f"**Bet**: {bet['name']}\n**Description**: {bet.get('description', 'N/A')}\n"
        if bet.get('placed_date'):
            kg_str += f"**Placed date**: {bet['placed_date']}\n"
        if bet.get('result'):
            kg_str += f"**Current result**: {bet['result']}\n"

        # Dependent capabilities
        if cap_names:
            kg_str += f"\n**Depends on capabilities**: {', '.join(cap_names)}\n"

        # Parent ideas with their arguments
        ideas = [i for i in bet.get("ideas", []) if i.get("name")]
        if ideas:
            kg_str += "\n**Parent Ideas/Assessments**:\n"
            for idea in ideas:
                kg_str += f"- **{idea['name']}**: {idea.get('description', '')[:300]}\n"
                if idea.get('argument'):
                    kg_str += f"  Argument: {idea['argument'][:200]}\n"
                if idea.get('assumptions'):
                    kg_str += f"  Assumptions: {idea['assumptions'][:200]}\n"
                if idea.get('counterargument'):
                    kg_str += f"  Counterargument: {idea['counterargument'][:200]}\n"

        # Existing validation/invalidation evidence
        valid = [v for v in bet.get("validations", []) if v.get("milestone")]
        invalid = [v for v in bet.get("invalidations", []) if v.get("source")]
        if valid:
            kg_str += "\n**Existing validating evidence**:\n"
            for v in valid:
                kg_str += f"- {v['milestone']}{' (' + str(v.get('date', '')) + ')' if v.get('date') else ''}\n"
        if invalid:
            kg_str += "\n**Existing invalidating evidence**:\n"
            for v in invalid:
                kg_str += f"- {v['source']}{' (' + str(v.get('date', '')) + ')' if v.get('date') else ''}\n"

        # Milestone timeline
        if milestones:
            kg_str += "\n**Milestone timeline for dependent capabilities**:\n"
            for m in milestones[:20]:
                kg_str += f"- {m.get('date', '?')}: {m['name']}"
                reached = [r for r in m.get('reached_by', []) if r]
                if reached:
                    kg_str += f" (by: {', '.join(reached[:3])})"
                kg_str += "\n"

        # Related bets (potential contradictions)
        if related_bets:
            kg_str += "\n**Other bets in the same capability space**:\n"
            for rb in related_bets:
                kg_str += f"- {rb['name']}: {rb.get('description', '')[:200]}"
                if rb.get('result'):
                    kg_str += f" [Result: {rb['result']}]"
                kg_str += "\n"

        # 5. Send to Grok with combined evaluation prompt
        system_prompt = (
            "You are an intelligence analyst performing a comprehensive evaluation of a strategic bet. "
            "You have access to a knowledge graph and can search the web and X for the latest developments. "
            "Your evaluation must cover ALL of the following dimensions:\n\n"
            "Structure your response in exactly these sections using markdown:\n\n"
            "## 📊 Current Evidence\n"
            "What does the latest data say? Search the web and X for recent developments related to "
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

        now = datetime.now(timezone.utc)
        from_date = now - timedelta(hours=168)  # 7 days lookback

        tools = [
            web_search(excluded_domains=["wikipedia.org", "gartner.com", "weforum.com", "forbes.com", "accenture.com"]),
            x_search(from_date=from_date, to_date=now),
        ]

        user_prompt = (
            f"Evaluate this strategic bet:\n\n{kg_str}\n\n"
            f"EmTech sector: {req.emtech}\n\n"
            f"Search the web and X for the latest developments relevant to this bet's thesis. "
            f"Then provide your comprehensive evaluation covering all five dimensions."
        )

        xai_client = AsyncClient(api_key=XAI_API_KEY, timeout=180)
        chat = xai_client.chat.create(
            model="grok-4-1-fast",
            tools=tools,
            messages=[
                system(system_prompt),
                user(user_prompt),
            ],
        )

        response = await chat.sample()
        return {"content": response.content, "bet_name": req.bet_name, "emtech": req.emtech}

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
