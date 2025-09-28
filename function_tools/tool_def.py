from xai_sdk.chat import tool

with open("knowledge_graph/cypher.cfg", "r") as f:
    CYPHER_CFG = f.read()


TOOLS_DEFINITIONS = {
    "execute_cypher_query": tool(
        name="execute_cypher_query",
        description="""
        Executes a read-only Cypher query against a Neo4j database.
        Only supports safe, query-only operations: MATCH, OPTIONAL MATCH, UNWIND, WITH, RETURN, UNION.
        No data modification (e.g., no CREATE, MERGE, SET, DELETE, CALL procedures, or unsafe APOC procedures).
        Use patterns like (e:EmTech {name: 'artificial intelligence'})-[:ENABLES]->(c:Capability).
        Aggregations via COUNT, REDUCE; safe built-ins like elementId(), keys(), properties(), labels(), abs(), coalesce();
        allow-listed APOC functions from coll, map, text, number, date, temporal, convert, regex, math, agg (e.g., apoc.coll.sort).
        Include WHERE for filters, ORDER BY, SKIP, LIMIT for pagination.
        Returns query results as JSON-like structures (nodes, relationships, paths, values), e.g., [{"node": {"id": "123", "labels": ["EmTech"], "properties": {"name": "AI"}}}, ...].
        Generate queries that strictly match this subset to ensure execution; invalid queries will error.

        IMPORTANT GUIDELINES:
        - Always bind variables (e.g., via MATCH or UNWIND) before referencing them in WHERE, RETURN, or functions.
        - Use separate identifiers for variables and functions; do not concatenate (e.g., avoid 'collectDistinctCOALESCE'; use coalesce(...) instead).
        - Ensure expressions are valid (e.g., apoc functions take correct arguments like lists).
        - For aggregations, use WITH if needed to group results.
        - Do not reference unbound variables; this causes runtime errors.
        - Avoid complex nesting unless necessary; keep queries linear.
        - Respect the schema: Use exact node labels (e.g., EmTech, Capability, Milestone) and edge types (e.g., ENABLES, HAS_MILESTONE). All nodes have 'name' and 'description'. Do not create new EmTech nodes; use the taxonomy list.
        - For semantic search, use vector indices on nodes like Capability, Milestone with embedding properties.

        EXAMPLES OF VALID QUERIES:
        1. Simple match: MATCH (e:EmTech {name: 'artificial intelligence'}) RETURN e.name AS name, labels(e) AS labels, e.description AS desc
        2. With optional and aggregation: MATCH (c:Capability {name: 'Context Retention in Dialogs'}) OPTIONAL MATCH (c)-[:HAS_MILESTONE]->(m:Milestone) WITH c, m WHERE m.milestone_reached_date IS NOT NULL RETURN c.name AS cap, count(m) AS numMilestones
        3. Using APOC: MATCH (t:Trend) RETURN apoc.coll.sort(keys(t)) AS sortedProperties LIMIT 10
        4. With WHERE and ORDER: MATCH (p:PTC)-[:REACHES]->(m:Milestone) WHERE p.name CONTAINS 'OpenAI' RETURN p.name AS product, m.name AS milestone ORDER BY m.milestone_reached_date DESC SKIP 0 LIMIT 5

        EXAMPLES OF INVALID QUERIES (AVOID THESE):
        1. Unbound variable: RETURN unboundVar (error: variable not defined).
        2. Disallowed operation: CREATE (e:EmTech {name: 'New Tech'}) (error: mutation not allowed; EmTechs are fixed).
        3. Unsafe function: CALL apoc.do.it() (error: not allow-listed).
        """,
        parameters= {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A read-only Cypher query string to execute against the Neo4j database, following the allowed subset and guidelines."
                }
            },
            "required": ["query"]
        }
    ),
    "create_node": tool(
        name="create_node",
        description="""
        Creates or updates a node in the Neo4j knowledge graph, ensuring no duplicates by checking for similar nodes based on their descriptions.
        If a similar node exists, it updates the node with a merged description. If not, it creates a new node.
        Returns the node's name ( which is guaranteed to be a unique string identifier and may be different from the provided name).
        Use this tool to add or update nodes like technologies, capabilities, or parties in the graph.
        Provide the node type, a short name, and a detailed description.
        """,
        parameters={
            "type": "object",
            "properties": {
                "node_type": {
                    "type": "string",
                    "description": "The type of node (e.g., 'EmTech', 'Capability', 'Party').",
                },
                "name": {
                    "type": "string",
                    "description": "A short, unique name for the node (e.g., 'AI', 'OpenAI').",
                },
                "description": {
                    "type": "string",
                    "description": "A detailed description of the node for similarity checks and updates.",
                },
            },
            "required": ["node_type", "name", "description"],
        }
    ),
    "create_edge": tool(
        name="create_edge",
        description="""
        Creates or merges a directed relationship (edge) between two existing nodes in the Neo4j knowledge graph.
        If the relationship doesn't exist, it creates it; if it does, it matches the existing one.
        Use this tool to connect nodes, such as linking an emerging technology to a capability it enables.
        Provide the source and target node names, the relationship type, and optional properties for the edge.
        Returns the relationship object.
        """,
        parameters={
            "type": "object",
            "properties": {
                "source_name": {
                    "type": "string",
                    "description": "The name of the source node.",
                },
                "target_name": {
                    "type": "string",
                    "description": "The name of the target node.",
                },
                "relationship_type": {
                    "type": "string",
                    "description": "The type of relationship (e.g., 'ENABLES', 'USES', 'RELATES_TO').",
                },
                "properties": {
                    "type": "object",
                    "description": "Optional additional properties for the relationship (e.g., {'explanation': 'details'}).",
                    "additionalProperties": True,
                },
            },
            "required": ["source_name", "target_name", "relationship_type"],
        },
    ),
    "find_node": tool(
        name="find_node",
        description="""
        Finds nodes in knowledge graph that are similar to a given query text.
        Uses vector similarity search based on node descriptions.
        Returns a list of nodes with their names, descriptions, and similarity scores.
        """,
        parameters={
            "type": "object",
            "properties": {
                "query_text": {
                    "type": "string",
                    "description": "The text to search for similar nodes.",
                },
                "node_type": {
                    "type": "string",
                    "description": "The type of node to search for.",
                    "enum": ["Convergence", "Capability", "Milestone", "Trend", "Idea", "LTC", "LAC"],
                },
                "top_k": {
                    "type": "integer",
                    "description": "The number of top results to return (default is 25).",
                    "default": 25,
                },
            },
            "required": ["query_text", "node_type"],
        },
    ),
    "plan_tasks": tool(
        name="plan_tasks",
        description="""
        Completely rewrites the list of planned tasks, preserving done tasks.
        Done tasks remain unchanged and are not altered.
        The TaskList will show both DONE and planned tasks.
        """,
        parameters={
            "type": "object",
            "properties": {
                "planned_tasks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": "The list of planned tasks.",
                },
            },
            "required": ["planned_tasks"]
        }
    ),
    "get_tasks": tool(
        name="get_tasks",
        description="""
         Returns a dictionary with two lists: tasks that are done and planned tasks.
        Planned tasks include those in READY, RUNNING, FAILED, etc., but not DONE.
        This function takes no input parameter.
        """,
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    "mark_task_as_running": tool(
        name="mark_task_as_running",
        description="""
        Marks a task as done by updating its status to DONE, only if it's not already done.
        Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
        """,
        parameters={
            "type": "object",
            "properties": {
                "task_title": {
                    "type": "string",
                },
            },
            "required": ["task_title"]
        },
    ),
    "mark_task_as_done": tool(
        name="mark_task_as_done",
        description="""
        Marks a task as running by updating its status to RUNNING, only if it's not done.
        Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
        """,
        parameters={
            "type": "object",
            "properties": {
                "task_title": {
                    "type": "string",
                },
            },
            "required": ["task_title"]
        }
    ),
    "display_mermaid_diagram": tool(
        name="display_mermaid_diagram",
        description="""
        Displays a MermaidJS diagram.  
        Use MermaidJS flowchart syntax to visualize nodes and edges in the knowledge graph, or use the timeline syntax to show milestones and their progression over time.
        """,
        parameters={
            "type": "object",
            "properties": {
                "diagram_str": {
                    "type": "string",
                    "description": "The Mermaid diagram string to display.",
                },
            },
            "required": ["diagram_str"]
        }
    ),
    "display_convergence_canvas": tool(
        name="display_convergence_canvas",
        description="""
        Displays a Convergence Canvas visualization—a visual tool to describe, assess, and create Pathways that build off the *convergence* of multiple emerging technologies.

        ---
        **Convergence Canvas** helps you map out how different emerging technologies (emTechs) interact to enable new solutions. It distinguishes between the digital world of information ("bits") and the real, physical world ("atoms"), showing how technologies operate within and between these realms.

        - **Technology**: Anything that takes something scarce and makes it abundant (e.g., speech, clothing, computing, 3D printing).
        - **Emerging Technology (emTech)**: Technologies that, once information-based, progress exponentially (e.g., AI, robotics, synthetic biology).
        - **Counterparts**: Some emTechs have digital and physical analogs (e.g., transportation ↔ networking, AI ↔ robotics, energy ↔ computing).
        - **emTechs in Both Worlds**: Some technologies bridge both realms (e.g., IoT and sensors as portals, 3D printing turning digital into physical, synthetic biology, AR/VR, and crypto).
        - **Convergence**: The interplay where advances in one emTech accelerate another, enabling new Pathways.
            - *Weak convergence*: Using multiple emTechs together to build something new.
            - *Strong convergence*: Using one emTech to advance another, unlocking new possibilities.
        - **Pathway**: A trajectory or approach (not just a solution) enabled by the convergence of emTechs.

        The Convergence Canvas provides a structured way to visualize and discuss these relationships, helping you design and communicate innovative Pathways that address real-world problems—most of which ultimately require solutions in the physical world.
        """,
        parameters={
            "type": "object",
            "properties": {
                "json_str": {
                    "type": "string",
                    "description": """
                    JSON-encoded string that must represent a single JSON object.
                    - Keys: Emerging-technology identifiers from the allowed list:
                    - "ai"
                    - "arvr"
                    - "computing"
                    - "crypto"
                    - "energy"
                    - "iot"
                    - "networks"
                    - "robot"
                    - "synbio"
                    - "threeDprinting"
                    - "transportation"
                    - Values: Plain-text descriptions explaining each selected technology's role in the solution.

                    Example (must be stringified before passing):

                    {
                    "robot": "Robots for automated assembly tasks.",
                    "ai": "AI algorithms for real-time quality control."
                    }
                    """,
                },
            },
            "required": ["json_str"]
        },

    ),
    "visualize_oom": tool(
        name="visualize_oom",
        description="""
        Displays a OOM Visualizer, an interactive tool to visualize exponential growth of a technology over time.
        It shows the number of doublings needed to reach different orders of magnitude (OOM) developments: 10X, 100X, 1000X 
        and, based on the compounding rate, calculates how long it will take to reach each OOM.
        """,
        parameters={
            "type": "object",
            "properties": {
                "months_per_doubling": {
                    "type": "integer",
                    "description": "The number of months per doubling.",
                },
            },
            "required": ["months_per_doubling"]
        }
    ),
    "x_search": tool(
        name="x_search",
        description="""
        Searches on X and on the web.
        """,
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt to search on X.",
                },
                "included_handles": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "A Twitter/X handle to include in the search."
                    },
                    "description": "A list of Twitter/X handles (as strings) to search on X.",
                    "default": [],
                },
                "last_24hrs": {
                    "type": "boolean",
                    "description": "Whether to search on X for the last 24 hours.",
                    "default": False,
                },
                "system_prompt": {
                    "type": "string",
                    "description": "The system prompt to use for the search.",
                    "default": "Search on X and return a detailed summary.",
                },
            },
            "required": ["prompt"]
        }
    ),
}