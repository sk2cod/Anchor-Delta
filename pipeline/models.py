from pydantic import BaseModel
from typing import Optional
from datetime import date

class RouteResult(BaseModel):
    classification: str        # "noise" | "existing_card" | "new_frame"
    card_id: Optional[str]     # populated only when classification == "existing_card"
    confidence: str            # "high" | "medium" | "low"
    reason: str                # one sentence explaining the routing decision

class DialogueTurn(BaseModel):
    speaker: str
    quote: str

class ExtractionResult(BaseModel):
    named_actors: list[str]
    dialogue: list[DialogueTurn]
    tactical_moves: list[str]
    event_date: Optional[date]
    named_consequences: list[str]
    event_headline: str
    what_happened: str

class NewCardResult(BaseModel):
    domain: str
    umbrella_title: str
    anchor_text: str
    event_headline: str
    what_happened: str
    dialogue: list[DialogueTurn]
    event_date: date
    chain_latex: str
    nodes_markdown: str

class DeltaUpdateResult(BaseModel):
    event_headline: str
    what_happened: str
    dialogue: list[DialogueTurn]
    event_date: date
    transmission_needs_update: bool
    chain_latex: Optional[str]
    nodes_markdown: Optional[str]
