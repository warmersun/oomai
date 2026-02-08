CREATE CONSTRAINT unique_emtech_name IF NOT EXISTS FOR (e:EmTech) REQUIRE e.name IS UNIQUE;

MERGE (computing:EmTech { 
  name: "computing", 
  description: "Works in the digital domain, analogous to energy and power in the physical realm." 
})
MERGE (energy:EmTech { 
  name: "energy", 
  description: "Provides power in the real world from renewable sources and advanced battery technologies." 
})
MERGE (crypto:EmTech { 
  name: "crypto-currency", 
  description: "Blockchain and distributed ledger technologies that primarily exist in the digital realm while impacting finance in the real world." 
})
MERGE (ai:EmTech { 
  name: "artificial intelligence", 
  description: "Automates the processing of information in the digital world using algorithms and data." 
})
MERGE (robots:EmTech { 
  name: "robots", 
  description: "Machines with a physical presence that automate tasks in the real world." 
})
MERGE (networks:EmTech { 
  name: "networks", 
  description: "Systems of communication that move information through various media in 3D space." 
})
MERGE (transportation:EmTech { 
  name: "transportation", 
  description: "Moves people or cargo in the real world through various innovative modes." 
})
MERGE (_3dprinting:EmTech { 
  name: "3D printing", 
  description: "Manufacturing starts from the imagined digital information and makes it real in the world of atoms." 
})
MERGE (iot:EmTech { 
  name: "internet of things", 
  description: "At its core, IOT is about sensing: measuring and capturing the real world so it becomes computable information." 
})
MERGE (vr:EmTech { 
  name: "virtual reality", 
  description: "Virtual, augmented and mixed reality create a link between the real and the imagined digital world." 
})
MERGE (synbio:EmTech { 
  name: "synthetic biology", 
  description: "Gene sequencing goes from the real world to the world of bits: the genetic information encoded in the DNA becomes digital. Genetic engineering goes the other way: a synthetic life-form or a genetically modified organism becomes a real." 
})

MERGE (qc:EmTech { 
  name: "quantum computing", 
  description: "Leverages quantum mechanics to perform complex and high-speed computations." 
})
MERGE (qc)-[:DECOMPOSES]->(computing)
MERGE (bci:EmTech { 
  name: "brain-computer interface", 
  description: "Facilitates direct communication between the brain and external devices." 
})
MERGE (bci)-[:DECOMPOSES]->(computing)

MERGE (solar:EmTech { 
  name: "solar power", 
  description: "Energy harnessed directly from the sun’s rays." 
})
MERGE (solar)-[:DECOMPOSES]->(energy)
MERGE (wind:EmTech { 
  name: "wind power", 
  description: "Energy generated through wind turbines converting kinetic energy." 
})
MERGE (wind)-[:DECOMPOSES]->(energy)
MERGE (geothermal:EmTech { 
  name: "geothermal power", 
  description: "Energy obtained from the natural heat of the Earth." 
})
MERGE (geothermal)-[:DECOMPOSES]->(energy)
MERGE (tidal:EmTech { 
  name: "tidal power", 
  description: "Energy captured from the movement of tides or ocean waves." 
})
MERGE (tidal)-[:DECOMPOSES]->(energy)
MERGE (wave:EmTech { 
  name: "wave power", 
  description: "Energy captured from the movement of ocean waves." 
})
MERGE (wave)-[:DECOMPOSES]->(energy)
MERGE (battery:EmTech { 
  name: "battery technology", 
  description: "Technologies focused on storing and managing energy efficiently." 
})
MERGE (battery)-[:DECOMPOSES]->(energy)
MERGE (nuclear:EmTech { 
  name: "nuclear power", 
  description: "Nuclear power." 
})
MERGE (nuclear)-[:DECOMPOSES]->(energy)

MERGE (qi:EmTech { 
  name: "quantum internet", 
  description: "An emerging technology that uses quantum signals for ultra-secure communication." 
})
MERGE (qi)-[:DECOMPOSES]->(computing)
MERGE (qi)-[:DECOMPOSES]->(networks)

MERGE (self_driving:EmTech { 
  name: "self-driving cars", 
  description: "Vehicles that operate autonomously without human intervention." 
})
MERGE (self_driving)-[:DECOMPOSES]->(transportation)
MERGE (self_driving)-[:DECOMPOSES]->(robots)
MERGE (self_driving)-[:DECOMPOSES]->(ai)
MERGE (drones:EmTech { 
  name: "drones", 
  description: "Unmanned aerial vehicles used for delivery, surveillance, and transport." 
})
MERGE (drones)-[:DECOMPOSES]->(transportation)
MERGE (drones)-[:DECOMPOSES]->(ai)
MERGE (drones)-[:DECOMPOSES]->(battery)
MERGE (drones)-[:DECOMPOSES]->(iot)
MERGE (space:EmTech { 
  name: "space exploration", 
  description: "The use of advanced technology to explore and study outer space." 
})
MERGE (space)-[:DECOMPOSES]->(transportation)

MERGE (material_science:EmTech { 
  name: "material science", 
  description: "The study and development of new materials." 
})
MERGE (material_science)-[:DECOMPOSES]->(_3dprinting)
MERGE (nanotech:EmTech { 
  name: "nano-technology", 
  description: "Atomic Precision Manufacturing." 
})
MERGE (nanotech)-[:DECOMPOSES]->(_3dprinting)

MERGE (iot)-[:DECOMPOSES]->(networks)

MERGE (gene_eng:EmTech { 
  name: "genetic engineering", 
  description: "Focuses on the manipulation of an organism's genetic material to create new traits." 
})
MERGE (gene_eng)-[:DECOMPOSES]->(synbio)
MERGE (gene_seq:EmTech { 
  name: "gene sequencing", 
  description: "Involves determining the order of nucleotides in DNA, converting biological information into digital data." 
})
MERGE (gene_seq)-[:DECOMPOSES]->(synbio)
MERGE (altprotein:EmTech {
  name: "alternative proteins",
  description: "Alternative protein production including plant based meat, cultered meat, vertical farming."
})
MERGE (altprotein)-[:DECOMPOSES]->(synbio)
;
