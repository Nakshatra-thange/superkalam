                         ┌───────────────────┐
                         │    Candidate      │
                         │   🎙️ Mic / Voice  │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │     LiveKit       │
                         │  Voice Session    │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │  VAD / Turn       │
                         │    Detection      │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │     Sarvam STT    │
                         │    saaras:v4      │
                         └─────────┬─────────┘
                                   │
                              Transcript
                                   │
                                   ▼
              ┌─────────────────────────────────────┐
              │             Board LLM               │
              │          Gemma 4 31B IT             │
              │                                     │
              │  • Dynamic questions                │
              │  • Follow-up questions              │
              │  • Board persona                    │
              │  • Challenges vague claims          │
              └──────────────┬──────────────────────┘
                             │
                        Board response
                             │
                             ▼
                     ┌───────────────────┐
                     │    Sarvam TTS     │
                     │     bulbul:v3     │
                     └─────────┬─────────┘
                               │
                               ▼
                         ┌─────────────┐
                         │  Candidate  │
                         │   Speaker   │
                         └─────────────┘


        ┌─────────────────────────────────────────────┐
        │                  SQLite                     │
        │                                             │
        │  DAF Profile ───────┐                       │
        │  Interview History ─┤                       │
        └─────────────────────┼───────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ finish_interview  │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Separate Evaluator│
                    │       LLM         │
                    └─────────┬─────────┘
                              │
                              ▼
               ┌──────────────────────────────┐
               │       6 Dimensions           │
               │                              │
               │ Clarity    • Depth            │
               │ Balance    • Awareness        │
               │ Authenticity • Composure      │
               └──────────────────────────────┘