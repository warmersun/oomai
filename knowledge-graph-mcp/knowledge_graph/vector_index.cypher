
CREATE VECTOR INDEX convergence_description_embeddings IF NOT EXISTS
FOR (n:Convergence)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
CREATE VECTOR INDEX capability_description_embeddings IF NOT EXISTS
FOR (n:Capability)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
CREATE VECTOR INDEX milestone_description_embeddings IF NOT EXISTS
FOR (n:Milestone)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
CREATE VECTOR INDEX trend_description_embeddings IF NOT EXISTS
FOR (n:Trend)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
CREATE VECTOR INDEX idea_description_embeddings IF NOT EXISTS
FOR (n:Idea)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
CREATE VECTOR INDEX ltc_description_embeddings IF NOT EXISTS
FOR (n:LTC)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
CREATE VECTOR INDEX lac_description_embeddings IF NOT EXISTS
FOR (n:LAC)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
CREATE VECTOR INDEX bet_description_embeddings IF NOT EXISTS
FOR (n:Bet)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
  }
}
;
