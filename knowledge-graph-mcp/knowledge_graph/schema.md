## node types:

All nodes have `name` and `description` properties.  
All `name` values are guaranteed unique identifiers.  

Name values are in Title Case:  

- the first letter of most major words is capitalized
- separated by spaces
- short glue words are lowercase, like book or article titles in English
- e.g. _"Gone With the Wind", "A Brief History of Time", "The Book of AI"_.

### EmTech
Emerging technologies, e.g., AI, robots, 3D printing.

### Convergence
Describes how advancements in one EmTech accelerate progress in another.

### Capability
What can I do with the technology that I couldn't do before? What services does it provide?

### Milestone
As a capability progresses, it reaches certain milestones; these unlock new applications.
The `milestone_reached_date` is a date type property to track when the milestone was reached - with daily, monthly or yearly granularity, to our best knowledge.

### LTC
A Logical Technology Component (LTC) is a product class—an abstract product category (e.g., Large Language Model).

### PTC
A Physical Technology Component (PTC) is a specific product by a given vendor. It can be unreleased research (e.g., X.ai's Grok-4-Fast AI model).

So "Large Language Model" is the abstract product category, the "bucket"L an LTC
and "Grok-4-Fast" is a specific instance in that product category, a PTC.

### LAC
A Logical Application Component (LAC) is an abstract group of similar applications. Use it to capture different use cases.

### PAC
A Physical Application Component (PAC) is a specific application, implementation, or solution built.

### Trend
A trend examines how some capability is progressing and makes predictions about where it is headed.

### Idea
Describes an idea, assessment, evaluation, or strategic position.
Optional properties beyond `name` and `description`:
- `argument` — the reasoning chain supporting this idea
- `assumptions` — underlying assumptions that, if wrong, change the conclusion
- `counterargument` — known objections or alternative views

### Bet
A strategic position or prediction being actively tracked.
The `description` should include: the thesis, what signals would validate or invalidate it, and known blindspots.
Properties beyond `name` and `description`:
- `placed_date` — date type, when the bet was placed
- `result` — string, evaluation of how the bet played out (filled in later when validated/invalidated)

### Party
An organization like a company, research lab, or other group; or a person.

## vector indices

Convergence, Capability, Milestone, Trend, Idea, Bet, LTC, LAC has `embedding` property with embedding vector for semantic index.

## edge types:

### DECOMPOSES
(:EmTech)-[:DECOMPOSES]->(:EmTech)
(:LTC)-[:DECOMPOSES]->(:LTC)

An emerging technology category is further decomposed into subcategories (e.g., Synthetic Biology encompasses gene sequencing and gene editing).
A product category is further decomposed into subcategories (e.g., Large Language Models has subcategories like multi-modal LLMs, coding models, etc.)

### ACCELERATES
(:EmTech)-[:ACCELERATES]->(:Convergence)

### IS_ACCELERATED_BY
(:EmTech)-[:IS_ACCELERATED_BY]->(:Convergence)

### ENABLES
(:EmTech)-[:ENABLES]->(:Capability)

An emerging technology enables a capability. Technology can be thought of as taking something that was scarce and making it abundant. Capabilities describe something we could not do before and now we can. They are usually not black and white but exist on some measurable gray scale.

### HAS_MILESTONE
(:Capability)-[:HAS_MILESTONE]->(:Milestone)

### UNLOCKS
(:Milestone)-[:UNLOCKS]->(:LAC)

### REACHES
(:PTC)-[:REACHES]->(:Milestone)

As a capability progresses, there are measurable milestones. For example, a Large Language Model has a context window. When a particular LLM, such as Google Gemini 1.5 Pro, reaches a 1M token context window, that is a milestone because it unlocks new use cases and new kinds of applications.  

(:PAC)-[:REACHES]->(:Milestone)

A specific application or implementation (PAC) can also relate to a milestone directly. For example, maybe it is the combination of multiple components how the milestone was reached.  
Events should also be modeled this way - as a pair of a PAC and a milestone that does not need relate to a specific capability.

### PREDICTS
(:Trend)-[:PREDICTS]->(:Capability)  
A trend looks at how a capability advances and makes predictions.

### LOOKS_AT
(:Trend)-[:LOOKS_AT]->(:Milestone)  
A trend looks at past milestones and can predict when we will reach new ones.

### PROVIDES
(:LTC)-[:PROVIDES]->(:Capability)  
(:PTC)-[:PROVIDES]->(:Capability)  
Products provide technical capabilities. When we talk about specific products (PTCs) or research, the `measure` property can describe the capability.  
For example, Large Language Models retain context and can conduct a dialog. That capability can be measured in specific products; for example, OpenAI's o3-mini has a 200k token context.

### IS_REALIZED_BY
(:LTC)-[:IS_REALIZED_BY]->(:PTC)  
(:LAC)-[:IS_REALIZED_BY]->(:PAC)  
Describes how abstract categories are realized by specific examples.

### MAKES
(:Party)-[:MAKES]->(:PTC)

### USES
(:LAC)-[:USES]->(:LTC)  
(:PAC)-[:USES]->(:PTC)  
Describes how we build solutions and implementations from products.

### RELATES_TO
(:Idea)-[:RELATES_TO]->()  
Ideas can relate to anything.  
RELATES_TO has an optional `explanation` property (e.g., when the Law of Accelerating Returns relates to an EmTech, the `explanation` describes why).

### PLACES
(:Idea)-[:PLACES]->(:Bet)

An idea or assessment places (gives rise to) a bet.

### DEPENDS_ON
(:Bet)-[:DEPENDS_ON]->(:Capability)
(:Bet)-[:DEPENDS_ON]->(:Milestone)

A bet depends on certain capabilities reaching certain milestones.

### VALIDATES
(:Milestone)-[:VALIDATES]->(:Bet)

When a milestone validates a bet.

### INVALIDATES
(:Milestone)-[:INVALIDATES]->(:Bet)
(:Idea)-[:INVALIDATES]->(:Bet)

When a milestone or new assessment invalidates a bet.

## taxonomy

### EmTechs:

EmTechs are reference data. Do not create new EmTech nodes!

- computing
- energy
- crypto-currency
- artificial intelligence
- robots
- networks
- transportation
- 3D printing
- internet of things
- virtual reality
- synthetic biology
- quantum computing
- geothermal power
- tidal power
- self-driving cars
- drones
- brain-computer interface
- quantum internet
- solar power
- wind power
- wave power
- nuclear power
- battery technology
- space exploration
- material science
- nano-technology
- genetic engineering
- gene sequencing
- alternative proteins
