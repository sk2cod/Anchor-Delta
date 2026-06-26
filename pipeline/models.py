from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import date

def _coerce_to_str(v):
    """Coerce list values to string for scalar string fields."""
    if isinstance(v, list):
        if len(v) == 1:
            return str(v[0])
        elif len(v) > 1:
            return " | ".join(str(item) for item in v)
        return ""
    return v

def _dedupe_dialogue(turns):
    """Keep only the first DialogueTurn per speaker. Discards subsequent quotes from same speaker."""
    if not isinstance(turns, list):
        return turns
    seen_speakers = set()
    deduped = []
    for turn in turns:
        if isinstance(turn, dict):
            speaker = turn.get('speaker', '').strip().lower()
        elif hasattr(turn, 'speaker'):
            speaker = turn.speaker.strip().lower()
        else:
            continue
        if speaker and speaker not in seen_speakers:
            seen_speakers.add(speaker)
            deduped.append(turn)
    return deduped

class RouteResult(BaseModel):
    classification: str
    card_id: Optional[str] = None
    confidence: str
    reason: str

    @field_validator('classification', 'confidence', 'reason', mode='before')
    @classmethod
    def coerce_strings(cls, v):
        return _coerce_to_str(v)

class DialogueTurn(BaseModel):
    speaker: str
    quote: str

    @field_validator('speaker', 'quote', mode='before')
    @classmethod
    def coerce_strings(cls, v):
        return _coerce_to_str(v)

class ExtractionResult(BaseModel):
    named_actors: list[str]
    dialogue: list[DialogueTurn]
    tactical_moves: list[str]
    event_date: Optional[date] = None
    named_consequences: list[str]
    event_headline: str
    what_happened: str

    @field_validator('dialogue', mode='before')
    @classmethod
    def dedupe_speakers(cls, v):
        return _dedupe_dialogue(v)

    @field_validator('event_headline', 'what_happened', mode='before')
    @classmethod
    def coerce_strings(cls, v):
        return _coerce_to_str(v)

class NewCardResult(BaseModel):
    domain: str
    umbrella_title: str
    anchor_text: str
    tldr: str          # add this — one sentence hook
    event_headline: str
    what_happened: str
    dialogue: list[DialogueTurn]
    event_date: date
    chain_latex: str
    nodes_markdown: str

    @field_validator('dialogue', mode='before')
    @classmethod
    def dedupe_speakers(cls, v):
        return _dedupe_dialogue(v)

    @field_validator('domain', 'umbrella_title', 'anchor_text', 'tldr', 'event_headline', 'what_happened', 'chain_latex', 'nodes_markdown', mode='before')
    @classmethod
    def coerce_strings(cls, v):
        return _coerce_to_str(v)

class DeltaUpdateResult(BaseModel):
    tldr: str          # add this — one sentence hook
    event_headline: str
    what_happened: str
    dialogue: list[DialogueTurn]
    event_date: date
    transmission_needs_update: bool
    chain_latex: Optional[str] = None
    nodes_markdown: Optional[str] = None

    @field_validator('dialogue', mode='before')
    @classmethod
    def dedupe_speakers(cls, v):
        return _dedupe_dialogue(v)

    @field_validator('tldr', 'event_headline', 'what_happened', mode='before')
    @classmethod
    def coerce_strings(cls, v):
        return _coerce_to_str(v)

    @field_validator('chain_latex', 'nodes_markdown', mode='before')
    @classmethod
    def coerce_optional_strings(cls, v):
        if v is None:
            return v
        return _coerce_to_str(v)
