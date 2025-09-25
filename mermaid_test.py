import chainlit as cl

# Test cases for valid MermaidJS diagrams
VALID_DIAGRAMS = {
    "Basic Flowchart": """
graph TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Option 1]
    B -->|No| D[Option 2]
    C --> E[End]
    D --> E[End]
    """,
    
    "Sequence Diagram": """
sequenceDiagram
    participant A as Alice
    participant B as Bob
    A->>B: Hello Bob, how are you?
    B-->>A: Great!
    A-)B: See you later!
    """,
    
    "Class Diagram": """
classDiagram
    class Animal {
        +String name
        +int age
        +makeSound()
    }
    class Dog {
        +String breed
        +bark()
    }
    Animal <|-- Dog
    """,
    
    "State Diagram": """
stateDiagram-v2
    [*] --> Still
    Still --> [*]
    Still --> Moving
    Moving --> Still
    Moving --> Crash
    Crash --> [*]
    """,
    
    "Gantt Chart": """
gantt
    title A Gantt Diagram
    dateFormat  YYYY-MM-DD
    section Section
    A task           :a1, 2014-01-01, 30d
    Another task     :after a1  , 20d
    """,
    
    "Pie Chart": """
pie title Pets adopted by volunteers
    "Dogs" : 386
    "Cats" : 85
    "Rats" : 15
    """,
    
    "Git Graph": """
gitgraph
    commit
    branch develop
    checkout develop
    commit
    commit
    checkout main
    merge develop
    commit
    """,
    
    "User Journey": """
journey
    title My working day
    section Go to work
      Make tea: 5: Me
      Go upstairs: 3: Me
      Do work: 1: Me, Cat
    section Go home
      Go downstairs: 5: Me
      Sit down: 5: Me
    """,
    
    "Mind Map": """
mindmap
  root((mindmap))
    (A)
      (B)
        (C)
        (D)
      (E)
        (F)
        (G)
    (H)
      (I)
        (J)
        (K)
      (L)
        (M)
        (N)
    """,
    
    "Timeline": """
timeline
    title History of Social Media Platform
    2002 : LinkedIn
    2003 : MySpace
    2004 : Facebook
         : Google
    2005 : Youtube
    2006 : Twitter
    """
}

# Test cases for invalid MermaidJS diagrams
INVALID_DIAGRAMS = {
    "Empty Diagram": "",
    
    "Missing Direction": """
graph
    A --> B
    """,
    
    "Incomplete Flowchart": """
flowchart
    A --> B
    """,
    
    "Unmatched Brackets": """
graph TD
    A[Start --> B{Decision}
    B -->|Yes| C[Option 1]
    """,
    
    "Unmatched Parentheses": """
graph TD
    A(Start --> B{Decision}
    B -->|Yes| C(Option 1)
    """,
    
    "Invalid Diagram Type": """
invalidDiagram
    A --> B
    """,
    
    "Incomplete Sequence Diagram": """
sequenceDiagram
    participant A as Alice
    """,
    
    "Incomplete Class Diagram": """
classDiagram
    class Animal {
        +String name
    """,
    
    "Incomplete State Diagram": """
stateDiagram-v2
    [*] --> Still
    """,
    
    "Incomplete Gantt": """
gantt
    title A Gantt Diagram
    """,
    
    "Incomplete Pie Chart": """
pie title Pets adopted by volunteers
    """,
    
    "Incomplete Git Graph": """
gitgraph
    commit
    """,
    
    "Incomplete Journey": """
journey
    title My working day
    """,
    
    "Incomplete Mind Map": """
mindmap
  root((mindmap))
    """,
    
    "Incomplete Timeline": """
timeline
    title History of Social Media Platform
    """,
    
    "Syntax Error": """
graph TD
    A[Start] --> B{Decision
    B -->|Yes| C[Option 1]
    """,
    
    "Invalid Characters": """
graph TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Option 1] @#$%
    """,
    
    "Null Input": None,
    
    "Non-String Input": 12345
}

@cl.on_chat_start
async def on_start():
    await cl.Message(
        content="# MermaidJS Test Suite\n\nThis test suite demonstrates the improved error handling in the MermaidDiagram component with both valid and invalid diagram examples.",
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    if message.content.lower() == "test valid":
        await test_valid_diagrams()
    elif message.content.lower() == "test invalid":
        await test_invalid_diagrams()
    elif message.content.lower() == "test all":
        await test_valid_diagrams()
        await test_invalid_diagrams()
    elif message.content.lower() == "help":
        await show_help()
    else:
        await cl.Message(
            content="Available commands:\n- `test valid` - Test valid MermaidJS diagrams\n- `test invalid` - Test invalid MermaidJS diagrams\n- `test all` - Test both valid and invalid diagrams\n- `help` - Show this help message"
        ).send()

async def test_valid_diagrams():
    await cl.Message(
        content="## ✅ Testing Valid MermaidJS Diagrams\n\nThese should render successfully:"
    ).send()
    
    for name, diagram in VALID_DIAGRAMS.items():
        mermaid_element = cl.CustomElement(
            name="MermaidDiagram",
            props={"diagram": diagram},
            display="inline"
        )
        
        await cl.Message(
            content=f"**{name}:**",
            elements=[mermaid_element]
        ).send()

async def test_invalid_diagrams():
    await cl.Message(
        content="## ❌ Testing Invalid MermaidJS Diagrams\n\nThese should show error messages with helpful tips:"
    ).send()
    
    for name, diagram in INVALID_DIAGRAMS.items():
        mermaid_element = cl.CustomElement(
            name="MermaidDiagram",
            props={"diagram": diagram},
            display="inline"
        )
        
        await cl.Message(
            content=f"**{name}:**",
            elements=[mermaid_element]
        ).send()

async def show_help():
    await cl.Message(
        content="""# MermaidJS Test Suite Help

## Available Commands:
- `test valid` - Test 10 different types of valid MermaidJS diagrams
- `test invalid` - Test 15 different types of invalid MermaidJS diagrams  
- `test all` - Run both valid and invalid tests
- `help` - Show this help message

## Valid Diagram Types Tested:
1. Basic Flowchart
2. Sequence Diagram
3. Class Diagram
4. State Diagram
5. Gantt Chart
6. Pie Chart
7. Git Graph
8. User Journey
9. Mind Map
10. Timeline

## Invalid Diagram Types Tested:
1. Empty Diagram
2. Missing Direction
3. Incomplete Flowchart
4. Unmatched Brackets
5. Unmatched Parentheses
6. Invalid Diagram Type
7. Incomplete Sequence Diagram
8. Incomplete Class Diagram
9. Incomplete State Diagram
10. Incomplete Gantt
11. Incomplete Pie Chart
12. Incomplete Git Graph
13. Incomplete Journey
14. Incomplete Mind Map
15. Incomplete Timeline
16. Syntax Error
17. Invalid Characters
18. Null Input
19. Non-String Input

## Error Handling Features:
- ✅ Pre-render syntax validation
- ✅ Specific error messages
- ✅ Helpful tips and suggestions
- ✅ Retry functionality
- ✅ Loading states
- ✅ Graceful fallbacks

Type any command to start testing!"""
    ).send()