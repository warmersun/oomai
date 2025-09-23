import json
from neo4j.time import Date, DateTime


class Neo4jDateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (Date, DateTime)):
            return o.iso_format()  # Convert Neo4j Date/DateTime to ISO 8601 string
        return super().default(o)
