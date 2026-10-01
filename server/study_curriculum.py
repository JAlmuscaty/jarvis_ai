"""Curriculum definitions for Jarvis's Autonomous Study Engine.

Foundational subjects plus advanced domains (CS, AI, physics, philosophy, …).
Open-world domains in OPEN_WORLD_DOMAINS push beyond fixed flashcards.
"""
from __future__ import annotations

from typing import Any

SUBJECTS: dict[str, dict[str, Any]] = {
    "daily_life": {
        "id": "daily_life",
        "title": "Daily Life & Practical Problem Solving",
        "icon": "☕",
        "description": "Daily routines, time management, conversational etiquette, cooking, home organization, and everyday practical decisions.",
        "topics": [
            {
                "name": "Daily Routines & Time Management",
                "concepts": [
                    "Morning momentum: hydrate first, natural sunlight, tackle the highest-friction task early.",
                    "Time blocking: grouping similar tasks into 45-90 minute focus blocks avoids context-switching fatigue.",
                    "The two-minute rule: if an actionable task takes less than two minutes, complete it immediately.",
                    "Evening wind-down: reducing blue light and reviewing priorities for tomorrow primes restful sleep."
                ],
                "sample_qa": [
                    {
                        "q": "How can I stop procrastinating on a big task?",
                        "a": "Break the task into a tiny 5-minute starter step. Momentum reduces cognitive friction, making continued work much easier.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "What is the best way to prioritize daily tasks?",
                        "a": "Use the Eisenhower Matrix: categorize by urgent vs important. Prioritize important non-urgent work before it becomes an emergency.",
                        "difficulty": "moderate"
                    }
                ]
            },
            {
                "name": "Social Etiquette & Conversation",
                "concepts": [
                    "Active listening: reflect the speaker's main point before stating your viewpoint.",
                    "Clear brevity: deliver key conclusions first, followed by supporting context if requested.",
                    "Polite declines: express genuine appreciation, decline clearly without excessive excuses, and offer an alternative if possible."
                ],
                "sample_qa": [
                    {
                        "q": "How should I politely decline an invitation I cannot attend?",
                        "a": "Thank them warmly for thinking of you, clearly state that you are unable to make it, and wish them a wonderful time.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Home & Everyday Problem Solving",
                "concepts": [
                    "Safe grease fires: never use water; smother the flame with a lid or baking soda.",
                    "Stubborn stains: treat protein stains with cold water and grease stains with dish detergent.",
                    "Basic pantry meal: combine a grain, a protein, sautéed aromatics, and an acid (lemon or vinegar) for balanced flavor."
                ],
                "sample_qa": [
                    {
                        "q": "What should I do if oil catches fire in a frying pan?",
                        "a": "Turn off the burner immediately and slide a metal lid over the pan to cut off oxygen. Never pour water on burning oil.",
                        "difficulty": "simple"
                    }
                ]
            }
        ]
    },

    "mathematics": {
        "id": "mathematics",
        "title": "Mathematics & Logical Reasoning",
        "icon": "📐",
        "description": "Mental math shortcuts, arithmetic, percentages, fractions, unit conversions, geometry, algebra, and everyday finance.",
        "topics": [
            {
                "name": "Mental Arithmetic & Shortcuts",
                "concepts": [
                    "Multiplication by 5: halve the number and multiply by 10 (e.g. 48 * 5 = 24 * 10 = 240).",
                    "Multiplication by 9: multiply by 10 and subtract the original number (e.g. 37 * 9 = 370 - 37 = 333).",
                    "Squaring numbers ending in 5: multiply tens digit n by (n+1) and append 25 (e.g. 65^2 = 6*7 and 25 = 4225)."
                ],
                "sample_qa": [
                    {
                        "q": "What is 84 multiplied by 5?",
                        "a": "84 multiplied by 5 is 420. Half of 84 is 42, and multiplying by 10 gives 420.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "What is 15 percent of 80?",
                        "a": "15 percent of 80 is 12. Ten percent is 8, five percent is 4, and 8 plus 4 equals 12.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Unit Conversions & Real-World Formulas",
                "concepts": [
                    "Temperature: Celsius to Fahrenheit is (C * 9/5) + 32. Quick estimate: double Celsius and add 30.",
                    "Distance: 1 mile is approximately 1.6 kilometers; 1 kilometer is approximately 0.62 miles.",
                    "Weight: 1 kilogram is approximately 2.2 pounds; 1 pound is approximately 454 grams.",
                    "Pythagorean theorem: in a right triangle, a^2 + b^2 = c^2."
                ],
                "sample_qa": [
                    {
                        "q": "How many kilometers are in 10 miles?",
                        "a": "10 miles is approximately 16.1 kilometers, using the conversion factor of 1 mile equaling roughly 1.609 km.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "A right triangle has legs of length 6 and 8. What is the hypotenuse?",
                        "a": "The hypotenuse is 10. By the Pythagorean theorem: 6 squared (36) plus 8 squared (64) equals 100, and the square root of 100 is 10.",
                        "difficulty": "moderate"
                    }
                ]
            },
            {
                "name": "Everyday Financial Math",
                "concepts": [
                    "Discounts: a 25% discount means you pay 75% of the original price (multiply by 0.75).",
                    "Rule of 72: divide 72 by the annual interest rate to estimate how many years it takes an investment to double.",
                    "Compound interest: A = P * (1 + r/n)^(nt), where interest earns interest over time."
                ],
                "sample_qa": [
                    {
                        "q": "If an item costs $120 and has a 20% discount, what is the final price?",
                        "a": "The discount is $24 (20% of 120), so the final price before tax is $96.",
                        "difficulty": "simple"
                    }
                ]
            }
        ]
    },

    "science": {
        "id": "science",
        "title": "Natural Science (Physics, Chemistry & Biology)",
        "icon": "🔬",
        "description": "Fundamental physics laws, chemical reactions, periodic table, cells, genetics, human anatomy, and ecological balance.",
        "topics": [
            {
                "name": "Physics Fundamentals",
                "concepts": [
                    "Newton's First Law (Inertia): an object remains at rest or in uniform motion unless acted upon by a net external force.",
                    "Newton's Second Law: Force equals mass times acceleration (F = m*a).",
                    "Newton's Third Law: For every action, there is an equal and opposite reaction.",
                    "Conservation of Energy: energy cannot be created or destroyed, only transformed between kinetic, potential, thermal, and chemical forms.",
                    "Ohm's Law: Voltage equals Current times Resistance (V = I * R)."
                ],
                "sample_qa": [
                    {
                        "q": "What is Newton's first law of motion?",
                        "a": "Newton's first law, the law of inertia, states that an object will stay at rest or in steady motion in a straight line unless acted on by an outside force.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "Why does a ball fall at the same acceleration regardless of its weight in a vacuum?",
                        "a": "In a vacuum without air resistance, gravitational acceleration (g ≈ 9.8 m/s²) acts equally on all masses because gravitational force is directly proportional to mass (F = m*g).",
                        "difficulty": "moderate"
                    }
                ]
            },
            {
                "name": "Chemistry & Matter",
                "concepts": [
                    "Atomic structure: protons (positive) and neutrons (neutral) form the nucleus, surrounded by electrons (negative).",
                    "Water molecule (H2O): polar covalent molecule with hydrogen bonding, giving it a high boiling point and making ice float.",
                    "Acids and Bases: pH scale ranges from 0 to 14. 7 is neutral, below 7 is acidic (excess H+ ions), and above 7 is basic/alkaline (excess OH- ions)."
                ],
                "sample_qa": [
                    {
                        "q": "What makes water unique compared to most other liquids when it freezes?",
                        "a": "Water expands when freezing because its hydrogen bonds form a crystalline lattice, making ice less dense than liquid water so it floats.",
                        "difficulty": "moderate"
                    }
                ]
            },
            {
                "name": "Biology & Living Systems",
                "concepts": [
                    "The Cell: the fundamental unit of life. The nucleus stores genetic code, mitochondria generate ATP energy, and ribosomes synthesize proteins.",
                    "Photosynthesis: plants convert carbon dioxide, water, and sunlight into glucose and oxygen (6CO2 + 6H2O -> C6H12O6 + 6O2).",
                    "Circulatory system: the heart pumps oxygenated blood from the left ventricle through arteries, and veins return deoxygenated blood."
                ],
                "sample_qa": [
                    {
                        "q": "What is the primary role of mitochondria in human cells?",
                        "a": "Mitochondria are the powerhouses of the cell; they produce ATP energy through cellular respiration using oxygen and nutrients.",
                        "difficulty": "simple"
                    }
                ]
            }
        ]
    },

    "technology": {
        "id": "technology",
        "title": "Technology, Computing & Artificial Intelligence",
        "icon": "💻",
        "description": "Computer architecture, operating systems, networking, internet protocols, coding fundamentals, algorithms, cybersecurity, and AI.",
        "topics": [
            {
                "name": "Computer Hardware & Architecture",
                "concepts": [
                    "CPU: Central Processing Unit executes instructions via fetch, decode, execute, and writeback cycles.",
                    "RAM vs Storage: RAM provides ultra-fast volatile working memory for active processes; SSDs/HDDs provide persistent non-volatile storage.",
                    "GPU: Graphics Processing Units contain thousands of lightweight parallel cores ideal for matrix operations, graphics rendering, and AI tensor computation."
                ],
                "sample_qa": [
                    {
                        "q": "What is the difference between RAM and storage?",
                        "a": "RAM is fast, temporary memory used by running programs that clears when powered off, while storage (SSD/HDD) holds your operating system and files permanently.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Networking & The Internet",
                "concepts": [
                    "DNS (Domain Name System): translates human-friendly domain names (like google.com) into machine-readable IP addresses.",
                    "HTTP vs HTTPS: HTTPS encrypts traffic using TLS/SSL, preventing eavesdropping and tampering between client and server.",
                    "TCP vs UDP: TCP guarantees ordered, reliable delivery via handshakes and packet retransmission; UDP favors raw speed without delivery confirmation."
                ],
                "sample_qa": [
                    {
                        "q": "What does DNS do on the internet?",
                        "a": "DNS acts as the phonebook of the internet by translating readable domain names into the numerical IP addresses computers use to route data.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Artificial Intelligence & Software",
                "concepts": [
                    "LLM (Large Language Model): deep neural network trained to predict next tokens given a prompt context.",
                    "Parameters vs Context: parameters are learned neural weights from training; context window is the immediate active memory buffer.",
                    "API (Application Programming Interface): standardized protocol allowing different software programs to communicate and exchange data."
                ],
                "sample_qa": [
                    {
                        "q": "What is an API in software engineering?",
                        "a": "An API is a defined interface that allows two software applications to talk to each other and request services or data securely.",
                        "difficulty": "simple"
                    }
                ]
            }
        ]
    },

    "world_history_geography": {
        "id": "world_history_geography",
        "title": "World History & Geography",
        "icon": "🌍",
        "description": "Major historical eras, scientific revolutions, continents, oceans, world capitals, geographic landmarks, and historical milestones.",
        "topics": [
            {
                "name": "World Geography Foundations",
                "concepts": [
                    "Seven Continents: Asia (largest), Africa, North America, South America, Antarctica, Europe, Australia.",
                    "Five Oceans: Pacific (largest and deepest), Atlantic, Indian, Southern, Arctic.",
                    "Equator and Prime Meridian: Equator divides Northern/Southern hemispheres (0° latitude); Prime Meridian divides Eastern/Western (0° longitude in Greenwich)."
                ],
                "sample_qa": [
                    {
                        "q": "What is the largest ocean on Earth?",
                        "a": "The Pacific Ocean is the largest and deepest ocean on Earth, covering more than 30 percent of the planet's surface.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "What is the capital of Japan?",
                        "a": "The capital of Japan is Tokyo.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Pivotal Historical Turning Points",
                "concepts": [
                    "Agricultural Revolution: transition from nomadic foraging to settled farming around 10,000 BCE enabled cities and civilization.",
                    "The Printing Press (c. 1440): Gutenberg's invention democratized literacy and catalyzed the Scientific Revolution.",
                    "Industrial Revolution (18th-19th c.): transition from handcraft to steam and mechanization fundamentally reshaped human labor and cities.",
                    "Moon Landing (1969): Apollo 11 marked the first human footsteps on an extraterrestrial body."
                ],
                "sample_qa": [
                    {
                        "q": "Why was the invention of the printing press so significant?",
                        "a": "Gutenberg's movable-type printing press made books affordable and widely accessible, accelerating the spread of scientific knowledge and literacy across the world.",
                        "difficulty": "moderate"
                    }
                ]
            }
        ]
    },

    "language_communication": {
        "id": "language_communication",
        "title": "Language, Communication & Clear Thinking",
        "icon": "💬",
        "description": "Concise speech, vocabulary, active voice, rhetorical precision, logical reasoning, and summarizing complex ideas clearly.",
        "topics": [
            {
                "name": "Clarity & Concise Communication",
                "concepts": [
                    "Bottom-Line Up Front (BLUF): deliver the core answer or recommendation first, followed by necessary nuance.",
                    "Active voice: place the actor before the action (e.g. 'The team completed the project' instead of 'The project was completed by the team').",
                    "Eliminating filler: avoid redundant qualifiers like 'essentially', 'needless to say', and 'in order to'."
                ],
                "sample_qa": [
                    {
                        "q": "What does Bottom-Line Up Front mean in communication?",
                        "a": "BLUF means stating your main conclusion or answer in the very first sentence so the listener immediately understands the outcome.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Critical Thinking & Cognitive Biases",
                "concepts": [
                    "Confirmation bias: the tendency to favor information that confirms pre-existing beliefs while discounting contrary evidence.",
                    "First-principles reasoning: breaking a problem down to its most fundamental truths and reasoning upward from there.",
                    "Correlation vs Causation: just because two events happen together does not mean one caused the other."
                ],
                "sample_qa": [
                    {
                        "q": "What is the difference between correlation and causation?",
                        "a": "Correlation means two things happen at the same time, whereas causation proves that one event directly caused the other to occur.",
                        "difficulty": "simple"
                    }
                ]
            }
        ]
    },

    "health_wellness": {
        "id": "health_wellness",
        "title": "Health, Wellness & Human Performance",
        "icon": "🍎",
        "description": "Sleep hygiene, nutrition fundamentals, hydration, physical recovery, stress regulation, and basic first aid.",
        "topics": [
            {
                "name": "Sleep & Circadian Science",
                "concepts": [
                    "Sleep Cycles: humans alternate through 90-minute cycles of NREM (deep restorative sleep) and REM (dreaming and memory consolidation).",
                    "Circadian Rhythm: the 24-hour internal clock regulated by the suprachiasmatic nucleus, heavily influenced by morning light and darkness.",
                    "Sleep Hygiene: cool room temperature (~18-20°C / 65-68°F), dark room, and limiting screens 1 hour before sleep optimize sleep depth."
                ],
                "sample_qa": [
                    {
                        "q": "Why is deep sleep important for the human body?",
                        "a": "Deep sleep repairs muscle tissue, strengthens the immune system, clears cellular metabolic waste from the brain, and restores physical energy.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Hydration, Nutrition & Movement",
                "concepts": [
                    "Hydration: water supports joint lubrication, cognitive focus, body temperature regulation, and waste removal.",
                    "Macronutrients: proteins provide amino acids for repair; carbohydrates provide immediate glycogen; fats support hormone production and cellular membranes.",
                    "Posture & Movement: taking 2-minute movement breaks every 45 minutes of sitting prevents musculoskeletal strain and boosts alertness."
                ],
                "sample_qa": [
                    {
                        "q": "How much water should an average adult drink daily?",
                        "a": "A healthy guideline is roughly 2 to 3 liters (about 8 to 12 cups) per day, adjusted for climate and physical activity levels.",
                        "difficulty": "simple"
                    }
                ]
            }
        ]
    },

    "how_things_work": {
        "id": "how_things_work",
        "title": "How Things Work & Everyday Mechanics",
        "icon": "⚙️",
        "description": "Mechanical principles behind household appliances, transportation, engines, electronic displays, batteries, and natural phenomena.",
        "topics": [
            {
                "name": "Household Technology Mechanics",
                "concepts": [
                    "Refrigerator: circulates a refrigerant fluid that evaporates inside the coils (absorbing heat) and condenses outside (releasing heat).",
                    "Microwave oven: uses a magnetron tube to emit electromagnetic waves that vibrate water molecules in food, generating dielectric heat.",
                    "Air Conditioner: operates on the refrigeration cycle, extracting indoor heat and moisture and pumping it outside."
                ],
                "sample_qa": [
                    {
                        "q": "How does a microwave oven heat food so quickly?",
                        "a": "It emits microwaves that cause polar water molecules inside the food to rapidly rotate and vibrate, producing friction that heats the food directly from within.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "How does a refrigerator keep food cold?",
                        "a": "It compresses a refrigerant into a liquid, then allows it to expand inside cooling coils where it absorbs heat from inside the fridge and vents it out back.",
                        "difficulty": "moderate"
                    }
                ]
            },
            {
                "name": "Transportation & Flight",
                "concepts": [
                    "Airplane lift: wings (airfoils) deflect oncoming airflow downward, producing an equal and opposite upward lift force (Bernoulli effect & Newton's 3rd law).",
                    "Four forces of flight: Lift (up), Weight/Gravity (down), Thrust (forward), and Drag (backward).",
                    "Internal Combustion Engine: operates on four strokes: Intake (fuel/air drawn in), Compression, Power (spark ignites fuel), and Exhaust."
                ],
                "sample_qa": [
                    {
                        "q": "What are the four primary forces acting on an airplane in flight?",
                        "a": "The four forces are Lift (upward), Weight or Gravity (downward), Thrust (forward from engines), and Drag (backward air resistance).",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Everyday Physics in the World",
                "concepts": [
                    "Why the sky is blue: Rayleigh scattering scatters shorter blue wavelengths of sunlight far more than longer red wavelengths.",
                    "Touchscreens: capacitive screens detect the tiny electrical charge carried by your finger when it touches the glass grid.",
                    "GPS: calculates your precise position on Earth by measuring signal transit times from at least four orbiting satellites."
                ],
                "sample_qa": [
                    {
                        "q": "Why is the sky blue during the day?",
                        "a": "Earth's atmosphere scatters sunlight in all directions; because blue light travels in shorter, smaller waves, it scatters more than other colors (Rayleigh scattering).",
                        "difficulty": "simple"
                    }
                ]
            }
        ]
    },

    "kuwait_local": {
        "id": "kuwait_local",
        "title": "Kuwait Places & Kuwaiti Dialect",
        "icon": "KW",
        "description": "Kuwait governorates and areas, Kuwaiti-accent place names in English and Arabic, and local travel-time phrases.",
        "topics": [
            {
                "name": "Kuwait Governorates & Major Areas",
                "concepts": [
                    "Six governorates: Capital, Hawalli, Farwaniya, Ahmadi, Jahra, Mubarak Al-Kabeer.",
                    "Hawalli areas: Salmiya, Hawalli, Jabriya, Hiteen (حطين), Mishrif (مشرف), Salwa, Bayan, Rumaithiya, Surra, Shaab.",
                    "Capital areas: Sharq, Qibla, Shuwaikh, Kaifan, Khaldiya, Rawda, Yarmouk, Qortuba, Kuwait Towers.",
                    "Landmarks: Kuwait Airport, The Avenues, 360 Mall, Marina Mall, Assima."
                ],
                "sample_qa": [
                    {
                        "q": "Where is Hiteen in Kuwait?",
                        "a": "Hiteen (Hitteen / Hitin / حطين) is in Hawalli Governorate, near Bayan and Surra.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "Where is Mishrif?",
                        "a": "Mishrif (Mishref / مشرف) is in Hawalli Governorate, south of Salwa.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "Name the six Kuwait governorates.",
                        "a": "Capital, Hawalli, Farwaniya, Ahmadi, Jahra, and Mubarak Al-Kabeer.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Kuwaiti Accent Place Names (EN and AR)",
                "concepts": [
                    "Romanization varies: Hiteen/Hitteen/Hitin = حطين; Mishrif/Mishref = مشرف; Salmiya/Salmiyah = السالمية; Jahra = الجهراء.",
                    "People often drop Al- when speaking English: السالمية becomes Salmiya.",
                    "Arabizi examples: mn hiteen l mishref; km takhdh mn salmiya l jahra.",
                    "Direction asks: من X ل Y / كم تاخذ من X ل Y / how long from X to Y."
                ],
                "sample_qa": [
                    {
                        "q": "If someone says Hitteen, what area do they mean?",
                        "a": "Hiteen / حطين in Hawalli — same as Hiteen or Hitin.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "What does من حطين لمشرف mean?",
                        "a": "From Hiteen to Mishrif — a travel-time request between two Hawalli areas.",
                        "difficulty": "simple"
                    }
                ]
            },
            {
                "name": "Travel Time Phrases",
                "concepts": [
                    "English: how long from A to B, ETA from A to B, minutes from A to B.",
                    "Kuwaiti Arabic: كم تاخذ من A ل B، من A ل B، مسافة بين A و B.",
                    "Jarvis answers in English minutes by default using free OpenStreetMap routing and a local Kuwait atlas.",
                    "Say walk or على رجلي for walking ETA."
                ],
                "sample_qa": [
                    {
                        "q": "Someone asks: how long from Hiteen to Mishrif?",
                        "a": "Treat it as a Kuwait driving ETA between Hiteen and Mishrif and answer with approximate minutes.",
                        "difficulty": "simple"
                    },
                    {
                        "q": "Someone says: كم تاخذ من السالمية للجهراء؟",
                        "a": "They want drive time from Salmiya to Jahra; answer in English minutes unless they asked for Arabic.",
                        "difficulty": "moderate"
                    }
                ]
            }
        ]
    },
}


# ---------------------------------------------------------------------------
# Advanced / complex domains — push toward broad general knowledge
# (Layer 1 still won't equal ChatGPT; Hermes remains the deep brain.)
# ---------------------------------------------------------------------------

_ADVANCED: dict[str, dict[str, Any]] = {
    "computer_science": {
        "id": "computer_science",
        "title": "Computer Science & Algorithms",
        "icon": "CS",
        "description": "Data structures, algorithms, complexity, OS, networking, databases, cryptography, distributed systems.",
        "topics": [
            {
                "name": "Algorithms & Complexity",
                "concepts": [
                    "Big-O: O(1), O(log n), O(n), O(n log n), O(n²) describe how runtime grows with input size.",
                    "Binary search requires sorted data and halves the search space each step → O(log n).",
                    "Hash tables average O(1) lookup; worst case O(n) with collisions.",
                    "Dijkstra finds shortest paths in weighted graphs with non-negative edges.",
                    "Dynamic programming: break problems into overlapping subproblems and memoize.",
                ],
                "sample_qa": [
                    {"q": "What is the time complexity of binary search?", "a": "O(log n) comparisons on a sorted array, because each step halves the remaining range.", "difficulty": "moderate"},
                    {"q": "When would you use a hash map vs a balanced BST?", "a": "Hash maps give average O(1) lookups without order; balanced BSTs keep keys sorted with O(log n) operations.", "difficulty": "complex"},
                ],
            },
            {
                "name": "Systems & Networking",
                "concepts": [
                    "OSI / TCP-IP: application → transport (TCP/UDP) → network (IP) → link.",
                    "Processes vs threads: processes isolate memory; threads share an address space.",
                    "CAP theorem: in a partition, a distributed system must choose consistency or availability.",
                    "ACID transactions: Atomicity, Consistency, Isolation, Durability.",
                ],
                "sample_qa": [
                    {"q": "What does TCP guarantee that UDP does not?", "a": "Reliable, ordered delivery with retransmission and congestion control; UDP is fire-and-forget.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "artificial_intelligence": {
        "id": "artificial_intelligence",
        "title": "AI, ML & Deep Learning",
        "icon": "AI",
        "description": "ML basics, neural nets, transformers, training, evaluation, alignment, practical LLM use.",
        "topics": [
            {
                "name": "Machine Learning Foundations",
                "concepts": [
                    "Supervised vs unsupervised vs reinforcement learning.",
                    "Overfitting: model memorizes training noise; fix with regularization, more data, simpler models.",
                    "Train/validation/test splits prevent optimistic evaluation.",
                    "Gradient descent updates weights opposite the loss gradient.",
                ],
                "sample_qa": [
                    {"q": "What is overfitting?", "a": "When a model fits training data too tightly and fails to generalize to new examples.", "difficulty": "moderate"},
                ],
            },
            {
                "name": "Transformers & LLMs",
                "concepts": [
                    "Attention lets each token weigh other tokens; self-attention is the transformer core.",
                    "Pretraining predicts next tokens on huge text; fine-tuning adapts to tasks or preferences.",
                    "Tokens are subword pieces; context length limits how much the model can consider at once.",
                    "Hallucinations: fluent but false outputs — verify critical facts with tools or sources.",
                ],
                "sample_qa": [
                    {"q": "What is self-attention in a transformer?", "a": "A mechanism where each position computes weighted combinations of all positions, letting the model relate words across a sequence.", "difficulty": "complex"},
                ],
            },
        ],
    },
    "physics_advanced": {
        "id": "physics_advanced",
        "title": "Physics (Advanced)",
        "icon": "Φ",
        "description": "Classical mechanics, E&M, thermo, waves, relativity basics, quantum intro.",
        "topics": [
            {
                "name": "Mechanics & Energy",
                "concepts": [
                    "Newton's laws; F=ma; action-reaction pairs.",
                    "Conservation of energy and momentum in closed systems.",
                    "Work-energy theorem: net work equals change in kinetic energy.",
                    "Simple harmonic motion: restoring force proportional to displacement.",
                ],
                "sample_qa": [
                    {"q": "If net force is zero, what can you say about velocity?", "a": "Velocity is constant (including possibly zero) — that is Newton's first law.", "difficulty": "moderate"},
                ],
            },
            {
                "name": "Modern Physics Intro",
                "concepts": [
                    "Special relativity: speed of light constant; time dilation and length contraction at high v.",
                    "E=mc² relates mass and energy.",
                    "Photoelectric effect: light comes in quanta (photons); evidence for particle nature of light.",
                    "Uncertainty principle: limits simultaneous knowledge of position and momentum.",
                ],
                "sample_qa": [
                    {"q": "Why can't anything with mass reach the speed of light in vacuum?", "a": "Relativistic mass-energy grows without bound as v→c, so infinite energy would be required.", "difficulty": "complex"},
                ],
            },
        ],
    },
    "chemistry_advanced": {
        "id": "chemistry_advanced",
        "title": "Chemistry (Advanced)",
        "icon": "⚗",
        "description": "Stoichiometry, bonding, equilibrium, acids/bases, organic basics, thermo.",
        "topics": [
            {
                "name": "Reactions & Equilibrium",
                "concepts": [
                    "Mole concept and balancing equations conserve atoms.",
                    "Le Chatelier: system shifts to counteract imposed change.",
                    "pH = -log[H+]; strong acids fully dissociate.",
                    "Exothermic vs endothermic; catalysts lower activation energy without changing ΔG.",
                ],
                "sample_qa": [
                    {"q": "What does a catalyst do to a reaction?", "a": "It speeds the reaction by lowering activation energy but is not consumed and does not change the equilibrium position.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "biology_advanced": {
        "id": "biology_advanced",
        "title": "Biology & Life Sciences",
        "icon": "🧬",
        "description": "Cell biology, genetics, evolution, physiology, ecology, microbiology.",
        "topics": [
            {
                "name": "Cells, DNA & Evolution",
                "concepts": [
                    "Central dogma: DNA → RNA → protein.",
                    "Mitosis vs meiosis; haploid gametes.",
                    "Natural selection: heritable variation + differential reproductive success.",
                    "Mitochondria produce ATP via oxidative phosphorylation.",
                ],
                "sample_qa": [
                    {"q": "What is the central dogma of molecular biology?", "a": "Genetic information generally flows from DNA to RNA to protein.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "economics_finance": {
        "id": "economics_finance",
        "title": "Economics & Finance",
        "icon": "$",
        "description": "Micro/macro basics, markets, inflation, interest, investing, opportunity cost.",
        "topics": [
            {
                "name": "Markets & Macro",
                "concepts": [
                    "Supply and demand set prices; shortages raise price, surpluses lower it.",
                    "Opportunity cost: value of the next-best alternative foregone.",
                    "Inflation: rising general price level; real vs nominal values.",
                    "Diversification reduces unsystematic risk in portfolios.",
                ],
                "sample_qa": [
                    {"q": "What is opportunity cost?", "a": "The value of the best alternative you give up when you choose something else.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "philosophy_logic": {
        "id": "philosophy_logic",
        "title": "Philosophy, Logic & Ethics",
        "icon": "Φ?",
        "description": "Logical fallacies, epistemology, ethics frameworks, classic arguments.",
        "topics": [
            {
                "name": "Logic & Ethics",
                "concepts": [
                    "Valid vs sound arguments; premises must support conclusions.",
                    "Straw man, ad hominem, false dilemma, slippery slope fallacies.",
                    "Utilitarianism: maximize overall welfare; deontology: duty/rules; virtue ethics: character.",
                    "Occam's razor: prefer simpler explanations that fit the facts.",
                ],
                "sample_qa": [
                    {"q": "What is a straw man fallacy?", "a": "Misrepresenting someone's argument in a weaker form so it is easier to attack.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "psychology_sociology": {
        "id": "psychology_sociology",
        "title": "Psychology & Social Science",
        "icon": "Ψ",
        "description": "Cognitive biases, learning, motivation, social influence, research basics.",
        "topics": [
            {
                "name": "Mind & Behavior",
                "concepts": [
                    "Working memory is limited (~4 chunks); spaced repetition beats cramming.",
                    "System 1 (fast intuitive) vs System 2 (slow deliberate) thinking.",
                    "Fundamental attribution error: over-credit personality, under-credit situation.",
                    "Placebo effect: expectations can change subjective and sometimes physiological outcomes.",
                ],
                "sample_qa": [
                    {"q": "Why is spaced repetition effective?", "a": "Revisiting material just as you begin to forget strengthens long-term memory more than massed practice.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "engineering_design": {
        "id": "engineering_design",
        "title": "Engineering & Design Thinking",
        "icon": "⚙+",
        "description": "Systems thinking, tradeoffs, reliability, feedback loops, estimation.",
        "topics": [
            {
                "name": "Systems & Tradeoffs",
                "concepts": [
                    "Every design has tradeoffs: cost, performance, reliability, complexity.",
                    "Feedback loops: negative feedback stabilizes; positive feedback amplifies.",
                    "Fermi estimation: break unknown quantities into factors you can approximate.",
                    "Redundancy and fail-safes improve reliability at the cost of complexity.",
                ],
                "sample_qa": [
                    {"q": "What is a Fermi estimate?", "a": "A rough order-of-magnitude calculation made by decomposing a hard quantity into estimable parts.", "difficulty": "complex"},
                ],
            },
        ],
    },
    "law_civics": {
        "id": "law_civics",
        "title": "Law, Civics & Institutions",
        "icon": "§",
        "description": "Basic legal concepts, rights, contracts, how governments and courts work (general knowledge, not legal advice).",
        "topics": [
            {
                "name": "Legal & Civic Basics",
                "concepts": [
                    "Civil vs criminal law; burden of proof differs.",
                    "Contracts generally need offer, acceptance, and consideration.",
                    "Separation of powers: legislative, executive, judicial checks.",
                    "Intellectual property: copyright, patents, trademarks protect different creations.",
                ],
                "sample_qa": [
                    {"q": "What is the difference between civil and criminal cases?", "a": "Criminal cases are prosecuted by the state for offenses against society; civil cases resolve disputes between private parties, usually for remedies like damages.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "literature_arts": {
        "id": "literature_arts",
        "title": "Literature, Arts & Culture",
        "icon": "✎",
        "description": "Literary devices, major movements, storytelling structure, visual/music basics.",
        "topics": [
            {
                "name": "Story & Style",
                "concepts": [
                    "Narrative arc: setup, confrontation, resolution; character vs plot.",
                    "Metaphor, irony, foreshadowing, unreliable narrator.",
                    "Theme is the underlying idea; motif is a recurring concrete element.",
                    "Show vs tell: dramatize with action and detail rather than abstract labels.",
                ],
                "sample_qa": [
                    {"q": "What is foreshadowing?", "a": "Hints placed early in a story that prepare the audience for later events.", "difficulty": "simple"},
                ],
            },
        ],
    },
    "medicine_first_aid": {
        "id": "medicine_first_aid",
        "title": "Medicine Literacy & First Aid",
        "icon": "+",
        "description": "Body systems overview, common conditions literacy, emergency first aid (not a substitute for a doctor).",
        "topics": [
            {
                "name": "Body & Emergencies",
                "concepts": [
                    "CPR: compressions hard and fast on center of chest; call emergency services.",
                    "Stroke FAST: Face droop, Arm weakness, Speech difficulty, Time to call help.",
                    "Antibiotics treat bacteria, not viruses.",
                    "Homeostasis keeps internal conditions in a narrow healthy range.",
                ],
                "sample_qa": [
                    {"q": "What does the FAST acronym for stroke mean?", "a": "Face drooping, Arm weakness, Speech difficulty, Time to call emergency services immediately.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "earth_environment": {
        "id": "earth_environment",
        "title": "Earth Science & Environment",
        "icon": "🌎",
        "description": "Climate, geology, weather, ecosystems, energy, sustainability.",
        "topics": [
            {
                "name": "Climate & Earth Systems",
                "concepts": [
                    "Greenhouse effect: gases trap outgoing infrared; amplified by CO₂/methane rise.",
                    "Plate tectonics: crustal plates move, causing earthquakes and volcanoes.",
                    "Water cycle: evaporation, condensation, precipitation, runoff.",
                    "Biodiversity supports ecosystem resilience and services humans depend on.",
                ],
                "sample_qa": [
                    {"q": "What is the greenhouse effect?", "a": "Atmospheric gases absorb and re-radiate infrared energy from Earth, warming the surface; human emissions intensify this.", "difficulty": "moderate"},
                ],
            },
        ],
    },
    "world_religions_culture": {
        "id": "world_religions_culture",
        "title": "World Cultures & Belief Systems",
        "icon": "☪✝",
        "description": "Comparative overview of major traditions and cultural literacy (respectful, factual).",
        "topics": [
            {
                "name": "Cultural Literacy",
                "concepts": [
                    "Abrahamic traditions: Judaism, Christianity, Islam share related monotheistic roots.",
                    "Five Pillars of Islam: shahada, salat, zakat, sawm, hajj.",
                    "Hinduism and Buddhism differ on atman/anatman and paths to liberation.",
                    "Cultural relativism vs universal human rights — tension in ethics debates.",
                ],
                "sample_qa": [
                    {"q": "What are the Five Pillars of Islam?", "a": "Faith declaration (shahada), prayer (salat), charity (zakat), fasting in Ramadan (sawm), and pilgrimage to Mecca (hajj) if able.", "difficulty": "moderate"},
                ],
            },
        ],
    },
}

SUBJECTS.update(_ADVANCED)

# Domains for open-world deep study (LLM invents advanced Q&A beyond fixed concepts)
OPEN_WORLD_DOMAINS: list[str] = [
    "advanced calculus and linear algebra intuition",
    "probability, statistics, and causal inference",
    "quantum computing basics",
    "compiler design and programming language theory",
    "cybersecurity and threat models",
    "robotics and control systems",
    "molecular biology and CRISPR",
    "neuroscience of learning and memory",
    "game theory and mechanism design",
    "international relations and geopolitics",
    "architectural history and urban design",
    "music theory and acoustics",
    "linguistics and language acquisition",
    "astronomy and cosmology",
    "materials science and semiconductors",
    "operations research and optimization",
    "behavioral economics",
    "constitutional law concepts (general knowledge)",
    "epidemiology and public health",
    "climate modeling and energy systems",
    "human-computer interaction",
    "database internals and query optimization",
    "distributed consensus (Paxos/Raft intuition)",
    "information theory (entropy, compression)",
    "ethics of AI and dual-use technology",
    "Kuwait history, Gulf politics, and Arabic rhetoric",
    "advanced English rhetoric and technical writing",
    "mathematical proofs and discrete math",
    "organic chemistry reaction patterns",
    "fluid dynamics intuition for everyday life",
]


def total_curriculum_topics() -> int:
    return sum(len(sub.get("topics", [])) for sub in SUBJECTS.values())


def all_sample_qa() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for sub_id, sub in SUBJECTS.items():
        for topic in sub.get("topics", []):
            for qa in topic.get("sample_qa", []):
                cards.append({
                    "subject_id": sub_id,
                    "subject_title": sub.get("title"),
                    "topic": topic.get("name"),
                    "question": qa.get("q"),
                    "answer": qa.get("a"),
                    "difficulty": qa.get("difficulty", "simple"),
                    "concepts": topic.get("concepts", [])[:2],
                })
    return cards
