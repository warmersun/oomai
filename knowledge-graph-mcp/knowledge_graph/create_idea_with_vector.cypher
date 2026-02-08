CREATE (i:Idea {name: 'My Idea', description: 'This is a detailed description.'})
WITH i
CALL genai.vector.encode(i.description, 'OpenAI', {token: 'your-openai-api-key'}) YIELD vector
CALL db.create.setNodeVectorProperty(i, 'embedding', vector)
RETURN i