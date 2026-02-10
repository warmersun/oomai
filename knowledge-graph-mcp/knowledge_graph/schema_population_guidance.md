##### Objectives

The purpose of this knowledge graph is to build context that enables better questions, not to store facts. Factual information will be retrieved via web search when needed.

Focus on capturing context and relationships that help formulate better questions. Do not store easily searchable facts—web search will handle lookups.

##### Entity specific rules

###### EmTech

Emerging technologies are the foundation of this knowledge graph. The taxonomy is fixed.

Do not create new EmTechs. Use only those defined in the taxonomy.

###### Convergence

Always associate with at least two EmTechs.

###### Capability

Carefully check if the capability already exists, and if so, use it. Think of capabilities as a spectrum, as a grey scale. A capability advances and this can be measured with some unit of measure e.g. context window size for LLMs is measured in tokens.
Capabilities are important to track because web search and users fail to clearly articulate the full list of capabilities.
As emerging technologies advance exponentially, new capabilities emerge and these are very hard to predict so they are of high interest,

###### Milestone

Think of milestones as black or white. A milestone is reached when the capability reaches a certain threshold in that unit of measure and this can be used to unlock new applications. 
Always capture new milestones along with the new use cases that they enable; and relate back to the capability that enabled it.

###### LTC

Carefully check if the LTC already exists, and if so, use it. You will only rarely need to create a new LTC.
Try to find the one from the existing ones using 'find_node`.
Only create new LTC when you discover a new logical category of products or services that is substantially different from existing ones.

###### PTC

Make sure you identify the right LTC for the PTC. LTCs can be nested, make sure you create the LTC at the right level of abstraction, the lower in the hierarchy, the more specific the LTC is the better.
The goal is not to describe each product in detail, as this information can be easily looked up with web search.
The right level of detail is to focus on trends, milestones, exponential progress and show which new product is the first to reach a certain milestone.

###### LAC

When you identify a new use case carefully pick the right LTC for it by looking at the capabilities of interest. Also identify the milestones that enable this use case i.e. how mature does the capability need to be for this use case to be possible.
Use cases are very valuable data because otherwise they are difficult to gather with web search. 
BEfore you add a new LAC, check if a similar one already exists. Do this in addition to thede-duplication built in to `create_node`.

###### PAC

You will rarely need to create a PAC. A PAC is a specific application, implementation, or solution built that is of interest e.g. a success story, case study or a remarkable project.

###### Trend

Includes both looking back at how a capability has evolved through milestones and making predictions about where it is headed.
Trends are similar to ideas, but they relate to capabilities and milestones.
Trends are important to build context, to ask questions one would not think to ask otherwise, therefore focus on capturing trends.
Trends can be spotted by others, or by yourself. When spotted by others, give credit to these thought leaders by relating a Party node.

###### Idea

Use to describe ideas, policies, warnings, predictions, personal assessments, and evaluations.
Ideas are the primary vehicle for storing personal judgment — things that exist in the user's head and nowhere on the internet.
When the user shares an assessment or opinion, always capture it as an Idea and relate it to the relevant concepts.
Use the optional `argument`, `assumptions`, and `counterargument` properties when the user provides their reasoning — this preserves the chain of thought and enables the system to re-evaluate positions when new information arrives.
Ideas can relate to other ideas.
Ideas are the most important nodes to build context, to ask questions one would not think to ask otherwise, therefore focus on capturing ideas.

###### Bet

A bet is a strategic position the user is actively tracking. It's a prediction with skin in the game.
The description must include: (1) the core thesis, (2) what signals would validate it, (3) what signals would invalidate it, and (4) known blindspots.
Always link bets to the Capabilities and Milestones they depend on using DEPENDS_ON edges.
When new information validates or invalidates a bet, create VALIDATES or INVALIDATES edges from the relevant Milestone or Idea.
Before creating a new Bet, check if a similar one already exists using `find_node`.



###### Party

Make sure you use the full, proper name of the party. Not the legal entityt name, but also not an abbreviation.
For example, use "OpenAI" instead of "OpenAI Inc." or "OpenAI Corp.", "Elon Musk" instead of "Musk" or "Elon".
Do not capture parties solely for the purposes to give credit .e.g. when storing ideas from a research paper.