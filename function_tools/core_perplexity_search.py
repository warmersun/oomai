from perplexity import AsyncPerplexity
from perplexity import Perplexity
from perplexity.types import (
    SearchCreateResponse,
)
import logging

async def core_perplexity_search(queries: list[str], max_results: int = 5) -> str:
    """
    Perform a multi-query search using Perplexity and return a list of result structures for each query.

    Args:
        queries (list[str]): List of queries to search.
        max_results (int): Maximum number of results per query.

    Returns:
        list[list[dict]]: A list where each element is a list of result dicts for the corresponding query.
    """
    logging.info(f"[PERPLEXITY_SEARCH]:\n{queries}\nMAX RESULTS: {max_results}")
    client = AsyncPerplexity()
    search_response: SearchCreateResponse = await client.search.create(
        query=queries,
        max_results=max_results
    )
    
    return search_response.to_json()
