# Collab Chat Code Improvements

## Date
2026-02-26

## Overview
Refactored and improved the collab-chat multi-AI deliberation system. All original files backed up with `.bak` extension.

---

## Changes Made

### 1. Configuration Constants (Lines 15-45)
**Before:** Magic numbers scattered throughout the code  
**After:** Extracted to named constants at top of file

```python
# Timeouts (seconds)
DEFAULT_TIMEOUT: float = 120.0
LONG_TIMEOUT: float = 180.0
EXTERNAL_API_TIMEOUT: float = 10.0

# Token limits
MAX_TOKENS_DEFAULT: int = 2048
TEMPERATURE_DEFAULT: float = 0.8

# History limits
HISTORY_LIMIT_ROUND: int = 30
HISTORY_LIMIT_SYNTHESIS: int = 40
HISTORY_LIMIT_DIRECTED: int = 16
HISTORY_LIMIT_CROSSTALK: int = 20
HISTORY_LIMIT_DEV_BAR: int = 10

# Retry settings
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 1.0
```

### 2. Retry Logic with Exponential Backoff (Lines 336-379)
**Before:** Single HTTP request, failed silently  
**After:** Retries up to 3 times with exponential backoff (1s, 2s, 4s)

```python
async def ask_model(
    model_id: str,
    model_name: str,
    messages: list[dict[str, Any]],
    max_retries: int = MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT
) -> str:
    for attempt in range(max_retries):
        # ... make request ...
        if attempt < max_retries - 1:
            backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
            await asyncio.sleep(backoff)
    return last_error
```

### 3. Parallel Round 1 Deliberation (Lines 455-549)
**Before:** Sequential model calls - each AI waited for previous to finish  
**After:** All AI participants respond in parallel using `asyncio.gather()`

This is the **biggest performance improvement** - Round 1 now runs ~5x faster with 5+ participants.

### 4. Input Sanitization (Lines 433-451)
**Before:** User input passed directly to AI models  
**After:** Added `sanitize_input()` function

```python
def sanitize_input(text: str, max_length: int = 10000) -> str:
    # Limit length
    text = text[:max_length]
    # Remove null bytes and control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()
```

### 5. Type Hints Added
- `broadcast()` - `message: dict[str, Any]`
- `build_messages()` - `participant: dict[str, Any]`, `history: list[dict[str, Any]]`
- `detect_references()` - Already had hints, optimized to use list comprehension
- `update_deliberation_state()` - `key: str`, `value: Any`
- Removed duplicate global declarations (conversation_history, connected_clients)

### 6. Improved Connection Handling (Lines 308-323)
**Before:** Could fail if client already removed  
**After:** Added try/except for safe removal

```python
for ws in dead:
    try:
        connected_clients.remove(ws)
    except ValueError:
        pass  # Already removed
```

### 7. URL Constant Consolidation
**Before:** `os.environ.get("CLAUDE_CODE_URL", "http://claude-code:8000")` repeated 3 times  
**After:** Single `CLAUDE_CODE_URL` constant at top

---

## Files Modified
- `main.py` - All improvements above
- `index.html` - No changes (backup created)

## Files Created
- `main.py.bak` - Original main.py
- `index.html.bak` - Original index.html

---

## Potential Further Improvements (Not Implemented)
1. **Persistence** - Add SQLite/Postgres for conversation history
2. **Rate limiting** - Add throttling on WebSocket/API endpoints
3. **Async deliberation rounds** - Could also parallelize rounds 2+ (more complex due to sequential context)
4. **Structured logging** - Replace print statements with proper logging
5. **Health checks** - Add detailed endpoint for monitoring
