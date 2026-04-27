from __future__ import annotations
from pydantic import BaseModel, Field
import re
import uuid


# ---------------------------------------------------------------------------
# Entity resolution helpers
# ---------------------------------------------------------------------------
def _normalize(name: str) -> str:
    """Lowercase, strip punctuation/LLC/Inc suffixes for comparison."""
    name = name.lower().strip()
    # Remove common corporate suffixes
    for suffix in [", llc", " llc", ", inc", " inc", ", ltd", " ltd", ", corp", " corp",
                   ", co.", " co.", ".", ","]:
        name = name.replace(suffix, "")
    # Collapse whitespace
    return re.sub(r"\s+", " ", name).strip()


def _name_tokens(name: str) -> set:
    """Split normalized name into word tokens (≥2 chars)."""
    return {t for t in _normalize(name).split() if len(t) >= 2}


def is_same_entity(a: str, b: str) -> bool:
    """
    True if two name strings likely refer to the same real-world entity.
    Used for FACT deduplication — intentionally aggressive.
    Handles: exact match, corporate suffix variants, nickname overlap.
    """
    if not a or not b:
        return False
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    # One is contained in the other (catches "Sisu Capital" in "Sisu Capital, LLC")
    if na in nb or nb in na:
        return True
    # Token overlap: if ≥2 tokens shared, treat as same
    ta, tb = _name_tokens(a), _name_tokens(b)
    shared = ta & tb
    if len(shared) >= 2:
        return True
    return False


def is_duplicate_queue_entry(candidate: str, known_names: list[str]) -> bool:
    """
    True if candidate is already in the investigation queue or searched list.
    Used for QUEUE deduplication — more conservative than is_same_entity.

    Only blocks if:
    - Exact normalized match (same name, different casing/punctuation/suffix)
    - Containment where BOTH first AND last name tokens match (prevents "Hans"
      blocking "Hansueli" just because they share a surname)

    Does NOT block just because two names share a surname token — family members
    with different first names must be investigated separately.
    """
    if not candidate:
        return False
    nc = _normalize(candidate)
    tc = _name_tokens(candidate)

    for known in known_names:
        if not known:
            continue
        nk = _normalize(known)
        tk = _name_tokens(known)

        # Exact normalized match
        if nc == nk:
            return True
        # Containment (e.g. "Sisu Capital" vs "Sisu Capital LLC")
        if nc in nk or nk in nc:
            return True
        # For PERSON names: only consider duplicate if the first name token also matches.
        # This prevents "Hans Overturf" from blocking "Hansueli Overturf".
        # Both must share ≥2 tokens AND one of those tokens must NOT be just the surname.
        shared = tc & tk
        if len(shared) >= 2:
            # Find non-surname tokens (tokens that appear in only one of the names = likely first name)
            # If the shared tokens are ONLY the surname, these are different people
            only_in_candidate = tc - tk
            only_in_known     = tk - tc
            # If both names have unique tokens (different first names), they are different people
            if only_in_candidate and only_in_known:
                # Different first names — NOT a duplicate, must investigate separately
                continue
            return True

    return False


class Entity(BaseModel):
    name:     str
    type:     str = "PERSON"
    priority: int = 5
    context:  str = ""
    searched: bool = False


class Fact(BaseModel):
    subject:    str
    relation:   str
    object:     str
    confidence: float = 0.75
    source_url: str = ""
    quote:      str = ""


class Flag(BaseModel):
    severity:    str
    category:    str
    description: str
    sources:     list[str] = Field(default_factory=list)


class State(BaseModel):
    run_id:            str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    target:            str = ""
    context:           str = ""
    aliases:           list[str]    = Field(default_factory=list)
    iteration:         int = 0
    max_iterations:    int = 8
    queue:             list[Entity] = Field(default_factory=list)
    searched:          list[str]    = Field(default_factory=list)
    done_queries:      list[str]    = Field(default_factory=list)
    raw_text:          str = ""
    facts:             list[Fact]   = Field(default_factory=list)
    flags:             list[Flag]   = Field(default_factory=list)
    stagnation:        int = 0
    concluded:         bool = False
    researcher_model:  str = ""
    analyst_model:     str = ""
    evaluator_model:   str = ""
    suggested_queries: list[str]   = Field(default_factory=list)

    def __getitem__(self, k):    return getattr(self, k)
    def __setitem__(self, k, v): object.__setattr__(self, k, v)
    def keys(self):              return self.model_fields.keys()
    def get(self, k, d=None):   return getattr(self, k, d)
    def items(self):             return self.model_dump().items()
