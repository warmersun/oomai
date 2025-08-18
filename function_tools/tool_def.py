with open("knowledge_graph/cypher.cfg", "r") as f:
    CYPHER_CFG = f.read()


TOOLS_DEFINITIONS = {
    "execute_cypher_query": {
        "type": "custom",
        "name": "execute_cypher_query",
        "description": """
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
        "format": {
            "type": "grammar",
            "syntax": "lark",
            "definition": CYPHER_CFG,
        }
    },
    "create_node": {
        "type": "function",
        "name": "create_node",
        "description": """
        Creates or updates a node in the Neo4j knowledge graph, ensuring no duplicates by checking for similar nodes based on their descriptions.
        If a similar node exists, it updates the node with a merged description. If not, it creates a new node.
        Returns the node's name ( which is guaranteed to be a unique string identifier).
        Use this tool to add or update nodes like technologies, capabilities, or parties in the graph.
        Provide the node type, a short name, and a detailed description.
        """,
        "parameters": {
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
    },
    "create_edge": {
        "type": "function",
        "name": "create_edge",
        "description": """
        Creates or merges a directed relationship (edge) between two existing nodes in the Neo4j knowledge graph.
        If the relationship doesn't exist, it creates it; if it does, it matches the existing one.
        Use this tool to connect nodes, such as linking an emerging technology to a capability it enables.
        Provide the source and target node names, the relationship type, and optional properties for the edge.
        Returns the relationship object.
        """,
        "parameters": {
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
            "required": ["source_id", "target_id", "relationship_type"],
        },
    },
    "find_node": {
        "type": "function",
        "name": "find_node",
        "description": """
        Finds nodes in knowledge graph that are similar to a given query text.
        Uses vector similarity search based on node descriptions.
        Returns a list of nodes with their names, descriptions, and similarity scores.
        """,
        "parameters": {
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
                    "description": "The number of top results to return (default is 5).",
                    "default": 5,
                },
            },
            "required": ["query_text", "node_type"],
        },
    },
    "x_search": {
        "type": "function",
        "name": "x_search",
        "description": """
        Search on X and return a detailed summary.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The search prompt.",
                },
                "included_handles": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "maxItems": 10  # Limit the array to a maximum of 10 handles,
                    },
                    "description": "Optional list of included X handles, limited to 10.",
                },
                "last_24hrs": {
                    "type": "boolean",
                    "description": "Optional flag to search only in the last 24 hours.",
                }
            },
            "required": ["prompt"]
        },
    },
    "plan_tasks": {
        "type": "function",
        "name": "plan_tasks",
        "description": """
        Completely rewrites the list of planned tasks, preserving done tasks.
        Done tasks remain unchanged and are not altered.
        The TaskList will show both DONE and planned tasks.
        """,
        "parameters": {
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
    },
    "get_tasks": {
        "type": "function",
        "name": "get_tasks",
        "description": """
         Returns a dictionary with two lists: tasks that are done and planned tasks.
        Planned tasks include those in READY, RUNNING, FAILED, etc., but not DONE.
        """,
        "parameters": {
            "type": "object",
            "properties": {},
        }
    },
    "mark_task_as_running": {
        "type": "function",
        "name": "mark_task_as_running",
        "description": """
        Marks a task as done by updating its status to DONE, only if it's not already done.
        Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {
                    "type": "string",
                },
            },
            "required": ["task_title"]
        },
    },
    "mark_task_as_done": {
        "type": "function",
        "name": "mark_task_as_done",
        "description": """
        Marks a task as running by updating its status to RUNNING, only if it's not done.
        Does not affect done tasks. Refreshes the TaskList, which shows both DONE and planned tasks.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "task_title": {
                    "type": "string",
                },
            },
            "required": ["task_title"]
        }
    },
}