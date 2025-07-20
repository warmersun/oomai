CALL genai.vector.encode('Search for similar ideas about innovation.', 'OpenAI', {token: 'your-openai-api-key'}) YIELD vector

CALL db.index.vector.queryNodes('idea_description_embeddings', 100, vector)  // Use a large topK, e.g., 100
YIELD node, score

WHERE score >= 0.8  // Your similarity threshold

RETURN node.name, node.description, score
ORDER BY score DESC
LIMIT 100  // Optional: Cap results if needed, after filtering