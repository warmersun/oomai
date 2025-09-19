import os
from config import BRAVE_SEARCH_API_KEY
from typing import Optional

import chainlit as cl
import httpx

# Refer to https://api.search.brave.com/app/subscriptions/subscribe?tab=ai

@cl.step(type="tool", name="Search the Web Using Brave Search")
async def web_search_brave(query: str, freshness : Optional[str] = None) -> list:
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY
    }
    params = {
        "q": query,
        "safesearch": "strict",
        "text_decorations": 0,
        "result_filter": "news,web",
        "extra_snippets": 1
    }
    if freshness is not None:
        params["freshness"] = freshness

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        raw_brave_response = response.json()

    def filter_results(results):
        filtered_results = []
        for result in results:
            filtered_results.append({
                "title": result.get("title"),
                "url": result.get("url"),
                "age": result.get("age"),
                "extra_snippets": result.get("extra_snippets")
            })
        return filtered_results


    processed_brave_response = []
    if "web" in raw_brave_response and "results" in raw_brave_response["web"]:
        processed_brave_response.extend(filter_results(raw_brave_response["web"]["results"]))
    if "news" in raw_brave_response and "results" in raw_brave_response["news"]:
        processed_brave_response.extend(filter_results(raw_brave_response["news"]["results"]))

    return processed_brave_response

web_search_brave_tool = {
    "type": "function",
    "function": {
        "name": "web_search_brave",
        "description": "Search the Web using Brave Search API.",
        "parameters": {
          "type": "object",
          "properties": {
            "q": {
              "type": "string",
              "description": "The search query. Maximum of 400 characters and 50 words in the query. You can also optimize your search query by using  search operators. -: Returns web pages not containing the specified term neither in the title nor the body of the page. Example: to search web pages containing the keyword 'office' while avoiding results with the term 'Microsoft', type 'office -microsoft'. \"\": Returns web pages containing only exact matches to your query. Example: to find web pages about Harry Potter only containing the keywords 'order of the phoenix' in that exact order, type 'harry potter \"order of the phoenix\"'. You can use logical operators AND, OR and NOT in combination with search operators."
            },
            "freshness": {
              "type": "string",
              "description": "The freshness of the search results. Can be 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year), 'YYYY-MM-DDtoYYYY-MM-DD' (custom date range)."
            }
          },
          "required": ["q"]
        }
    }
}