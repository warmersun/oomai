CREATE VECTOR INDEX idea_description_embeddings IF NOT EXISTS
FOR (i:Idea)
ON i.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}