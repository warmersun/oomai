# Knowledge Graph Data Resilience and Maintenance

This document outlines how the **oom.ai** application handles the inherent messiness of knowledge graph data (redundant nodes, missing edges, noisy inputs) and ensures the system remains robust.

## 1. The Challenge: "Messy Data"
Knowledge graphs populated by LLMs or automated scripts inevitably face two main data quality issues:
1.  **Redundant Nodes**: Different nodes representing the same concept (e.g., "Artificial Intelligence", "AI", "Machine Learning").
2.  **Missing or Messy Edges**: Connections that should exist but don't, or connections that are incorrect or noisy.

## 2. Current Resilience Mechanisms

### A. Preventing Redundancy: "Smart Upsert"
The application implements a **semantic deduplication** strategy at the point of data ingestion. This logic is contained in `function_tools/core_graph_ops.py` within the `core_smart_upsert` function.

-   **Process**: When creating a new node (for types like *Trend*, *Idea*, *Milestone*, *Capability*):
    1.  **Vector Search**: The system first searches for existing nodes with similar description embeddings.
    2.  **LLM Verification**: It uses a reasoning model (GPT-4 class) to compare the new candidate node with the top retrieved existing nodes.
    3.  **Merge Decision**: The LLM decides if they are semantically identical.
        -   **If YES**: It merges them, updating the existing node's description to be a comprehensive synthesis of both, and adopts the better name.
        -   **If NO**: It creates a new node.
-   **Impact**: This actively prevents the creation of duplicate nodes that have different names but the same meaning.

### B. Handling Missing Edges: "Vector-First Retrieval"
The application's retrieval strategy is designed to be resilient to missing edges. It does *not* rely solely on hard graph traversals (like walking strictly from node A to node B), which would fail if a single link is missing.

-   **Process**: Retrieval tools like `find_node`, `scan_ideas`, and `scan_trends` use **Vector Similarity Search**.
-   **Impact**: Even if a node is completely disconnected (an "island") or locally isolated due to missing edges, the system can still find it if its description is semantically relevant to the user's query.
-   **Inference**: The LLM then uses this retrieved context to answer the question, effectively "inferring" the missing connection at runtime by synthesizing information from disjointed but relevant nodes.

### C. Error Tolerance
-   **Batch Processing**: The `batch.py` script is designed to catch and log errors (such as failed edge creations due to missing endpoints) rather than crashing the entire process. This ensures that a few bad data points do not stop the ingestion pipeline.
-   **Database Constraints**: Uniqueness constraints (defined in `unique_names.cypher`) enforce that no two nodes of the same label can have the exact same name property, acting as a final hard gate against duplicates.

## 3. Maintenance and Future Solutions

To further improve data quality beyond these automated resilience mechanisms, the following strategies can be employed:

1.  **Periodic Cleanup**:
    -   Run background scripts to scan for potential duplicates that might have been missed by the ingestion logic (e.g., using stricter thresholds or different embedding models).
    -   Identify "orphan" nodes (nodes with 0 relationships) and flagging them for review or auto-linking.

2.  **Link Prediction**:
    -   Use the **Convergence Canvas** or similar graph algorithms to suggest likely missing edges based on the proximity of nodes in the vector space or shared neighbors.
